"""Per-user conversation history for multi-turn context.

Stored in-memory (resets on server restart — same trade-off as agent.py's
_conversation_history). A Redis or Firestore backend can replace the dict
later without changing callers.
"""
from __future__ import annotations

from collections import deque
from threading import Lock

_MAX_TURNS = 8          # keep last 8 exchanges per user
_REPLY_PREVIEW = 80     # chars of Dragun reply stored per turn

_history: dict[str, deque[dict]] = {}
_lock = Lock()


def append_turn(user_id: str, user_msg: str, assistant_reply: str) -> None:
    """Record a completed exchange. Call after every successful /api/chat."""
    with _lock:
        if user_id not in _history:
            _history[user_id] = deque(maxlen=_MAX_TURNS)
        _history[user_id].append({
            "user": user_msg.strip(),
            "assistant": assistant_reply.strip()[:_REPLY_PREVIEW],
        })


def get_user_turns(user_id: str, *, max_turns: int = 3) -> str:
    """Return recent user messages only — used in extraction prompt for pronoun resolution."""
    with _lock:
        turns = list(_history.get(user_id, []))[-max_turns:]
    if not turns:
        return ""
    return "\n".join(f'- "{t["user"]}"' for t in turns)


def get_full_history(user_id: str, *, max_turns: int = 3) -> str:
    """Return full recent exchanges — used in advisor prompt for tonal continuity."""
    with _lock:
        turns = list(_history.get(user_id, []))[-max_turns:]
    if not turns:
        return ""
    lines: list[str] = []
    for t in turns:
        lines.append(f'User: {t["user"]}')
        lines.append(f'Dragun: {t["assistant"]}')
    return "\n".join(lines)


def clear_history(user_id: str) -> None:
    """Wipe history on logout / account delete."""
    with _lock:
        _history.pop(user_id, None)
