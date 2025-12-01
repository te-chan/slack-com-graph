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

-- Clustering analysis tables
CREATE TABLE IF NOT EXISTS reaction_contexts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reaction_name TEXT NOT NULL,
    message_ts TEXT NOT NULL,
    message_text TEXT,
    reactor_user TEXT,
    message_author TEXT,
    channel_id TEXT,
    UNIQUE(reaction_name, message_ts, reactor_user)
);

CREATE TABLE IF NOT EXISTS embeddings_cache (
    message_ts TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    embedding BLOB NOT NULL,
    embedding_dim INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS clustering_results (
    run_id TEXT PRIMARY KEY,
    algorithm TEXT NOT NULL,
    params_json TEXT,
    text_weight REAL,
    behavior_weight REAL,
    n_clusters INTEGER,
    silhouette_score REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cluster_assignments (
    run_id TEXT NOT NULL,
    reaction_name TEXT NOT NULL,
    cluster_id INTEGER NOT NULL,
    confidence REAL,
    PRIMARY KEY (run_id, reaction_name)
);

CREATE INDEX IF NOT EXISTS idx_reaction_contexts_name ON reaction_contexts(reaction_name);
CREATE INDEX IF NOT EXISTS idx_embeddings_cache_ts ON embeddings_cache(message_ts);
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

    # ===== Clustering analysis methods =====

    def build_reaction_contexts(self) -> int:
        """Build reaction_contexts table by joining reactions with messages.

        Returns the number of contexts created.
        """
        # Clear existing data
        self.conn.execute("DELETE FROM reaction_contexts")

        # Join reactions -> messages and insert
        self.conn.execute(
            """
            INSERT OR IGNORE INTO reaction_contexts
                (reaction_name, message_ts, message_text, reactor_user, message_author, channel_id)
            SELECT
                r.name,
                r.message_ts,
                m.text,
                r.user,
                m.user,
                m.channel_id
            FROM reactions r
            JOIN messages m ON r.message_ts = m.ts
            WHERE m.text IS NOT NULL AND m.text != ''
            """
        )
        self.conn.commit()

        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM reaction_contexts")
        return int(cur.fetchone()[0])

    def get_reaction_contexts(self) -> Iterable[Dict[str, Any]]:
        """Get all reaction contexts."""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT reaction_name, message_ts, message_text, reactor_user, message_author, channel_id
            FROM reaction_contexts
            ORDER BY reaction_name
            """
        )
        for row in cur.fetchall():
            yield {
                "reaction_name": row[0],
                "message_ts": row[1],
                "message_text": row[2],
                "reactor_user": row[3],
                "message_author": row[4],
                "channel_id": row[5],
            }

    def get_unique_reactions(self) -> list[str]:
        """Get list of unique reaction names."""
        cur = self.conn.cursor()
        cur.execute("SELECT DISTINCT reaction_name FROM reaction_contexts ORDER BY reaction_name")
        return [row[0] for row in cur.fetchall()]

    def get_messages_for_reaction(self, reaction_name: str) -> list[str]:
        """Get all message texts for a specific reaction."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT DISTINCT message_text FROM reaction_contexts WHERE reaction_name = ?",
            (reaction_name,),
        )
        return [row[0] for row in cur.fetchall() if row[0]]

    def get_user_reaction_counts(self) -> Dict[str, Dict[str, int]]:
        """Get user-reaction count matrix as nested dict.

        Returns: {user_id: {reaction_name: count}}
        """
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT reactor_user, reaction_name, COUNT(*) as cnt
            FROM reaction_contexts
            GROUP BY reactor_user, reaction_name
            """
        )
        result: Dict[str, Dict[str, int]] = {}
        for user, reaction, count in cur.fetchall():
            if user not in result:
                result[user] = {}
            result[user][reaction] = count
        return result

    def get_reaction_cooccurrence(self) -> Dict[str, Dict[str, int]]:
        """Get reaction co-occurrence matrix (reactions appearing on same messages).

        Returns: {reaction1: {reaction2: count}}
        """
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT rc1.reaction_name, rc2.reaction_name, COUNT(DISTINCT rc1.message_ts) as cnt
            FROM reaction_contexts rc1
            JOIN reaction_contexts rc2 ON rc1.message_ts = rc2.message_ts
            WHERE rc1.reaction_name < rc2.reaction_name
            GROUP BY rc1.reaction_name, rc2.reaction_name
            """
        )
        result: Dict[str, Dict[str, int]] = {}
        for r1, r2, count in cur.fetchall():
            if r1 not in result:
                result[r1] = {}
            if r2 not in result:
                result[r2] = {}
            result[r1][r2] = count
            result[r2][r1] = count
        return result

    def save_embedding(self, message_ts: str, model_name: str, embedding: bytes, dim: int):
        """Cache an embedding for a message."""
        self.conn.execute(
            "INSERT OR REPLACE INTO embeddings_cache(message_ts, model_name, embedding, embedding_dim) VALUES(?,?,?,?)",
            (message_ts, model_name, embedding, dim),
        )

    def get_embedding(self, message_ts: str, model_name: str) -> bytes | None:
        """Get cached embedding for a message."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT embedding FROM embeddings_cache WHERE message_ts = ? AND model_name = ?",
            (message_ts, model_name),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def save_clustering_result(
        self,
        run_id: str,
        algorithm: str,
        params_json: str,
        text_weight: float,
        behavior_weight: float,
        n_clusters: int,
        silhouette_score: float | None,
        assignments: list[tuple[str, int, float]],
    ):
        """Save clustering results.

        Args:
            run_id: Unique identifier for this clustering run
            algorithm: Algorithm name (e.g., 'hdbscan')
            params_json: JSON string of algorithm parameters
            text_weight: Weight used for text features
            behavior_weight: Weight used for behavior features
            n_clusters: Number of clusters found
            silhouette_score: Silhouette score (or None)
            assignments: List of (reaction_name, cluster_id, confidence) tuples
        """
        self.conn.execute(
            """
            INSERT OR REPLACE INTO clustering_results
                (run_id, algorithm, params_json, text_weight, behavior_weight, n_clusters, silhouette_score)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, algorithm, params_json, text_weight, behavior_weight, n_clusters, silhouette_score),
        )

        # Clear old assignments for this run
        self.conn.execute("DELETE FROM cluster_assignments WHERE run_id = ?", (run_id,))

        # Insert new assignments
        self.conn.executemany(
            "INSERT INTO cluster_assignments(run_id, reaction_name, cluster_id, confidence) VALUES(?,?,?,?)",
            [(run_id, name, cluster_id, conf) for name, cluster_id, conf in assignments],
        )
        self.conn.commit()

    def get_latest_clustering_result(self) -> Dict[str, Any] | None:
        """Get the most recent clustering result."""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT run_id, algorithm, params_json, text_weight, behavior_weight, n_clusters, silhouette_score, created_at
            FROM clustering_results
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            return None

        run_id = row[0]
        cur.execute(
            "SELECT reaction_name, cluster_id, confidence FROM cluster_assignments WHERE run_id = ?",
            (run_id,),
        )
        assignments = [{"reaction": r[0], "cluster": r[1], "confidence": r[2]} for r in cur.fetchall()]

        return {
            "run_id": run_id,
            "algorithm": row[1],
            "params_json": row[2],
            "text_weight": row[3],
            "behavior_weight": row[4],
            "n_clusters": row[5],
            "silhouette_score": row[6],
            "created_at": row[7],
            "assignments": assignments,
        }

    def count_reaction_contexts(self) -> int:
        """Count rows in reaction_contexts table."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM reaction_contexts")
        return int(cur.fetchone()[0])
