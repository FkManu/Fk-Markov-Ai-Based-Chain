import asyncio

from cumbot.db import state


def test_autopost_cooldown_triggers_and_resets(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "state.sqlite3"
    monkeypatch.setattr(state.config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(state.config, "AUTOPOST_MIN_MESSAGES", 3)
    monkeypatch.setattr(state.config, "AUTOPOST_MAX_MESSAGES", 3)

    async def scenario() -> None:
        await state.init_db()
        await state.register_chat(-100123, "group", "Test Group")

        first = await state.advance_autopost_cooldown(-100123)
        second = await state.advance_autopost_cooldown(-100123)
        third = await state.advance_autopost_cooldown(-100123)
        settings = await state.get_chat_settings(-100123)

        assert first == (False, 1, 3)
        assert second == (False, 2, 3)
        assert third == (True, 3, 3)
        assert settings is not None
        assert settings.messages_since_bot == 0
        assert settings.next_autopost_after == 3

    asyncio.run(scenario())


def test_reaction_counts_are_saved_on_generated_messages(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "state.sqlite3"
    monkeypatch.setattr(state.config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(state.config, "AUTOPOST_MIN_MESSAGES", 3)
    monkeypatch.setattr(state.config, "AUTOPOST_MAX_MESSAGES", 3)

    async def scenario() -> None:
        await state.init_db()
        await state.register_chat(-100123, "group", "Test Group")
        await state.log_generated_message(
            chat_id=-100123,
            trigger_type="cooldown",
            groq_enabled=False,
            used_groq=False,
            output_text="ciao gruppo",
            response_message_id=42,
        )

        updated = await state.add_reaction_delta(
            chat_id=-100123,
            response_message_id=42,
            delta=2,
            reaction_breakdown={"🔥": 1, "😂": 1},
            reacted_at="2026-04-09T20:00:00+00:00",
        )
        assert updated is True

        overwritten = await state.overwrite_reaction_count(
            chat_id=-100123,
            response_message_id=42,
            reaction_count=5,
            reaction_breakdown={"🔥": 3, "😂": 2},
            reacted_at="2026-04-09T20:05:00+00:00",
        )
        assert overwritten is True

        records = await state.get_top_reacted_messages(chat_id=-100123, limit=1)
        assert len(records) == 1
        assert records[0].reaction_count == 5
        assert records[0].reaction_breakdown == {"🔥": 3, "😂": 2}

    asyncio.run(scenario())


def test_gif_corpus_counts_and_random_pick(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "state.sqlite3"
    monkeypatch.setattr(state.config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(state.config, "GIF_CORPUS_MAX", 2)

    async def scenario() -> None:
        await state.init_db()
        await state.log_gif(-100123, "gif_a", "file_a")
        await state.log_gif(-100123, "gif_b", "file_b")
        await state.log_gif(-100123, "gif_c", "file_c")

        count = await state.count_recent_gifs(-100123, 15)
        picked = await state.get_random_gif(-100123)

        assert count == 2
        assert picked in {"file_b", "file_c"}

    asyncio.run(scenario())


def test_groq_temperature_is_persisted_per_chat(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "state.sqlite3"
    monkeypatch.setattr(state.config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(state.config, "GROQ_REFINER_TEMPERATURE", 0.76)

    async def scenario() -> None:
        await state.init_db()
        await state.register_chat(-100123, "group", "Test Group")
        settings = await state.get_chat_settings(-100123)
        assert settings is not None
        assert settings.groq_temperature == 0.76

        await state.set_groq_temperature(-100123, 1.15)
        updated = await state.get_chat_settings(-100123)
        assert updated is not None
        assert updated.groq_temperature == 1.15

    asyncio.run(scenario())


def test_replace_and_append_live_corpus_are_chat_scoped(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "state.sqlite3"
    monkeypatch.setattr(state.config, "DATABASE_PATH", db_path)

    async def scenario() -> None:
        await state.init_db()
        await state.replace_live_corpus(
            -100123,
            [
                {"user_id": 1, "username": "alice", "text": "ciao", "created_at": "2026-04-11T10:00:00+00:00"},
                {"user_id": 2, "username": "bob", "text": "mondo", "created_at": "2026-04-11T10:01:00+00:00"},
            ],
        )
        await state.append_live_corpus(
            -100123,
            [
                {"user_id": 3, "username": "carol", "text": "extra", "created_at": "2026-04-11T10:02:00+00:00"},
            ],
        )
        await state.replace_live_corpus(
            -100999,
            [
                {"user_id": 9, "username": "other", "text": "altra chat", "created_at": "2026-04-11T10:03:00+00:00"},
            ],
        )

        rows = await state.get_all_live_messages_for_training(chat_id=-100123)
        assert [row["text"] for row in rows] == ["ciao", "mondo", "extra"]

        other_rows = await state.get_all_live_messages_for_training(chat_id=-100999)
        assert [row["text"] for row in other_rows] == ["altra chat"]

    asyncio.run(scenario())


def test_training_corpus_dedups_and_exports_for_training(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "state.sqlite3"
    monkeypatch.setattr(state.config, "DATABASE_PATH", db_path)

    async def scenario() -> None:
        await state.init_db()
        inserted = await state.insert_training_corpus_rows(
            -100123,
            [
                {
                    "source_kind": "export",
                    "source_key": "export:1",
                    "user_id": 1,
                    "username": "alice",
                    "text": "ciao mondo",
                    "created_at": "2026-04-11T10:00:00+00:00",
                },
                {
                    "source_kind": "export",
                    "source_key": "export:1",
                    "user_id": 1,
                    "username": "alice",
                    "text": "duplicato ignorato",
                    "created_at": "2026-04-11T10:00:00+00:00",
                },
                {
                    "source_kind": "live",
                    "source_key": "live:9",
                    "user_id": 2,
                    "username": "bob",
                    "text": "seconda riga utile",
                    "created_at": "2026-04-11T10:01:00+00:00",
                },
            ],
        )
        assert inserted == 2

        rows = await state.get_training_corpus_rows(-100123)
        assert [row.source_key for row in rows] == ["export:1", "live:9"]
        assert await state.count_training_corpus_rows(-100123) == 2
        assert await state.count_training_corpus_rows(-100123, source_kind="export") == 1

        training_rows = await state.get_training_corpus_for_training(-100123)
        assert [row["text"] for row in training_rows] == ["ciao mondo", "seconda riga utile"]
        assert training_rows[0]["from_id"] == "user1"

    asyncio.run(scenario())


def test_replace_training_corpus_source_only_replaces_target_source(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "state.sqlite3"
    monkeypatch.setattr(state.config, "DATABASE_PATH", db_path)

    async def scenario() -> None:
        await state.init_db()
        await state.insert_training_corpus_rows(
            -100123,
            [
                {
                    "source_kind": "export",
                    "source_key": "export:1",
                    "user_id": 1,
                    "username": "alice",
                    "text": "storico uno",
                    "created_at": "2026-04-11T10:00:00+00:00",
                },
                {
                    "source_kind": "live",
                    "source_key": "live:1",
                    "user_id": 2,
                    "username": "bob",
                    "text": "live uno",
                    "created_at": "2026-04-11T10:01:00+00:00",
                },
            ],
        )

        replaced = await state.replace_training_corpus_source(
            -100123,
            "export",
            [
                {
                    "source_key": "export:2",
                    "user_id": 3,
                    "username": "carol",
                    "text": "storico nuovo",
                    "created_at": "2026-04-11T10:02:00+00:00",
                }
            ],
        )
        assert replaced == 1

        export_rows = await state.get_training_corpus_rows(-100123, source_kind="export")
        live_rows = await state.get_training_corpus_rows(-100123, source_kind="live")
        assert [row.source_key for row in export_rows] == ["export:2"]
        assert [row.source_key for row in live_rows] == ["live:1"]

    asyncio.run(scenario())


def test_chat_training_state_tracks_partial_updates_and_live_high_watermark(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "state.sqlite3"
    monkeypatch.setattr(state.config, "DATABASE_PATH", db_path)

    async def scenario() -> None:
        await state.init_db()
        await state.log_live_message(-100123, 1, "alice", "ciao mondo")
        await state.log_live_message(-100123, 2, "bob", "seconda riga")

        latest_live_id = await state.get_latest_live_corpus_id(-100123)
        assert latest_live_id == 2

        first = await state.update_chat_training_state(
            -100123,
            last_retrain_at="2026-04-11T12:00:00+00:00",
            last_live_corpus_id=latest_live_id,
            last_export_path="data/export.json",
            training_corpus_size=25,
            models_path="models/chats/-100123",
        )
        assert first.last_live_corpus_id == 2
        assert first.training_corpus_size == 25

        second = await state.update_chat_training_state(
            -100123,
            training_corpus_size=30,
        )
        assert second.last_retrain_at == "2026-04-11T12:00:00+00:00"
        assert second.last_export_path == "data/export.json"
        assert second.training_corpus_size == 30
        assert second.models_path == "models/chats/-100123"

    asyncio.run(scenario())


def test_live_corpus_rows_for_training_corpus_are_incremental(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "state.sqlite3"
    monkeypatch.setattr(state.config, "DATABASE_PATH", db_path)

    async def scenario() -> None:
        await state.init_db()
        await state.log_live_message(-100123, 1, "alice", "prima riga")
        await state.log_live_message(-100123, 2, "bob", "seconda riga")
        await state.log_live_message(-100123, 3, "carol", "terza riga")

        all_rows = await state.get_live_corpus_rows_for_training_corpus(-100123)
        incremental_rows = await state.get_live_corpus_rows_for_training_corpus(
            -100123,
            after_id=2,
        )

        assert [row["source_key"] for row in all_rows] == ["live:1", "live:2", "live:3"]
        assert [row["text"] for row in incremental_rows] == ["terza riga"]

    asyncio.run(scenario())
