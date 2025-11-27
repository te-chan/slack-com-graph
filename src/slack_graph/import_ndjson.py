import json
import re
from pathlib import Path
from typing import Iterable, Dict, Any, Tuple

from .storage import Storage
from .models import Channel, Message, User
from .ingest import _is_human_message


API_PATH_RE = re.compile(r"/api/([A-Za-z0-9\._-]+)")


def _endpoint_from_url(url: str) -> str | None:
    if not url:
        return None
    m = API_PATH_RE.search(url)
    return m.group(1) if m else None


def _iter_ndjson(path: str) -> Iterable[Dict[str, Any]]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                yield json.loads(s)
            except json.JSONDecodeError:
                continue


def _coerce_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.lower() in {"1", "true", "yes"}
    return False


def _import_search_modules_channels(payload: Dict[str, Any], store: Storage) -> int:
    items = payload.get("items") or []
    count = 0
    for ch in items:
        c = Channel(
            id=ch.get("id"),
            name=ch.get("name"),
            is_private=_coerce_bool(ch.get("is_private")),
            is_im=_coerce_bool(ch.get("is_im")),
            is_mpim=_coerce_bool(ch.get("is_mpim")),
        )
        if c.id:
            store.upsert_channel(c)
            count += 1
    return count


def _import_search_modules_people(payload: Dict[str, Any], store: Storage) -> int:
    items = payload.get("items") or []
    count = 0
    for p in items:
        profile = p.get("profile") or {}
        display_name = profile.get("display_name_normalized") or profile.get("display_name")
        real_name = profile.get("real_name_normalized") or profile.get("real_name")
        u = User(
            id=p.get("id"),
            username=p.get("username") or p.get("name"),
            name=display_name or p.get("name"),
            real_name=real_name,
        )
        if u.id:
            store.upsert_user(u)
            count += 1
    return count


def _import_search_modules_messages(payload: Dict[str, Any], store: Storage) -> Tuple[int, int]:
    items = payload.get("items") or []
    msg_count = 0
    ch_count = 0
    for it in items:
        ch = it.get("channel") or {}
        c = Channel(
            id=ch.get("id"),
            name=ch.get("name"),
            is_private=_coerce_bool(ch.get("is_private")),
            is_im=_coerce_bool(ch.get("is_im")),
            is_mpim=_coerce_bool(ch.get("is_mpim")),
        )
        if c.id:
            store.upsert_channel(c)
            ch_count += 1
        for m in (it.get("messages") or []):
            if not _is_human_message(m):
                continue
            msg = Message(
                ts=m.get("ts"),
                channel_id=c.id or (ch.get("id") if isinstance(ch, dict) else None),
                user=m.get("user") or m.get("parent_user_id"),
                text=m.get("text") or "",
                thread_ts=m.get("thread_ts") or None,
                reply_count=m.get("reply_count"),
                reactions=m.get("reactions"),
            )
            if msg.ts and msg.channel_id:
                store.insert_message(msg)
                # reactions (rare in search)
                for react in (m.get("reactions") or []):
                    for u in (react.get("users") or []):
                        store.insert_reaction(msg.ts, react.get("name"), u)
                msg_count += 1
    return msg_count, ch_count


def _import_conversations_history(payload: Dict[str, Any], channel_id: str, store: Storage) -> Tuple[int, int]:
    msg_count = 0
    reaction_count = 0
    for m in payload.get("messages", []) or []:
        if not _is_human_message(m):
            continue
        msg = Message(
            ts=m.get("ts"),
            channel_id=channel_id,
            user=m.get("user"),
            text=m.get("text") or "",
            thread_ts=m.get("thread_ts"),
            reply_count=m.get("reply_count"),
            reactions=m.get("reactions"),
        )
        if msg.ts and msg.channel_id:
            store.insert_message(msg)
            msg_count += 1
            for react in (m.get("reactions") or []):
                for u in (react.get("users") or []):
                    store.insert_reaction(msg.ts, react.get("name"), u)
                    reaction_count += 1
    return msg_count, reaction_count


def _import_conversations_replies(payload: Dict[str, Any], channel_id: str, parent_ts: str, store: Storage) -> Tuple[int, int]:
    msg_count = 0
    reaction_count = 0
    for m in payload.get("messages", []) or []:
        if not _is_human_message(m):
            continue
        msg = Message(
            ts=m.get("ts"),
            channel_id=channel_id,
            user=m.get("user") or m.get("parent_user_id"),
            text=m.get("text") or "",
            thread_ts=m.get("thread_ts") or parent_ts,
            reply_count=m.get("reply_count"),
            reactions=m.get("reactions"),
        )
        if msg.ts and msg.channel_id:
            store.insert_message(msg)
            msg_count += 1
            for react in (m.get("reactions") or []):
                for u in (react.get("users") or []):
                    store.insert_reaction(msg.ts, react.get("name"), u)
                    reaction_count += 1
    return msg_count, reaction_count


def import_ndjson(paths: list[str], store: Storage) -> Dict[str, int]:
    """Parse NDJSON capture logs and store into DB.

    Supports endpoints:
      - search.modules.channels -> channels
      - search.modules.people   -> users
      - search.modules.messages -> channels, messages (limited reactions)
      - conversations.history   -> messages, reactions
      - conversations.replies   -> messages(replies), reactions
    """
    counts = {
        "users": 0,
        "channels": 0,
        "messages": 0,
        "reactions": 0,
        "files": 0,
        "lines": 0,
        "skipped": 0,
    }

    for path in paths:
        for entry in _iter_ndjson(path):
            counts["lines"] += 1
            url = (entry.get("url") or "")
            endpoint = _endpoint_from_url(url) or ""
            payload = ((entry.get("response") or {}).get("json"))
            if not endpoint or not isinstance(payload, dict):
                counts["skipped"] += 1
                continue

            if endpoint == "search.modules.channels":
                counts["channels"] += _import_search_modules_channels(payload, store)
            elif endpoint == "search.modules.people":
                counts["users"] += _import_search_modules_people(payload, store)
            elif endpoint == "search.modules.messages":
                m, c = _import_search_modules_messages(payload, store)
                counts["messages"] += m
                counts["channels"] += c
            elif endpoint == "conversations.history":
                # derive channel from request body if available
                channel_id = _extract_form_value(entry, "channel")
                m, r = _import_conversations_history(payload, channel_id, store)
                counts["messages"] += m
                counts["reactions"] += r
            elif endpoint == "conversations.replies":
                channel_id = _extract_form_value(entry, "channel")
                parent_ts = _extract_form_value(entry, "ts")
                m, r = _import_conversations_replies(payload, channel_id, parent_ts, store)
                counts["messages"] += m
                counts["reactions"] += r
            else:
                counts["skipped"] += 1
        counts["files"] += 1

    store.commit()
    return counts


def _extract_form_value(entry: Dict[str, Any], key: str) -> str | None:
    # Try to find k=v inside captured request.bodyText (can be multipart encoded as lines)
    body = ((entry.get("request") or {}).get("bodyText")) or ""
    if not isinstance(body, str) or not body:
        return None
    # Quick scan for 'name="key"\r\n\r\nVALUE' or 'key=VALUE'
    # 1) multipart form-data pattern
    m = re.search(rf"name=\"{re.escape(key)}\"\r?\n\r?\n([^\r\n]+)", body)
    if m:
        return m.group(1)
    # 2) urlencoded-ish pattern
    m = re.search(rf"(?:^|[&;]){re.escape(key)}=([^&;\n\r]+)", body)
    if m:
        return m.group(1)
    return None

