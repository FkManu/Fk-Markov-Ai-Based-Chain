from pathlib import Path

import pytest

from cumbot.markov.trainer import (
    build_training_corpus_import_rows,
    build_live_corpus_import_rows,
    classify_skip_reason,
    extract_sender_id,
    flatten_export_text,
    normalize_training_text,
    normalize_sender_id,
    resolve_export_path,
    should_keep_training_text,
    train_all,
)


def test_flatten_export_text_supports_plain_segments() -> None:
    payload = [
        {"type": "plain", "text": "ciao "},
        {"type": "bold", "text": "ignored"},
        "mondo",
        {"type": "plain", "text": "!"},
    ]
    assert flatten_export_text(payload) == "ciao ignoredmondo!"


def test_normalize_sender_id_extracts_numeric_suffix() -> None:
    assert normalize_sender_id("user123456") == "123456"
    assert normalize_sender_id(42) == "42"


def test_extract_sender_id_prefers_known_fields() -> None:
    assert extract_sender_id({"from_id": "user123"}) == "123"
    assert extract_sender_id({"actor_id": "user999"}) == "999"


def test_should_keep_training_text_filters_short_and_url_only_messages() -> None:
    assert not should_keep_training_text("ciao")
    assert not should_keep_training_text("https://example.com")
    assert should_keep_training_text("questa frase passa il filtro")


def test_normalize_training_text_replaces_noisy_fragments() -> None:
    normalized = normalize_training_text(
        "ciao @mario guarda https://example.com e questo 123456",
        mode="normalized",
    )
    assert "@user" in normalized
    assert "link" in normalized
    assert "numero" in normalized


def test_classify_skip_reason_filters_bot_command() -> None:
    message = {"type": "message", "text": "/shipping@SHIPPERINGbot"}
    raw = "/shipping@SHIPPERINGbot"
    normalized = normalize_training_text(raw)
    assert classify_skip_reason(message, raw, normalized) == "bot_command"


def test_resolve_export_path_returns_direct_path_when_present(tmp_path: Path) -> None:
    export_path = tmp_path / "export.json"
    export_path.write_text("{}", encoding="utf-8")
    assert resolve_export_path(export_path) == export_path


def test_resolve_export_path_raises_when_missing_and_no_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("cumbot.config.DATA_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        resolve_export_path(tmp_path / "missing.json")


def test_build_live_corpus_import_rows_extracts_text_and_timestamp(tmp_path: Path) -> None:
    export_path = tmp_path / "export.json"
    export_path.write_text(
        """
        {
          "messages": [
            {
              "type": "message",
              "from_id": "user123",
              "from": "alice",
              "date": "2026-04-11T12:30:00",
              "text": [{"type": "plain", "text": "ciao "}, "mondo"]
            },
            {
              "type": "message",
              "from_id": "user456",
              "from": "bob",
              "date_unixtime": "1712838600",
              "text": "secondo messaggio"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    rows = build_live_corpus_import_rows(export_path)

    assert len(rows) == 2
    assert rows[0]["user_id"] == 123
    assert rows[0]["username"] == "alice"
    assert rows[0]["text"] == "ciao mondo"
    assert rows[0]["created_at"].startswith("2026-04-11T12:30:00")
    assert rows[1]["user_id"] == 456
    assert rows[1]["text"] == "secondo messaggio"


def test_build_training_corpus_import_rows_uses_message_id_and_hash_fallback(
    tmp_path: Path,
) -> None:
    export_path = tmp_path / "export.json"
    export_path.write_text(
        """
        {
          "messages": [
            {
              "type": "message",
              "id": 77,
              "from_id": "user123",
              "from": "alice",
              "date": "2026-04-11T12:30:00",
              "text": "ciao mondo"
            },
            {
              "type": "message",
              "from_id": "user456",
              "from": "bob",
              "date": "2026-04-11T12:31:00",
              "text": "senza id telegram"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    rows = build_training_corpus_import_rows(export_path)

    assert len(rows) == 2
    assert rows[0]["source_kind"] == "export"
    assert rows[0]["source_key"] == "export:77"
    assert rows[1]["source_key"].startswith("exporthash:")
    assert rows[1]["text"] == "senza id telegram"


def test_train_all_writes_models_to_chat_namespace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    export_path = tmp_path / "export.json"
    messages = []
    for index in range(120):
        messages.append(
            {
                "type": "message",
                "id": index + 1,
                "from_id": "user123",
                "from": "alice",
                "text": f"questa frase di test numero {index} passa il filtro",
            }
        )
    export_path.write_text(json_dumps({"messages": messages}), encoding="utf-8")

    monkeypatch.setattr("cumbot.config.MODELS_DIR", tmp_path / "models")

    stats = train_all(export_path=export_path, chat_id=-1001)

    assert stats["chat_id"] == -1001
    assert (tmp_path / "models" / "chats" / "-1001" / "state_1" / "global.json").exists()
    assert (tmp_path / "models" / "chats" / "-1001" / "metadata.json").exists()


def test_train_all_can_use_base_messages_without_reloading_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("cumbot.config.MODELS_DIR", tmp_path / "models")

    base_messages = [
        {
            "type": "message",
            "from_id": "user123",
            "from": "alice",
            "text": f"questa frase di base numero {index} passa bene il filtro"
        }
        for index in range(120)
    ]
    extra_messages = [
        {
            "type": "message",
            "from_id": "user456",
            "from": "bob",
            "text": "questo live si aggiunge al retrain"
        }
    ]

    stats = train_all(
        export_path=tmp_path / "missing-export.json",
        extra_messages=extra_messages,
        chat_id=-1002,
        base_messages=base_messages,
        source_label="training_corpus:-1002",
    )

    assert stats["chat_id"] == -1002
    assert stats["base_messages_used"] == 120
    assert stats["live_messages_added"] == 1
    assert (tmp_path / "models" / "chats" / "-1002" / "state_1" / "global.json").exists()


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)
