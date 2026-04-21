from datetime import date

from cumbot.handlers import cumpleanno_handler


def test_parse_birthday_date_accepts_supported_formats(monkeypatch) -> None:
    monkeypatch.setattr(cumpleanno_handler, "_local_today", lambda: date(2026, 4, 21))

    assert cumpleanno_handler._parse_birthday_date("14/05/1994") == (14, 5, 1994)
    assert cumpleanno_handler._parse_birthday_date("14-05-1994") == (14, 5, 1994)
    assert cumpleanno_handler._parse_birthday_date("4/05/1994") == (4, 5, 1994)
    assert cumpleanno_handler._parse_birthday_date("4-5-94") == (4, 5, 1994)
    assert cumpleanno_handler._parse_birthday_date("14/05/05") == (14, 5, 2005)
    assert cumpleanno_handler._parse_birthday_date("14-05-94") == (14, 5, 1994)


def test_parse_birthday_date_rejects_invalid_or_future_dates(monkeypatch) -> None:
    monkeypatch.setattr(cumpleanno_handler, "_local_today", lambda: date(2026, 4, 21))

    assert cumpleanno_handler._parse_birthday_date("31/02/1994") is None
    assert cumpleanno_handler._parse_birthday_date("14/05/2027") is None
    assert cumpleanno_handler._parse_birthday_date("boh") is None


def test_usage_text_mentions_supported_commands() -> None:
    text = cumpleanno_handler._usage_text()
    assert "/cumpleanno 14/05/1994" in text
    assert "/cumpleanno @tag 14-05-94" in text
    assert "/cumpleanno show @tag" in text
    assert "/cumpleanno remove @tag" in text
