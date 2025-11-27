import sqlite3
from pathlib import Path
from typing import Iterable, Tuple, Dict, Any

from .models import User, Channel, Message, Edge


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT,
    name TEXT,
    real_name TEXT
);

CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    name TEXT,
    is_private INTEGER,
    is_im INTEGER,
    is_mpim INTEGER
);

CREATE TABLE IF NOT EXISTS messages (
    ts TEXT PRIMARY KEY,
    channel_id TEXT,
    user TEXT,
    text TEXT,
    thread_ts TEXT,
    reply_count INTEGER
);

CREATE TABLE IF NOT EXISTS reactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_ts TEXT,
    name TEXT,
    user TEXT
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,
    target TEXT,
    type TEXT,
    weight INTEGER,
    channel_id TEXT,
    ts TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel_id);
CREATE INDEX IF NOT EXISTS idx_edges_source_target ON edges(source, target);
"""


class Storage:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL;")

    def init(self):
        self.conn.executescript(SCHEMA)
        self._ensure_migrations()
        self.conn.commit()

    def upsert_user(self, u: User):
        self.conn.execute(
            "INSERT OR REPLACE INTO users(id, username, name, real_name) VALUES(?,?,?,?)",
            (u.id, u.username, u.name, u.real_name),
        )

    def upsert_channel(self, c: Channel):
        self.conn.execute(
            "INSERT OR REPLACE INTO channels(id, name, is_private, is_im, is_mpim) VALUES(?,?,?,?,?)",
            (c.id, c.name, int(c.is_private), int(c.is_im), int(getattr(c, "is_mpim", False))),
        )

    def insert_message(self, m: Message):
        self.conn.execute(
            "INSERT OR REPLACE INTO messages(ts, channel_id, user, text, thread_ts, reply_count) VALUES(?,?,?,?,?,?)",
            (m.ts, m.channel_id, m.user, m.text, m.thread_ts, m.reply_count),
        )

    def insert_reaction(self, ts: str, name: str, user: str):
        self.conn.execute(
            "INSERT INTO reactions(message_ts, name, user) VALUES(?,?,?)",
            (ts, name, user),
        )

    def insert_edge(self, e: Edge):
        edge_type = e.type.value if hasattr(e.type, "value") else str(e.type)
        self.conn.execute(
            "INSERT INTO edges(source, target, type, weight, channel_id, ts) VALUES(?,?,?,?,?,?)",
            (e.source, e.target, edge_type, e.weight, e.channel_id, e.ts),
        )

    def commit(self):
        self.conn.commit()

    def iter_messages(self, channel_id: str | None = None) -> Iterable[Dict[str, Any]]:
        cur = self.conn.cursor()
        if channel_id:
            cur.execute(
                "SELECT ts, channel_id, user, text, thread_ts, reply_count FROM messages WHERE channel_id=? ORDER BY ts",
                (channel_id,),
            )
        else:
            cur.execute(
                "SELECT ts, channel_id, user, text, thread_ts, reply_count FROM messages ORDER BY ts"
            )
        for row in cur.fetchall():
            yield {
                "ts": row[0],
                "channel_id": row[1],
                "user": row[2],
                "text": row[3],
                "thread_ts": row[4],
                "reply_count": row[5],
            }

    def reactions_for_message(self, ts: str) -> Iterable[Tuple[str, str]]:
        cur = self.conn.cursor()
        cur.execute("SELECT name, user FROM reactions WHERE message_ts=?", (ts,))
        return cur.fetchall()

    # Utility & reporting
    def count_users(self) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        return int(cur.fetchone()[0])

    def count_channels(self, include_im_mpim: bool = True) -> int:
        cur = self.conn.cursor()
        if include_im_mpim:
            cur.execute("SELECT COUNT(*) FROM channels")
        else:
            cur.execute(
                "SELECT COUNT(*) FROM channels WHERE COALESCE(is_im,0)=0 AND COALESCE(is_mpim,0)=0"
            )
        return int(cur.fetchone()[0])

    def count_messages(self) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM messages")
        return int(cur.fetchone()[0])

    def count_reactions(self) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM reactions")
        return int(cur.fetchone()[0])

    def list_channels_to_process(self) -> Iterable[Tuple[str, str]]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, COALESCE(name, id) FROM channels WHERE COALESCE(is_im,0)=0 AND COALESCE(is_mpim,0)=0 ORDER BY name"
        )
        return cur.fetchall()

    def users_map(self) -> Dict[str, Dict[str, Any]]:
        """Return a mapping of user id -> {username, name, real_name, label}.

        The `label` prefers display name, then real name, then username, and
        finally falls back to the id. Use for node labeling in exports.
        """
        cur = self.conn.cursor()
        cur.execute("SELECT id, username, name, real_name FROM users")
        out: Dict[str, Dict[str, Any]] = {}
        for row in cur.fetchall():
            uid, username, name, real_name = row
            label = name or real_name or username or uid
            out[uid] = {
                "username": username,
                "name": name,
                "real_name": real_name,
                "label": label,
            }
        return out

    def _ensure_migrations(self) -> None:
        # users: add username column if missing
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(users)")
        cols = {row[1] for row in cur.fetchall()}
        if "username" not in cols:
            self.conn.execute("ALTER TABLE users ADD COLUMN username TEXT")

        # channels: add is_mpim if missing
        cur.execute("PRAGMA table_info(channels)")
        cols = {row[1] for row in cur.fetchall()}
        if "is_mpim" not in cols:
            self.conn.execute("ALTER TABLE channels ADD COLUMN is_mpim INTEGER")
