"""Request identity and latest-wins guard for streamed chat turns.

The in-memory registry provides an immediate, process-local cancellation signal.
The database remains the cross-process source of truth when the caller performs
the final conditional assistant insert.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import threading
import time
import uuid


_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9_.:-]{8,80}")


def normalize_chat_request_id(value: object) -> str:
    """Return a log/DB-safe request id, generating one for absent or invalid input."""
    candidate = str(value or "").strip()
    if _REQUEST_ID_RE.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


@dataclass(frozen=True)
class _LatestRequest:
    request_id: str
    registered_at: float


class LatestChatRequestRegistry:
    """Thread-safe, bounded latest request registry keyed by conversation."""

    def __init__(self, *, max_entries: int = 10_000, ttl_seconds: float = 86_400.0):
        self._max_entries = max(100, int(max_entries))
        self._ttl_seconds = max(60.0, float(ttl_seconds))
        self._entries: dict[str, _LatestRequest] = {}
        self._lock = threading.Lock()

    def register(self, conversation_id: str, request_id: str) -> None:
        conversation_key = str(conversation_id or "").strip()
        request_key = str(request_id or "").strip()
        if not conversation_key or not request_key:
            return

        now = time.monotonic()
        with self._lock:
            if len(self._entries) >= self._max_entries:
                cutoff = now - self._ttl_seconds
                self._entries = {
                    key: entry
                    for key, entry in self._entries.items()
                    if entry.registered_at >= cutoff
                }
                if len(self._entries) >= self._max_entries:
                    oldest = min(
                        self._entries,
                        key=lambda key: self._entries[key].registered_at,
                    )
                    self._entries.pop(oldest, None)
            self._entries[conversation_key] = _LatestRequest(request_key, now)

    def is_latest(self, conversation_id: str, request_id: str) -> bool:
        conversation_key = str(conversation_id or "").strip()
        request_key = str(request_id or "").strip()
        if not conversation_key or not request_key:
            return True
        with self._lock:
            latest = self._entries.get(conversation_key)
        return latest is None or latest.request_id == request_key
