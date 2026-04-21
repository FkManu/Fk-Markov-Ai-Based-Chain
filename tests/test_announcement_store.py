from cumbot.announcement_store import AnnouncementMessageStore


def test_announcement_store_marks_and_recognizes_messages() -> None:
    store = AnnouncementMessageStore(ttl=3600)
    assert store.is_announcement(-1001, 10) is False

    store.mark(-1001, 10)
    assert store.is_announcement(-1001, 10) is True
    assert store.is_announcement(-1001, 11) is False


def test_announcement_store_expires_messages(monkeypatch) -> None:
    fake_now = 1000.0

    def _fake_time() -> float:
        return fake_now

    monkeypatch.setattr("cumbot.announcement_store.time.time", _fake_time)
    store = AnnouncementMessageStore(ttl=10)
    store.mark(-1001, 20)
    store._store[(-1001, 20)].created_at = fake_now
    assert store.is_announcement(-1001, 20) is True

    fake_now = 1015.0
    assert store.is_announcement(-1001, 20) is False
