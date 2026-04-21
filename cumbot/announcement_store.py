from __future__ import annotations

import time
from dataclasses import dataclass, field


_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 giorni


@dataclass
class _AnnouncementEntry:
    created_at: float = field(default_factory=time.time)


class AnnouncementMessageStore:
    """Store in-memory dei message_id inviati come annunci programmati."""

    def __init__(self, ttl: int = _TTL_SECONDS) -> None:
        self._ttl = ttl
        self._store: dict[tuple[int, int], _AnnouncementEntry] = {}

    def mark(self, chat_id: int, message_id: int) -> None:
        self._cleanup()
        self._store[(chat_id, message_id)] = _AnnouncementEntry()

    def is_announcement(self, chat_id: int, message_id: int) -> bool:
        entry = self._store.get((chat_id, message_id))
        if entry is None:
            return False
        if time.time() - entry.created_at > self._ttl:
            del self._store[(chat_id, message_id)]
            return False
        return True

    def _cleanup(self) -> None:
        now = time.time()
        expired = [
            key for key, value in self._store.items()
            if now - value.created_at > self._ttl
        ]
        for key in expired:
            del self._store[key]


announcement_store = AnnouncementMessageStore()
