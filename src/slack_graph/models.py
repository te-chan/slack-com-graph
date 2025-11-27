from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict


class EdgeType(str, Enum):
    MENTION = "mention"
    REPLY = "reply"
    REACTION = "reaction"


@dataclass
class User:
    id: str
    username: Optional[str] = None
    name: Optional[str] = None
    real_name: Optional[str] = None


@dataclass
class Channel:
    id: str
    name: Optional[str] = None
    is_private: bool = False
    is_im: bool = False
    is_mpim: bool = False


@dataclass
class Message:
    ts: str
    channel_id: str
    user: Optional[str]
    text: str
    thread_ts: Optional[str] = None
    reply_count: Optional[int] = None
    reactions: Optional[List[Dict]] = None


@dataclass
class Edge:
    source: str
    target: str
    type: EdgeType
    weight: int = 1
    channel_id: Optional[str] = None
    ts: Optional[str] = None
