from cumbot.markov.tone import detect_tone


def test_detect_tone_aggressive() -> None:
    ctx = [{"text": "sei uno stronzo"}, {"text": "vaffanculo frocio"}]
    assert detect_tone(ctx, input_text="@bot rispondimi") == "aggressive"


def test_detect_tone_playful() -> None:
    ctx = [{"text": "ahahahah"}, {"text": "hahaha sei pazzo"}, {"text": "lol"}]
    assert detect_tone(ctx) == "playful"


def test_detect_tone_neutral() -> None:
    ctx = [{"text": "ok ci vediamo dopo"}, {"text": "si dai"}]
    assert detect_tone(ctx) == "neutral"
