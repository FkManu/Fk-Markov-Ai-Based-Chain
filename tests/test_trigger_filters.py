from types import SimpleNamespace

from cumbot.announcement_store import announcement_store
from cumbot.handlers.cooldown_handler import _is_direct_bot_trigger
from cumbot.handlers.mention_handler import _is_triggered


def _build_update(*, text: str, chat_id: int, reply_message_id: int | None = None, bot_id: int = 99):
    reply = None
    if reply_message_id is not None:
        reply = SimpleNamespace(
            message_id=reply_message_id,
            from_user=SimpleNamespace(id=bot_id),
        )
    message = SimpleNamespace(
        text=text,
        caption=None,
        reply_to_message=reply,
    )
    return SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=chat_id),
    )


def test_reply_to_announcement_does_not_trigger_mention_handler() -> None:
    chat_id = -100100
    message_id = 501
    announcement_store.mark(chat_id, message_id)
    update = _build_update(text="ok", chat_id=chat_id, reply_message_id=message_id)

    assert _is_triggered(update, bot_username="CumBot", bot_id=99) is False


def test_reply_to_announcement_does_not_trigger_cooldown_direct_trigger() -> None:
    chat_id = -100101
    message_id = 502
    announcement_store.mark(chat_id, message_id)
    update = _build_update(text="ci sta", chat_id=chat_id, reply_message_id=message_id)

    assert _is_direct_bot_trigger(update, bot_username="CumBot", bot_id=99) is False


def test_mention_still_triggers_even_if_replying_to_announcement() -> None:
    chat_id = -100102
    message_id = 503
    announcement_store.mark(chat_id, message_id)
    update = _build_update(text="@CumBot rispondi", chat_id=chat_id, reply_message_id=message_id)

    assert _is_triggered(update, bot_username="CumBot", bot_id=99) is True
