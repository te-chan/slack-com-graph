from dataclasses import dataclass
import os
from typing import Optional, Dict, Any

from dotenv import load_dotenv


@dataclass
class Config:
    base_url: str
    token: str
    cookie_d: Optional[str]
    db_path: str = "data/slack_graph.db"
    since_days: int = 30
    include_dms: bool = True


def load_config(overrides: Optional[Dict[str, Any]] = None) -> Config:
    """Load configuration from .env and optional overrides."""
    load_dotenv()
    overrides = overrides or {}
    base_url = overrides.get("base_url") or os.getenv("SLACK_WORKSPACE_BASE_URL", "")
    token = overrides.get("token") or os.getenv("SLACK_TOKEN", "")
    cookie_d = overrides.get("cookie_d") or os.getenv("SLACK_COOKIE_D")
    db_path = os.getenv("DB_PATH", "data/slack_graph.db")
    since_days_str = os.getenv("SINCE_DAYS")
    since_days = overrides.get("since_days") or (int(since_days_str) if since_days_str else 30)
    include_dms = True
    return Config(
        base_url=base_url,
        token=token,
        cookie_d=cookie_d,
        db_path=db_path,
        since_days=since_days,
        include_dms=include_dms,
    )
