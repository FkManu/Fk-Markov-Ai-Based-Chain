from cumbot.telegram_context.collector import RecentContextCollector


def test_recent_context_keeps_last_messages() -> None:
    collector = RecentContextCollector(max_messages=3)
    collector.add_message(1, 1, "a", "A", "uno")
    collector.add_message(1, 2, "b", "B", "due")
    collector.add_message(1, 3, "c", "C", "tre")
    collector.add_message(1, 4, "d", "D", "quattro")

    recent = collector.get_recent(1, n=10)
    assert [item["text"] for item in recent] == ["due", "tre", "quattro"]
