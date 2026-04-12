import asyncio

from cumbot.groq import classifier


def test_classifier_returns_generic_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(classifier.config, "GROQ_CLASSIFY_ENABLED", False)

    async def scenario() -> None:
        result = await classifier.classify_intent("@bot sei un coglione", bot_username="bot")
        assert result == "generic"

    asyncio.run(scenario())


def test_classifier_strips_bot_mention_and_accepts_valid_label(monkeypatch) -> None:
    monkeypatch.setattr(classifier.config, "GROQ_CLASSIFY_ENABLED", True)
    monkeypatch.setattr(classifier.config, "GROQ_API_KEY", "test-key")

    calls: dict[str, str] = {}

    async def fake_generate_text(**kwargs):
        calls["prompt"] = kwargs["user_prompt"]
        return "roast"

    monkeypatch.setattr(classifier.groq_service, "generate_text", fake_generate_text)

    async def scenario() -> None:
        result = await classifier.classify_intent("@MyBot sei inutile", bot_username="MyBot")
        assert result == "roast"

    asyncio.run(scenario())
    assert calls["prompt"] == "sei inutile"


def test_classifier_falls_back_to_generic_on_unknown_label(monkeypatch) -> None:
    monkeypatch.setattr(classifier.config, "GROQ_CLASSIFY_ENABLED", True)
    monkeypatch.setattr(classifier.config, "GROQ_API_KEY", "test-key")

    async def fake_generate_text(**kwargs):
        return "compliment"

    monkeypatch.setattr(classifier.groq_service, "generate_text", fake_generate_text)

    async def scenario() -> None:
        result = await classifier.classify_intent("bravissimo")
        assert result == "generic"

    asyncio.run(scenario())
