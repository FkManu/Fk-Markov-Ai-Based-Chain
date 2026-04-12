from cumbot import access


def test_is_chat_allowed_allows_everything_without_whitelist(monkeypatch) -> None:
    monkeypatch.setattr(access.config, "ALLOWED_CHAT_IDS", frozenset())
    monkeypatch.setattr(access.config, "ADMIN_USER_IDS", {1})
    assert access.is_chat_allowed(-100, 999) is True


def test_is_chat_allowed_respects_whitelist_and_admin_private(monkeypatch) -> None:
    monkeypatch.setattr(access.config, "ALLOWED_CHAT_IDS", frozenset({-1001}))
    monkeypatch.setattr(access.config, "ADMIN_USER_IDS", {42})
    assert access.is_chat_allowed(-1001, 999) is True
    assert access.is_chat_allowed(-1002, 999) is False
    assert access.is_chat_allowed(42, 42) is True


def test_is_chat_allowed_accepts_supergroup_shorthand_ids(monkeypatch) -> None:
    monkeypatch.setattr(access.config, "ALLOWED_CHAT_IDS", frozenset({2026712691}))
    monkeypatch.setattr(access.config, "ADMIN_USER_IDS", {42})
    assert access.is_chat_allowed(-1002026712691, 999) is True
