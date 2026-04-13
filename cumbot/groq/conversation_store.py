from __future__ import annotations

import time
from dataclasses import dataclass, field

_TTL_SECONDS = 7200  # 2 ore — dopodiché la conversazione è "persa"


@dataclass
class _ConversationEntry:
    messages: list[dict]
    last_updated: float = field(default_factory=time.time)


class AskConversationStore:
    """Store in-memory per le conversazioni multi-turn di /ask.

    Chiave: (chat_id, bot_message_id) — bot_message_id è il message_id
    del messaggio del bot a cui l'utente può rispondere per continuare.
    """

    def __init__(self, ttl: int = _TTL_SECONDS) -> None:
        self._store: dict[tuple[int, int], _ConversationEntry] = {}
        self._ttl = ttl

    def set(self, chat_id: int, bot_message_id: int, messages: list[dict]) -> None:
        self._cleanup()
        self._store[(chat_id, bot_message_id)] = _ConversationEntry(messages=list(messages))

    def get(self, chat_id: int, bot_message_id: int) -> list[dict] | None:
        """Ritorna la storia della conversazione o None se scaduta/non trovata."""
        entry = self._store.get((chat_id, bot_message_id))
        if entry is None:
            return None
        if time.time() - entry.last_updated > self._ttl:
            del self._store[(chat_id, bot_message_id)]
            return None
        return list(entry.messages)

    def _cleanup(self) -> None:
        """Rimuove le entry scadute. Chiamato ad ogni set() per evitare memory leak."""
        now = time.time()
        expired = [k for k, v in self._store.items() if now - v.last_updated > self._ttl]
        for k in expired:
            del self._store[k]


ask_store = AskConversationStore()
