from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from cumbot import config


@dataclass(slots=True)
class ContextMessage:
    user_id: int | None
    username: str
    display_name: str
    text: str


class RecentContextCollector:
    def __init__(self, max_messages: int = config.RECENT_CONTEXT_MAX_MESSAGES) -> None:
        self._messages: dict[int, deque[ContextMessage]] = defaultdict(
            lambda: deque(maxlen=max_messages)
        )

    def add_message(
        self,
        chat_id: int,
        user_id: int | None,
        username: str,
        display_name: str,
        text: str,
    ) -> None:
        cleaned = " ".join(text.split()).strip()
        if not cleaned:
            return
        self._messages[chat_id].append(
            ContextMessage(
                user_id=user_id,
                username=username,
                display_name=display_name,
                text=cleaned,
            )
        )

    def get_recent(self, chat_id: int, n: int = config.RECENT_CONTEXT_WINDOW) -> list[dict]:
        recent = list(self._messages[chat_id])[-n:]
        return [
            {
                "user_id": item.user_id,
                "username": item.username,
                "display_name": item.display_name,
                "speaker": item.username or item.display_name,
                "text": item.text,
            }
            for item in recent
        ]


collector = RecentContextCollector()
