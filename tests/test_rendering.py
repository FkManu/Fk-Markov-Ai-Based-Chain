from telegram.constants import ParseMode

from cumbot.markov.rendering import (
    build_mention_candidates,
    materialize_placeholder_labels,
    polish_generated_text,
    resolve_placeholder_mentions,
)


def test_resolve_placeholder_mentions_uses_username_when_available() -> None:
    text, parse_mode = resolve_placeholder_mentions(
        "ciao @user come va",
        [{"user_id": 1, "username": "mario", "display_name": "Mario"}],
    )
    assert text == "ciao @mario come va"
    assert parse_mode == ParseMode.HTML


def test_materialize_placeholder_labels_falls_back_to_display_name() -> None:
    output = materialize_placeholder_labels(
        "oh @user rispondi",
        [{"user_id": 1, "username": "", "display_name": "Giovanni"}],
    )
    assert output == "oh Giovanni rispondi"


def test_build_mention_candidates_keeps_trigger_user_first() -> None:
    candidates = build_mention_candidates(
        trigger_user={"user_id": 10, "username": "trigger", "display_name": "Trigger"},
        recent_context=[
            {"user_id": 11, "username": "other", "display_name": "Other"},
            {"user_id": 10, "username": "trigger", "display_name": "Trigger"},
        ],
    )
    assert candidates[0]["username"] == "trigger"
    assert len(candidates) == 2


def test_polish_generated_text_softens_mid_sentence_restarts() -> None:
    output = polish_generated_text(
        "Non me ne vado ora Pari rimango fino alle ginocchia questi Tu mi capisci sempre..."
    )
    assert output == "Non me ne vado ora Pari rimango fino alle ginocchia questi, tu mi capisci sempre..."


def test_polish_generated_text_collapses_duplicate_words_and_adds_punctuation() -> None:
    output = polish_generated_text("Forse ti gratti sempre e e all'apparenza sono uguali")
    assert output == "Forse ti gratti sempre e all'apparenza sono uguali."
