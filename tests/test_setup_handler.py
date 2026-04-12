from cumbot.handlers.setup_handler import _make_cooldown_keyboard, _settings_text


class DummySettings:
    title = "Chat Test"
    chat_id = -1001
    active_persona_ids = ["1", "2"]
    groq_enabled = True
    groq_temperature = 0.76
    cooldown_min_messages = 20
    cooldown_max_messages = 30


def test_settings_text_contains_core_state() -> None:
    text = _settings_text(DummySettings())
    assert "Chat Test" in text
    assert "Groq: on" in text
    assert "0.76" in text
    assert "1, 2" in text
    assert "20-30" in text


def test_cooldown_keyboard_contains_presets() -> None:
    keyboard = _make_cooldown_keyboard(-1001)
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "20-30 msg" in labels
    assert "Indietro" in labels
