import json
from pathlib import Path
from typing import Iterable, Dict, Any

from .storage import Storage
from .models import User


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


def import_users_ndjson(paths: list[str], store: Storage) -> Dict[str, int]:
    """Import normalized users NDJSON (from users_capture.js).

    Each line is expected to contain at least: id, username/name, real_name.
    Extra fields are ignored by current schema.
    """
    counts = {"files": 0, "lines": 0, "users": 0, "skipped": 0}
    for path in paths:
        for row in _iter_ndjson(path):
            counts["lines"] += 1
            if not isinstance(row, dict):
                counts["skipped"] += 1
                continue
            uid = row.get("id")
            if not uid:
                counts["skipped"] += 1
                continue
            u = User(
                id=uid,
                username=row.get("username"),
                name=row.get("name") or row.get("real_name"),
                real_name=row.get("real_name"),
            )
            store.upsert_user(u)
            counts["users"] += 1
        counts["files"] += 1
    store.commit()
    return counts

