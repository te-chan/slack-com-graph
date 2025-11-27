/*
  Slack Web API Capture (console-injectable)

  Paste this entire file into the browser console on a Slack web client page
  (e.g. https://app.slack.com or https://<workspace>.slack.com) to intercept
  fetch/XHR calls to Slack's /api/* endpoints and record both request and
  response payloads locally. No network exfiltration; data stays in memory
  until you download it as an NDJSON file.

  Public API exposed as window._slackCapture:
    - logs: in-memory array of captured entries
    - setFilter([/regex/, ...]): include-only URL filters (optional)
    - clear(): clear in-memory logs
    - exportNdjson(): return NDJSON string
    - download(filename?): trigger NDJSON download
    - stop(): restore original fetch/XHR and stop capturing
    - status(): { count }

  Note: This captures sensitive data (e.g., tokens in multipart/form-data).
  Handle outputs securely and in compliance with your organization's policy.
*/

(function () {
  if (window._slackCapture) {
    console.warn("slack capture: already installed");
    return;
  }

  const cfg = {
    include: null, // array of regexes; if set, only matching URLs are captured
    apiHostnamePattern: /\.slack\.com\/api\//,
  };

  const logs = [];
  const onRecord = (entry) => {
    try {
      logs.push(entry);
      const summary = (entry.response && entry.response.json && entry.response.json.pagination)
        ? `status=${entry.response.status} items=${(entry.response.json.items||[]).length} page=${entry.response.json.pagination.page}`
        : `status=${entry.response ? entry.response.status : "?"}`;
      console.debug("[slack-capture]", entry.method, entry.url, summary);
    } catch (e) {
      console.debug("[slack-capture] recorded", entry.url);
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
    let method = (init && init.method) || (typeof input !== "string" && input && input.method) || "GET";
    let reqBodyText = null;
    let reqHeaders = {};

    try {
      if (typeof input !== "string" && input && input.clone) {
        const reqClone = input.clone();
        // Best-effort: attempting to read request headers/body
        reqHeaders = Object.fromEntries([...reqClone.headers.entries()]);
        try {
          reqBodyText = await reqClone.text();
        } catch (e) { /* some bodies are non-readable */ }
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
      // ignore
    }

    const started = Date.now();
    const res = await originalFetch(input, init);
    if (shouldCapture(url)) {
      let clone = null;
      let resText = null;
      let resJson = null;
      let resHeaders = {};
      try {
        clone = res.clone();
        resHeaders = Object.fromEntries([...clone.headers.entries()]);
        const ct = (clone.headers.get("content-type") || "").toLowerCase();
        resText = await clone.text();
        if (ct.includes("application/json")) {
          resJson = safeJsonParse(resText);
        }
      } catch (e) {
        // ignore parse errors
      }
      onRecord({
        type: "fetch",
        url,
        method,
        request: { headers: reqHeaders, bodyText: reqBodyText },
        response: { status: res.status, headers: resHeaders, bodyText: resText, json: resJson },
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
    } catch (e) { /* ignore */ }
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
            request: { headers: this.__sc_reqHeaders || {}, bodyText: bodyToText(this.__sc_body) },
            response: { status: this.status, headers: resHeaders, bodyText, json },
            timeMs: Date.now() - started,
            at: new Date().toISOString(),
          });
        }
      } catch (e) { /* ignore */ }
    });
    return origSend.apply(this, arguments);
  };

  // ---------- helpers ----------
  function safeJsonParse(t) {
    try { return JSON.parse(t); } catch (_) { return null; }
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
    raw.trim().split(/\r?\n/).forEach((line) => {
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
    if (typeof Blob !== "undefined" && body instanceof Blob) return `[Blob ${body.type || ""} ${body.size} bytes]`;
    if (typeof ArrayBuffer !== "undefined" && body instanceof ArrayBuffer) return `[ArrayBuffer ${body.byteLength} bytes]`;
    try { return JSON.stringify(body); } catch (e) { return String(body); }
  }

  // ---------- public API ----------
  const api = {
    logs,
    setFilter(regexes) {
      if (!Array.isArray(regexes)) throw new Error("setFilter expects an array of RegExp");
      cfg.include = regexes;
      console.log("slack capture: filter set", regexes.map((r) => r.toString()));
    },
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
    stop() {
      window.fetch = originalFetch;
      // restore XHR prototypes (rebind originals)
      xhrProto.open = origOpen;
      xhrProto.setRequestHeader = origSetRequestHeader;
      xhrProto.send = origSend;
      console.log("slack capture: stopped");
    },
    status() {
      return { count: logs.length };
    },
  };

  window._slackCapture = api;
  console.log("slack capture: installed. API at window._slackCapture");
})();

