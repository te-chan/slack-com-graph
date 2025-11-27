import re
from typing import Dict

import networkx as nx

from .storage import Storage


MENTION_RE = re.compile(r"<@([UW][A-Z0-9]+)>")


def build_graph(store: Storage, weights: Dict[str, int] | None = None) -> nx.DiGraph:
    """Build a directed graph of interactions: mention, reply, reaction."""
    weights = {"mention": 2, "reply": 3, "reaction": 1} | (weights or {})
    G = nx.DiGraph()

    # Pre-compute thread roots: thread_ts -> root user
    thread_roots: Dict[str, str] = {}
    for msg in store.iter_messages():
        if msg["thread_ts"] and msg["thread_ts"] == msg["ts"]:
            if msg["user"]:
                thread_roots[msg["thread_ts"]] = msg["user"]

    for m in store.iter_messages():
        user = m.get("user")
        text = m.get("text") or ""

        # Mentions: user -> mentioned user
        for target in MENTION_RE.findall(text):
            if user and target and user != target:
                w = weights["mention"]
                current = G.get_edge_data(user, target) or {}
                G.add_edge(user, target, weight=(current.get("weight", 0) + w), kind="mention")

        # Reactions: reactor -> author
        for name, reactor in store.reactions_for_message(m["ts"]):
            if reactor and user and reactor != user:
                w = weights["reaction"]
                current = G.get_edge_data(reactor, user) or {}
                G.add_edge(reactor, user, weight=(current.get("weight", 0) + w), kind="reaction")

        # Replies: replier -> thread root author
        if m["thread_ts"] and m["thread_ts"] != m["ts"]:
            root_user = thread_roots.get(m["thread_ts"])
            if root_user and user and root_user != user:
                w = weights["reply"]
                current = G.get_edge_data(user, root_user) or {}
                G.add_edge(user, root_user, weight=(current.get("weight", 0) + w), kind="reply")

    # Enrich nodes with user attributes for export/visualization.
    # label: prefers display name -> real name -> username -> id
    users = store.users_map()
    node_attrs: Dict[str, Dict[str, str]] = {}
    for n in G.nodes:
        info = users.get(n, {})
        # Always set label
        d: Dict[str, str] = {"label": info.get("label", n) if info else n}
        # Only include non-empty string attributes to satisfy GraphML type limits
        for key in ("username", "name", "real_name"):
            val = info.get(key) if info else None
            if isinstance(val, str) and val:
                d[key] = val
        node_attrs[n] = d
    nx.set_node_attributes(G, node_attrs)

    return G
