/*
  Users Capture Hook (optional plugin for slack_capture.js)

  Purpose: Aggregate normalized user info from Slack Web API responses
  while browsing in the Slack web client. You can:
    - Post-process already captured logs: _slackUsersHook.processCaptured()
    - Enable a lightweight live hook:     _slackUsersHook.enableAuto()
    - Download users as NDJSON:           _slackUsersHook.download('users.ndjson')

  Safe by default: No network exfiltration; data stays in memory until download.

  Expected endpoints (best-effort):
    - /api/search.modules.people  (preferred: bulk user listing)
    - /api/users.info             (single user payload)
    - /api/users.profile.get      (profile details; user id taken from request)

  Usage:
    1) Load slack_capture.js first (recommended), then paste this file into Console.
    2) Run _slackUsersHook.processCaptured() to parse existing logs.
    3) Or call _slackUsersHook.enableAuto() to update on future requests.
    4) _slackUsersHook.download('users.ndjson') to save.
*/

(function () {
  if (window._slackUsersHook) {
    console.warn('users hook: already installed');
    return;
  }

  const users = new Map(); // id -> user object

  function endpointFromUrl(url) {
    if (!url) return null;
    const m = /\/api\/([A-Za-z0-9._-]+)/.exec(url);
    return m ? m[1] : null;
  }

  function addOrMerge(u) {
    if (!u || !u.id) return;
    const prev = users.get(u.id) || {};
    // Shallow merge: keep first non-empty values
    const merged = { ...prev };
    for (const [k, v] of Object.entries(u)) {
      if (v == null || v === '') continue;
      if (merged[k] == null || merged[k] === '') merged[k] = v;
      else merged[k] = merged[k];
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
      huddle_state: profile.huddle_state,
      huddle_state_expiration_ts: profile.huddle_state_expiration_ts,
      huddle_state_call_id: profile.huddle_state_call_id,
      guest_invited_by: profile.guest_invited_by,
      who_can_share_contact_card: profile.who_can_share_contact_card,
      image_original: profile.image_original,
      image_24: profile.image_24,
      image_32: profile.image_32,
      image_48: profile.image_48,
      image_72: profile.image_72,
      image_192: profile.image_192,
      image_512: profile.image_512,
      image_1024: profile.image_1024,
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
      huddle_state: profile.huddle_state,
      huddle_state_expiration_ts: profile.huddle_state_expiration_ts,
      huddle_state_call_id: profile.huddle_state_call_id,
      guest_invited_by: profile.guest_invited_by,
      who_can_share_contact_card: profile.who_can_share_contact_card,
      image_original: profile.image_original,
      image_24: profile.image_24,
      image_32: profile.image_32,
      image_48: profile.image_48,
      image_72: profile.image_72,
      image_192: profile.image_192,
      image_512: profile.image_512,
      image_1024: profile.image_1024,
      fields: profile.fields ? Object.fromEntries(Object.entries(profile.fields).map(([k,v]) => [k, v && v.value])) : undefined,
    };
  }

  function normFromUsersProfileGet(payload, entry) {
    const prof = payload && payload.profile;
    if (!prof) return null;
    const id = extractFormValue(entry, 'user') || prof.user || prof.user_id;
    return {
      id,
      name: prof.display_name_normalized || prof.display_name,
      real_name: prof.real_name_normalized || prof.real_name,
      email: prof.email,
      phone: prof.phone || "",
      first_name: prof.first_name,
      last_name: prof.last_name,
      image_original: prof.image_original,
      image_24: prof.image_24,
      image_32: prof.image_32,
      image_48: prof.image_48,
      image_72: prof.image_72,
      image_192: prof.image_192,
      image_512: prof.image_512,
      image_1024: prof.image_1024,
      fields: prof.fields ? Object.fromEntries(Object.entries(prof.fields).map(([k,v]) => [k, v && v.value])) : undefined,
    };
  }

  function extractFormValue(entry, key) {
    const body = entry && entry.request && entry.request.bodyText;
    if (!body || typeof body !== 'string') return null;
    let m = new RegExp(`name=\"${key}\"\r?\n\r?\n([^\r\n]+)`).exec(body);
    if (m) return m[1];
    m = new RegExp(`(?:^|[&;])${key}=([^&;\n\r]+)`).exec(body);
    return m ? m[1] : null;
  }

  function processEntry(entry) {
    const url = entry && entry.url;
    const payload = entry && entry.response && entry.response.json;
    if (!payload || typeof payload !== 'object') return 0;
    const ep = endpointFromUrl(url);
    if (!ep) return 0;
    let added = 0;
    try {
      if (ep === 'search.modules.people') {
        const items = payload.items || [];
        for (const p of items) {
          const u = normFromPeopleItem(p);
          if (u && u.id) {
            addOrMerge(u); added++;
          }
        }
      } else if (ep === 'users.info') {
        const u = normFromUsersInfoPayload(payload);
        if (u && u.id) { addOrMerge(u); added++; }
      } else if (ep === 'users.profile.get') {
        const u = normFromUsersProfileGet(payload, entry);
        if (u && u.id) { addOrMerge(u); added++; }
      }
    } catch (e) {
      // ignore
    }
    return added;
  }

  function processCaptured() {
    const logs = (window._slackCapture && window._slackCapture.logs) || [];
    let total = 0;
    for (const entry of logs) {
      total += processEntry(entry);
    }
    console.log(`users hook: processed ${logs.length} entries, added ${total} users (unique=${users.size})`);
    return { total_entries: logs.length, users_added: total, unique: users.size };
  }

  function exportNdjson() {
    const arr = Array.from(users.values());
    return arr.map((u) => JSON.stringify(u)).join('\n');
  }

  function download(filename = `slack-users-${Date.now()}.ndjson`) {
    const text = exportNdjson();
    const blob = new Blob([text], { type: 'application/x-ndjson' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    console.log('users hook: downloaded', filename, `(${text.length} bytes)`);
  }

  // Live hook: fetch + XHR (same要領 as slack_capture)
  const origFetch = window.fetch;
  const xhrProto = XMLHttpRequest && XMLHttpRequest.prototype;
  let liveEnabled = false;

  async function hookedFetch(input, init) {
    const res = await origFetch(input, init);
    try {
      const url = typeof input === 'string' ? input : input && input.url;
      const clone = res.clone();
      const ct = (clone.headers.get('content-type') || '').toLowerCase();
      const text = await clone.text();
      const json = ct.includes('application/json') ? JSON.parse(text) : null;
      const entry = { url, request: init || {}, response: { json } };
      const added = processEntry(entry);
      if (added) console.debug('[users_hook] fetch', url, 'added', added);
    } catch (e) { /* ignore */ }
    return res;
  }

  const origOpen = xhrProto && xhrProto.open;
  const origSetRequestHeader = xhrProto && xhrProto.setRequestHeader;
  const origSend = xhrProto && xhrProto.send;

  function enableAuto() {
    if (liveEnabled) return;
    // fetch
    window.fetch = hookedFetch;
    // XHR
    if (xhrProto && origOpen && origSend) {
      xhrProto.open = function (method, url) {
        this.__uh_url = url;
        this.__uh_method = method;
        this.__uh_reqHeaders = {};
        return origOpen.apply(this, arguments);
      };
      xhrProto.setRequestHeader = function (header, value) {
        try {
          if (!this.__uh_reqHeaders) this.__uh_reqHeaders = {};
          this.__uh_reqHeaders[header] = value;
        } catch (e) {}
        return origSetRequestHeader.apply(this, arguments);
      };
      xhrProto.send = function (body) {
        this.__uh_body = body;
        this.addEventListener('readystatechange', () => {
          try {
            if (this.readyState === 4) {
              const ct = (this.getResponseHeader && this.getResponseHeader('content-type') || '').toLowerCase();
              const text = this.responseText || '';
              const json = ct.includes('application/json') ? JSON.parse(text) : null;
              const entry = {
                url: this.__uh_url,
                request: { headers: this.__uh_reqHeaders || {}, bodyText: bodyToText(this.__uh_body) },
                response: { json },
              };
              const added = processEntry(entry);
              if (added) console.debug('[users_hook] xhr', this.__uh_url, 'added', added);
            }
          } catch (e) {}
        });
        return origSend.apply(this, arguments);
      };
    }
    liveEnabled = true;
    console.log('users hook: live hooks enabled (fetch + XHR)');
  }

  function disableAuto() {
    if (!liveEnabled) return;
    window.fetch = origFetch;
    if (xhrProto && origOpen && origSend) {
      xhrProto.open = origOpen;
      xhrProto.setRequestHeader = origSetRequestHeader;
      xhrProto.send = origSend;
    }
    liveEnabled = false;
    console.log('users hook: live hooks disabled');
  }

  function bodyToText(body) {
    if (body == null) return null;
    if (typeof FormData !== 'undefined' && body instanceof FormData) {
      const parts = [];
      for (const [k, v] of body.entries()) {
        parts.push(`${k}=${typeof v === 'string' ? v : '[file]'}`);
      }
      return parts.join('&');
    }
    if (typeof body === 'string') return body;
    if (typeof Blob !== 'undefined' && body instanceof Blob) return `[Blob ${body.type || ''} ${body.size} bytes]`;
    if (typeof ArrayBuffer !== 'undefined' && body instanceof ArrayBuffer) return `[ArrayBuffer ${body.byteLength} bytes]`;
    try { return JSON.stringify(body); } catch (e) { return String(body); }
  }

  window._slackUsersHook = {
    get size() { return users.size; },
    users,
    processEntry,
    processCaptured,
    exportNdjson,
    download,
    clear() { users.clear(); },
    enableAuto,
    disableAuto,
  };
  // 同じ要領: インストール時に自動フックを有効化
  try { enableAuto(); } catch (e) {}
  console.log('users hook: installed + enabled. API at window._slackUsersHook');
})();
