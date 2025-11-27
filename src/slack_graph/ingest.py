import time
from typing import Dict, Any

from .storage import Storage
from .models import Channel, Message, User


def ingest_channels(client: Any, store: Storage) -> int:
    """Fetch channels via client and upsert into storage."""
    processed = 0
    for page in client.list_channels():
        # Webクライアントのレスポンス形式に応じて柔軟に対応
        channels = page.get("items") or page.get("channels") or []
        for ch in channels:
            c = Channel(
                id=ch.get("id"),
                name=ch.get("name"),
                is_private=bool(ch.get("is_private")),
                is_im=bool(ch.get("is_im")),
                is_mpim=bool(ch.get("is_mpim")),
            )
            store.upsert_channel(c)
            processed += 1
    store.commit()
    return processed

def ingest_users(client: Any, store: Storage) -> int:
    """Fetch users via client and upsert into storage."""
    # docs/slack: items配列, profile.display_name(_normalized), profile.real_name(_normalized)
    processed = 0
    for page in getattr(client, "list_people")():
        people = page.get("items") or []
        for p in people:
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
                processed += 1
    store.commit()
    return processed


def ingest_messages_for_channel(
    client: Any, store: Storage, channel_id: str, oldest_days: int = 30
) -> dict:
    latest = time.time()
    oldest = latest - oldest_days * 86400
    msg_count = 0
    reply_count = 0
    reaction_count = 0
    for page in client.conversation_history(channel_id, oldest, latest, limit=200):
        messages = page.get("messages", [])
        for m in messages:
            # Human-only: skip bots and deletions
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
            store.insert_message(msg)
            msg_count += 1
            # Reactions
            for react in (m.get("reactions") or []):
                for user in (react.get("users") or []):
                    store.insert_reaction(msg.ts, react.get("name"), user)
                    reaction_count += 1
            # Thread replies: fetch if reply_count > 0
            try:
                reply_count = int(m.get("reply_count") or 0)
            except Exception:
                reply_count = 0
            if reply_count > 0 and msg.ts:
                saw_parent = False
                for rpage in client.conversation_replies(channel_id, msg.ts, limit=200):
                    for rm in rpage.get("messages", []):
                        if not _is_human_message(rm):
                            if rm.get("ts") == msg.ts:
                                saw_parent = True
                            continue
                        if rm.get("ts") == msg.ts:
                            saw_parent = True
                        rmsg = Message(
                            ts=rm.get("ts"),
                            channel_id=channel_id,
                            user=rm.get("user") or rm.get("parent_user_id"),
                            text=rm.get("text") or "",
                            thread_ts=rm.get("thread_ts") or msg.ts,
                            reply_count=rm.get("reply_count"),
                            reactions=rm.get("reactions"),
                        )
                        store.insert_message(rmsg)
                        reply_count += 1
                        for react in (rm.get("reactions") or []):
                            for user in (react.get("users") or []):
                                store.insert_reaction(rmsg.ts, react.get("name"), user)
                                reaction_count += 1
                # 親が返ってこないケースの補完
                if not saw_parent:
                    for hpage in client.conversation_history(channel_id, oldest=float(msg.ts), latest=float(msg.ts), limit=1):
                        for pm in hpage.get("messages", []):
                            if not _is_human_message(pm):
                                continue
                            pmsg = Message(
                                ts=pm.get("ts"),
                                channel_id=channel_id,
                                user=pm.get("user") or pm.get("parent_user_id"),
                                text=pm.get("text") or "",
                                thread_ts=pm.get("thread_ts") or pm.get("ts"),
                                reply_count=pm.get("reply_count"),
                                reactions=pm.get("reactions"),
                            )
                            store.insert_message(pmsg)
    store.commit()
    return {"messages": msg_count, "replies": reply_count, "reactions": reaction_count}


def _is_human_message(m: Dict[str, Any]) -> bool:
    """Return True for human-authored messages; skip bots/deleted/system subtypes."""
    if m.get("bot_id"):
        return False
    subtype = m.get("subtype")
    if subtype:
        # common bot/system/deleted subtypes to exclude
        if subtype in {
            "bot_message",
            "message_deleted",
            "channel_join",
            "channel_leave",
            "channel_topic",
            "channel_purpose",
            "file_share",
        }:
            return False
    # deleted_ts or hidden flags
    if m.get("deleted_ts") or m.get("hidden"):
        return False
    # must have a user id
    return bool(m.get("user"))
