from cumbot.handlers.admin_handler import (
    _format_temperature,
    _make_groqtemp_chat_keyboard,
    _parse_groqtemp_action,
    _parse_temperature_arg,
)


def test_parse_temperature_accepts_comma_decimal() -> None:
    assert _parse_temperature_arg("0,85") == 0.85


def test_parse_temperature_rejects_out_of_range() -> None:
    assert _parse_temperature_arg("2.5") is None
    assert _parse_temperature_arg("-0.1") is None


def test_format_temperature_trims_trailing_zeroes() -> None:
    assert _format_temperature(0.7) == "0.7"
    assert _format_temperature(1.0) == "1"


def test_parse_groqtemp_action_supports_status_reset_and_numeric() -> None:
    assert _parse_groqtemp_action(None) == ("status", None)
    assert _parse_groqtemp_action("status") == ("status", None)
    assert _parse_groqtemp_action("0,9") == ("set", 0.9)
    parsed = _parse_groqtemp_action("reset")
    assert parsed is not None
    assert parsed[0] == "set"


def test_make_groqtemp_chat_keyboard_contains_chat_buttons() -> None:
    class DummyChat:
        def __init__(self, chat_id: int, title: str, chat_type: str) -> None:
            self.chat_id = chat_id
            self.title = title
            self.chat_type = chat_type

    keyboard = _make_groqtemp_chat_keyboard(
        [DummyChat(-1001, "Gruppo Test", "group"), DummyChat(-1002, "Altro", "supergroup")]
    )
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "Gruppo Test (group)" in labels
    assert "Altro (supergroup)" in labels
    assert "groqtemp:select:-1001" in callbacks
