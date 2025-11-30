/*
  Slack Web API Capture (console-injectable)

  Paste this entire file into the browser console on a Slack web client page
  (e.g. https://app.slack.com or https://<workspace>.slack.com) to intercept
  fetch/XHR calls to Slack's /api/* endpoints and record both request and
  response payloads locally. No network exfiltration; data stays in memory
  until you download it as an NDJSON file.

  Public API exposed as window._slackCapture:
    Core:
    - logs: in-memory array of captured entries
    - setFilter([/regex/, ...]): include-only URL filters (optional)
    - clear(): clear in-memory logs
    - exportNdjson(): return NDJSON string
    - download(filename?): trigger NDJSON download
    - stop(): restore original fetch/XHR and stop capturing
    - status(): { count, userCount, memoryEstimate }

    Config:
    - setConfig(options): update runtime configuration
    - getConfig(): get current configuration

    User Capture (optional):
    - enableUserCapture(): start collecting user info from API responses
    - disableUserCapture(): stop collecting user info
    - getUsers(): get Map of collected users
    - downloadUsers(filename?): download users as NDJSON

  Security Features:
    - Sensitive headers (authorization, cookie) are automatically excluded
    - Token values in request bodies are masked (xoxb-****, xoxp-****, etc.)

  Memory Management:
    - Default log limit: 10,000 entries (configurable via setConfig)
    - Oldest entries are automatically removed when limit is exceeded
*/

(function () {
  if (window._slackCapture) {
    console.warn("slack capture: already installed");
    return;
  }

  // ---------- Configuration ----------
  const cfg = {
    include: null, // array of regexes; if set, only matching URLs are captured
    apiHostnamePattern: /\.slack\.com\/api\//,
    maxLogSize: 10000,
    excludeHeaders: ["authorization", "cookie", "x-slack-req-resource", "x-xss-protection"],
    maskTokens: true,
    userCaptureEnabled: true,
    verbose: false,
  };

  // ---------- State ----------
  const logs = [];
  const users = new Map(); // id -> user object

  // ---------- Security helpers ----------
  /**
   * Remove or mask sensitive headers
   * @param {Object} headers - Header object
   * @returns {Object} Sanitized headers
   */
  function sanitizeHeaders(headers) {
    if (!headers || typeof headers !== "object") return {};
    const result = {};
    for (const [key, value] of Object.entries(headers)) {
      const lowerKey = key.toLowerCase();
      if (cfg.excludeHeaders.includes(lowerKey)) {
        continue; // Skip sensitive headers entirely
      }
      result[key] = value;
    }
    return result;
  }

  /**
   * Mask token values in text (xoxb-****, xoxp-****, xoxs-****, etc.)
   * @param {string} text - Text that may contain tokens
   * @returns {string} Text with masked tokens
   */
  function maskTokenValue(text) {
    if (!cfg.maskTokens || !text || typeof text !== "string") return text;
    // Match Slack token patterns: xoxb-, xoxp-, xoxs-, xoxa-, xoxr-
    return text.replace(/xox[abspre]-[A-Za-z0-9-]+/g, (match) => {
      const prefix = match.slice(0, 5); // e.g., "xoxb-"
      return prefix + "****";
    });
  }

  /**
   * Sanitize request body text
   * @param {string} bodyText - Request body as text
   * @returns {string} Sanitized body text
   */
  function sanitizeBodyText(bodyText) {
    if (!bodyText || typeof bodyText !== "string") return bodyText;
    return maskTokenValue(bodyText);
  }

  // ---------- Memory management ----------
  function trimLogs() {
    if (cfg.maxLogSize > 0 && logs.length > cfg.maxLogSize) {
      const removeCount = logs.length - cfg.maxLogSize;
      logs.splice(0, removeCount);
      if (cfg.verbose) {
        console.debug("[slack-capture] trimmed", removeCount, "old entries");
      }
    }
  }

  function estimateMemoryUsage() {
    try {
      const logsSize = JSON.stringify(logs).length;
      const usersSize = JSON.stringify(Array.from(users.values())).length;
      const totalBytes = logsSize + usersSize;
      if (totalBytes < 1024) return `${totalBytes}B`;
      if (totalBytes < 1024 * 1024) return `${(totalBytes / 1024).toFixed(1)}KB`;
      return `${(totalBytes / (1024 * 1024)).toFixed(1)}MB`;
    } catch (e) {
      return "unknown";
    }
  }

  // ---------- Record handler ----------
  const onRecord = (entry) => {
    try {
      logs.push(entry);
      trimLogs();

      // Process user capture if enabled
      if (cfg.userCaptureEnabled) {
        processEntryForUsers(entry);
      }

      if (cfg.verbose) {
        const summary =
          entry.response && entry.response.json && entry.response.json.pagination
            ? `status=${entry.response.status} items=${(entry.response.json.items || []).length} page=${entry.response.json.pagination.page}`
            : `status=${entry.response ? entry.response.status : "?"}`;
        console.debug("[slack-capture]", entry.method, entry.url, summary);
      }
    } catch (e) {
      if (cfg.verbose) {
        console.debug("[slack-capture] recorded", entry.url, "error:", e.message);
      }
    }
  };

  function shouldCapture(url) {
    if (!url || !cfg.apiHostnamePattern.test(url)) return false;
    if (Array.isArray(cfg.include) && cfg.include.length > 0) {
      return cfg.include.some((re) => re.test(url));
    }
    return true;
  }

  // ---------- fetch hook ----------
  const originalFetch = window.fetch;
  window.fetch = async function (input, init) {
    let url = typeof input === "string" ? input : input && input.url;
    let method =
      (init && init.method) || (typeof input !== "string" && input && input.method) || "GET";
    let reqBodyText = null;
    let reqHeaders = {};

    try {
      if (typeof input !== "string" && input && input.clone) {
        const reqClone = input.clone();
        reqHeaders = Object.fromEntries([...reqClone.headers.entries()]);
        try {
          reqBodyText = await reqClone.text();
        } catch (e) {
          /* some bodies are non-readable */
        }
      } else if (init) {
        reqHeaders = headersToObject(init.headers);
        if (init.body instanceof FormData) {
          reqBodyText = formDataToText(init.body);
        } else if (typeof init.body === "string") {
          reqBodyText = init.body;
        } else if (init.body && typeof init.body === "object") {
          try {
            reqBodyText = JSON.stringify(init.body);
          } catch (e) {
            reqBodyText = String(init.body);
          }
        }
      }
    } catch (e) {
      if (cfg.verbose) console.debug("[slack-capture] fetch request parse error:", e.message);
    }

    const started = Date.now();
    const res = await originalFetch(input, init);
    if (shouldCapture(url)) {
      let resText = null;
      let resJson = null;
      let resHeaders = {};
      try {
        const clone = res.clone();
        resHeaders = Object.fromEntries([...clone.headers.entries()]);
        const ct = (clone.headers.get("content-type") || "").toLowerCase();
        resText = await clone.text();
        if (ct.includes("application/json")) {
          resJson = safeJsonParse(resText);
        }
      } catch (e) {
        if (cfg.verbose) console.debug("[slack-capture] fetch response parse error:", e.message);
      }
      onRecord({
        type: "fetch",
        url,
        method,
        request: {
          headers: sanitizeHeaders(reqHeaders),
          bodyText: sanitizeBodyText(reqBodyText),
        },
        response: {
          status: res.status,
          headers: sanitizeHeaders(resHeaders),
          bodyText: resText,
          json: resJson,
        },
        timeMs: Date.now() - started,
        at: new Date().toISOString(),
      });
    }
    return res;
  };

  // ---------- XHR hook ----------
  const xhrProto = XMLHttpRequest.prototype;
  const origOpen = xhrProto.open;
  const origSetRequestHeader = xhrProto.setRequestHeader;
  const origSend = xhrProto.send;

  xhrProto.open = function (method, url /*, async, user, password */) {
    this.__sc_url = url;
    this.__sc_method = method;
    this.__sc_reqHeaders = {};
    return origOpen.apply(this, arguments);
  };

  xhrProto.setRequestHeader = function (header, value) {
    try {
      if (!this.__sc_reqHeaders) this.__sc_reqHeaders = {};
      this.__sc_reqHeaders[header] = value;
    } catch (e) {
      /* ignore */
    }
    return origSetRequestHeader.apply(this, arguments);
  };

  xhrProto.send = function (body) {
    const started = Date.now();
    this.__sc_body = body;
    this.addEventListener("readystatechange", () => {
      try {
        if (this.readyState === 4 && shouldCapture(this.__sc_url)) {
          const rawHeaders = this.getAllResponseHeaders();
          const resHeaders = parseRawHeaders(rawHeaders);
          const bodyText = this.responseText || null;
          const json = safeJsonParse(bodyText);
          onRecord({
            type: "xhr",
            url: this.__sc_url,
            method: this.__sc_method || "GET",
            request: {
              headers: sanitizeHeaders(this.__sc_reqHeaders || {}),
              bodyText: sanitizeBodyText(bodyToText(this.__sc_body)),
            },
            response: { status: this.status, headers: sanitizeHeaders(resHeaders), bodyText, json },
            timeMs: Date.now() - started,
            at: new Date().toISOString(),
          });
        }
      } catch (e) {
        if (cfg.verbose) console.debug("[slack-capture] xhr error:", e.message);
      }
    });
    return origSend.apply(this, arguments);
  };

  // ---------- Common helpers ----------
  function safeJsonParse(t) {
    try {
      return JSON.parse(t);
    } catch (_) {
      return null;
    }
  }

  function headersToObject(h) {
    if (!h) return {};
    try {
      if (Array.isArray(h)) return Object.fromEntries(h);
      if (typeof h === "object" && h.entries) return Object.fromEntries([...h.entries()]);
      return { ...h };
    } catch (e) {
      return {};
    }
  }

  function parseRawHeaders(raw) {
    const obj = {};
    if (!raw) return obj;
    raw
      .trim()
      .split(/\r?\n/)
      .forEach((line) => {
        const idx = line.indexOf(":");
        if (idx > 0) {
          const k = line.slice(0, idx).trim().toLowerCase();
          const v = line.slice(idx + 1).trim();
          obj[k] = v;
        }
      });
    return obj;
  }

  function formDataToText(fd) {
    const parts = [];
    try {
      for (const [k, v] of fd.entries()) {
        parts.push(`${k}=${typeof v === "string" ? v : "[file]"}`);
      }
    } catch (e) {
      // ignore
    }
    return parts.join("&");
  }

  function bodyToText(body) {
    if (body == null) return null;
    if (typeof FormData !== "undefined" && body instanceof FormData) return formDataToText(body);
    if (typeof body === "string") return body;
    if (typeof Blob !== "undefined" && body instanceof Blob)
      return `[Blob ${body.type || ""} ${body.size} bytes]`;
    if (typeof ArrayBuffer !== "undefined" && body instanceof ArrayBuffer)
      return `[ArrayBuffer ${body.byteLength} bytes]`;
    try {
      return JSON.stringify(body);
    } catch (e) {
      return String(body);
    }
  }

  // ---------- User capture helpers ----------
  function endpointFromUrl(url) {
    if (!url) return null;
    const m = /\/api\/([A-Za-z0-9._-]+)/.exec(url);
    return m ? m[1] : null;
  }

  function addOrMergeUser(u) {
    if (!u || !u.id) return;
    const prev = users.get(u.id) || {};
    const merged = { ...prev };
    for (const [k, v] of Object.entries(u)) {
      if (v == null || v === "") continue;
      if (merged[k] == null || merged[k] === "") merged[k] = v;
    }
    users.set(merged.id, merged);
  }

  function normFromPeopleItem(p) {
    const profile = p.profile || {};
    const fieldsRaw = profile.fields || {};
    const fields = {};
    try {
      for (const k of Object.keys(fieldsRaw)) {
        const v = fieldsRaw[k];
        fields[k] = (v && v.value) || null;
      }
    } catch (e) {}
    return {
      id: p.id,
      username: p.username || p.name,
      name: profile.display_name_normalized || profile.display_name || p.name,
      real_name: profile.real_name_normalized || profile.real_name,
      team: profile.team || p.team || (p.enterprise_user && p.enterprise_user.team_id),
      is_bot: !!p.is_bot,
      deleted: !!p.deleted,
      is_restricted: !!p.is_restricted,
      is_ultra_restricted: !!p.is_ultra_restricted,
      phone: p.phone || profile.phone || "",
      email: profile.email,
      first_name: profile.first_name,
      last_name: profile.last_name,
      image_original: profile.image_original,
      image_48: profile.image_48,
      image_72: profile.image_72,
      image_192: profile.image_192,
      image_512: profile.image_512,
      fields,
    };
  }

  function normFromUsersInfoPayload(payload) {
    const u = payload && payload.user;
    if (!u) return null;
    const profile = u.profile || {};
    return {
      id: u.id,
      username: u.name,
      name: profile.display_name_normalized || profile.display_name || u.name,
      real_name: profile.real_name_normalized || profile.real_name,
      team: u.team_id,
      is_bot: !!u.is_bot,
      deleted: !!u.deleted,
      is_restricted: !!u.is_restricted,
      is_ultra_restricted: !!u.is_ultra_restricted,
      phone: profile.phone || "",
      email: profile.email,
      first_name: profile.first_name,
      last_name: profile.last_name,
      image_original: profile.image_original,
      image_48: profile.image_48,
      image_72: profile.image_72,
      image_192: profile.image_192,
      image_512: profile.image_512,
      fields: profile.fields
        ? Object.fromEntries(Object.entries(profile.fields).map(([k, v]) => [k, v && v.value]))
        : undefined,
    };
  }

  function normFromUsersProfileGet(payload, entry) {
    const prof = payload && payload.profile;
    if (!prof) return null;
    const id = extractFormValue(entry, "user") || prof.user || prof.user_id;
    return {
      id,
      name: prof.display_name_normalized || prof.display_name,
      real_name: prof.real_name_normalized || prof.real_name,
      email: prof.email,
      phone: prof.phone || "",
      first_name: prof.first_name,
      last_name: prof.last_name,
      image_original: prof.image_original,
      image_48: prof.image_48,
      image_72: prof.image_72,
      image_192: prof.image_192,
      image_512: prof.image_512,
      fields: prof.fields
        ? Object.fromEntries(Object.entries(prof.fields).map(([k, v]) => [k, v && v.value]))
        : undefined,
    };
  }

  function extractFormValue(entry, key) {
    const body = entry && entry.request && entry.request.bodyText;
    if (!body || typeof body !== "string") return null;
    let m = new RegExp(`name="${key}"\r?\n\r?\n([^\r\n]+)`).exec(body);
    if (m) return m[1];
    m = new RegExp(`(?:^|[&;])${key}=([^&;\n\r]+)`).exec(body);
    return m ? m[1] : null;
  }

  function processEntryForUsers(entry) {
    const url = entry && entry.url;
    const payload = entry && entry.response && entry.response.json;
    if (!payload || typeof payload !== "object") return 0;
    const ep = endpointFromUrl(url);
    if (!ep) return 0;
    let added = 0;
    try {
      if (ep === "search.modules.people") {
        const items = payload.items || [];
        for (const p of items) {
          const u = normFromPeopleItem(p);
          if (u && u.id) {
            addOrMergeUser(u);
            added++;
          }
        }
      } else if (ep === "users.info") {
        const u = normFromUsersInfoPayload(payload);
        if (u && u.id) {
          addOrMergeUser(u);
          added++;
        }
      } else if (ep === "users.profile.get") {
        const u = normFromUsersProfileGet(payload, entry);
        if (u && u.id) {
          addOrMergeUser(u);
          added++;
        }
      } else if (ep === "users.list") {
        const members = payload.members || [];
        for (const m of members) {
          const u = normFromUsersInfoPayload({ user: m });
          if (u && u.id) {
            addOrMergeUser(u);
            added++;
          }
        }
      }
      if (added > 0 && cfg.verbose) {
        console.debug("[slack-capture] user capture:", ep, "added", added);
      }
    } catch (e) {
      if (cfg.verbose) {
        console.debug("[slack-capture] user capture error:", e.message);
      }
    }
    return added;
  }

  // ---------- Public API ----------
  const api = {
    logs,

    // Configuration
    getConfig() {
      return { ...cfg };
    },
    setConfig(options) {
      if (typeof options !== "object") throw new Error("setConfig expects an object");
      const validKeys = [
        "maxLogSize",
        "excludeHeaders",
        "maskTokens",
        "userCaptureEnabled",
        "verbose",
      ];
      for (const [k, v] of Object.entries(options)) {
        if (validKeys.includes(k)) {
          cfg[k] = v;
        }
      }
      console.log("slack capture: config updated", options);
    },

    // Filtering
    setFilter(regexes) {
      if (!Array.isArray(regexes)) throw new Error("setFilter expects an array of RegExp");
      cfg.include = regexes;
      console.log(
        "slack capture: filter set",
        regexes.map((r) => r.toString())
      );
    },

    // Log management
    clear() {
      logs.length = 0;
      console.log("slack capture: logs cleared");
    },
    exportNdjson() {
      return logs.map((l) => JSON.stringify(l)).join("\n");
    },
    download(filename = `slack-capture-${Date.now()}.ndjson`) {
      const text = this.exportNdjson();
      const blob = new Blob([text], { type: "application/x-ndjson" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      console.log("slack capture: downloaded", filename, `(${text.length} bytes)`);
    },

    // Lifecycle
    stop() {
      window.fetch = originalFetch;
      xhrProto.open = origOpen;
      xhrProto.setRequestHeader = origSetRequestHeader;
      xhrProto.send = origSend;
      console.log("slack capture: stopped");
    },

    // Status
    status() {
      return {
        count: logs.length,
        userCount: users.size,
        memoryEstimate: estimateMemoryUsage(),
        userCaptureEnabled: cfg.userCaptureEnabled,
      };
    },

    // User capture
    enableUserCapture() {
      cfg.userCaptureEnabled = true;
      // Process existing logs
      let added = 0;
      for (const entry of logs) {
        added += processEntryForUsers(entry);
      }
      console.log(
        `slack capture: user capture enabled (processed ${logs.length} entries, found ${added} users, unique=${users.size})`
      );
    },
    disableUserCapture() {
      cfg.userCaptureEnabled = false;
      console.log("slack capture: user capture disabled");
    },
    getUsers() {
      return users;
    },
    clearUsers() {
      users.clear();
      console.log("slack capture: users cleared");
    },
    exportUsersNdjson() {
      const arr = Array.from(users.values());
      return arr.map((u) => JSON.stringify(u)).join("\n");
    },
    downloadUsers(filename = `slack-users-${Date.now()}.ndjson`) {
      const text = this.exportUsersNdjson();
      const blob = new Blob([text], { type: "application/x-ndjson" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      console.log("slack capture: users downloaded", filename, `(${text.length} bytes)`);
    },
  };

  window._slackCapture = api;
  console.log("slack capture: installed. API at window._slackCapture");
  console.log("  - status(): check capture status");
  console.log("  - download(): save captured API calls");
  console.log("  - downloadUsers(): save collected user info");
  console.log("  - setConfig({ verbose: true }): enable debug logging");
})();
