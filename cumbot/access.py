from __future__ import annotations

from cumbot import config


def _equivalent_chat_ids(chat_id: int) -> set[int]:
    values = {chat_id}
    as_text = str(chat_id)
    if as_text.startswith("-100") and len(as_text) > 4:
        values.add(int(as_text[4:]))
    elif chat_id > 0:
        values.add(int(f"-100{chat_id}"))
    return values


def is_chat_allowed(chat_id: int | None, user_id: int | None) -> bool:
    if chat_id is None:
        return False
    if not config.ALLOWED_CHAT_IDS:
        return True
    if _equivalent_chat_ids(chat_id) & set(config.ALLOWED_CHAT_IDS):
        return True
    if user_id is not None and user_id in config.ADMIN_USER_IDS:
        return True
    return False
