import asyncio
from types import SimpleNamespace

from cumbot.db import state
from cumbot.jobs import birthdays


class _DummySentMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class _DummyBot:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return _DummySentMessage(len(self.calls))


def test_send_due_birthdays_handles_feb29_fallback_and_dedups(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "state.sqlite3"
    monkeypatch.setattr(state.config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(birthdays.config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(
        birthdays,
        "_local_now",
        lambda: birthdays.datetime(2027, 2, 28, 0, 0, tzinfo=birthdays._tz()),
    )
    monkeypatch.setattr(birthdays.random, "choice", lambda values: values[0])

    async def scenario() -> None:
        await state.init_db()
        await state.upsert_birthday(
            chat_id=-1001,
            user_id=10,
            username="alice",
            display_name="Alice",
            day=28,
            month=2,
            birth_year=1990,
        )
        await state.upsert_birthday(
            chat_id=-1001,
            user_id=11,
            username="bob",
            display_name="Bob",
            day=29,
            month=2,
            birth_year=1992,
        )

        bot = _DummyBot()
        context = SimpleNamespace(bot=bot)

        await birthdays.send_due_birthdays(context)
        await birthdays.send_due_birthdays(context)

        assert len(bot.calls) == 2
        assert "@alice" in bot.calls[0]["text"]
        assert "@bob" in bot.calls[1]["text"]
        assert "29/02" in bot.calls[1]["text"]

    asyncio.run(scenario())
