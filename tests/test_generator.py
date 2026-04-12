from cumbot.markov import generator


class DummyModel:
    def __init__(self, output: str | None) -> None:
        self.output = output

    def make_short_sentence(self, max_chars: int, tries: int = 100) -> str | None:
        if self.output is None:
            return None
        return self.output[:max_chars]

    def make_sentence(self, tries: int = 100) -> str | None:
        return self.output


def test_generate_draft_falls_back_to_global() -> None:
    original = generator._MODELS
    try:
        generator._MODELS = {
            1: {"global": DummyModel("fallback state 1")},
            2: {"global": DummyModel("global state 2")},
        }
        assert generator.generate_draft(persona_ids=["999"]) == "global state 2"
    finally:
        generator._MODELS = original


def test_generate_draft_truncates_long_sentence(monkeypatch) -> None:
    original = generator._MODELS
    try:
        monkeypatch.setattr(generator.config, "MARKOV_DRAFT_MAX_CHARS", 12)
        generator._MODELS = {
            1: {"global": DummyModel("fallback state 1")},
            2: {"global": DummyModel("questa frase lunghissima")},
        }
        assert generator.generate_draft() == "questa frase"
    finally:
        generator._MODELS = original


def test_generate_candidates_returns_ranked_scores() -> None:
    original = generator._MODELS
    try:
        generator._MODELS = {
            1: {"global": DummyModel("ciao ciao ciao")},
            2: {"global": DummyModel("questa frase sembra piu naturale e varia.")},
        }
        candidates = generator.generate_candidates(candidate_count=2)
        assert candidates
        assert candidates[0]["score"] >= candidates[-1]["score"]
        assert candidates[0]["text"] == "questa frase sembra piu naturale e varia."
    finally:
        generator._MODELS = original


def test_generate_candidates_filters_low_scoring_when_possible(monkeypatch) -> None:
    original = generator._MODELS
    try:
        monkeypatch.setattr(generator.config, "MARKOV_MIN_CANDIDATE_SCORE", 2.5)
        generator._MODELS = {
            1: {"global": DummyModel("10 - 9")},
            2: {"global": DummyModel("questa frase sembra piu naturale e varia.")},
        }
        candidates = generator.generate_candidates(candidate_count=2)
        assert candidates
        assert all(candidate["score"] >= 2.5 for candidate in candidates)
        assert candidates[0]["text"] == "questa frase sembra piu naturale e varia."
    finally:
        generator._MODELS = original


def test_score_candidate_penalizes_obvious_collage() -> None:
    cohesive = "Roberta è bella dal vivo o no?"
    collage = "Ma allora Roberta Domani Due ombrelloni Però Maria che fai?"
    assert generator._score_candidate(cohesive) > generator._score_candidate(collage)


def test_score_candidate_penalizes_short_window_repeats() -> None:
    repeated = "sei calabrese scimmia calabrese scimmia sei una scappata di casa?"
    cohesive = "sei una scappata di casa o stai facendo teatro?"
    assert generator._score_candidate(cohesive) > generator._score_candidate(repeated)


def test_generate_draft_doubles_candidate_pool_when_avoiding_question_endings(monkeypatch) -> None:
    captured: dict[str, int] = {}

    def fake_generate_candidates(*, persona_ids=None, candidate_count=0, live_texts=None, chat_id=None):
        captured["candidate_count"] = candidate_count
        return [{"text": "questa non finisce con punto interrogativo.", "score": 3.0}]

    monkeypatch.setattr(generator.config, "MARKOV_CANDIDATE_COUNT", 18)
    monkeypatch.setattr(generator, "generate_candidates", fake_generate_candidates)

    draft = generator.generate_draft(avoid_question_ending=True)

    assert draft == "questa non finisce con punto interrogativo."
    assert captured["candidate_count"] == 36


def test_generate_draft_uses_chat_namespace_when_available() -> None:
    original_chat_models = generator._CHAT_MODELS
    original_chat_metadata = generator._CHAT_METADATA
    try:
        generator._CHAT_MODELS = {
            -1001: {
                1: {"global": DummyModel("chat state 1")},
                2: {"global": DummyModel("chat state 2")},
            }
        }
        generator._CHAT_METADATA = {-1001: {}}
        assert generator.generate_draft(chat_id=-1001) == "chat state 2"
    finally:
        generator._CHAT_MODELS = original_chat_models
        generator._CHAT_METADATA = original_chat_metadata
