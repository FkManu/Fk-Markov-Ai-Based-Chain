from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path
from typing import Any

import markovify

from cumbot import config


LOGGER = logging.getLogger(__name__)

_MODELS: dict[int, dict[str, markovify.Text]] = {1: {}, 2: {}}
_METADATA: dict[str, Any] = {}
_CHAT_MODELS: dict[int, dict[int, dict[str, markovify.Text]]] = {}
_CHAT_METADATA: dict[int, dict[str, Any]] = {}
TOKEN_RE = re.compile(r"\b[\w@#']+\b", re.UNICODE)
DIGIT_HEAVY_RE = re.compile(r"(?:\d+\s*[-—]\s*\d+|\b\d{2,}\b)")
# Rilevamento testo non italiano nel candidato generato
_CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")
_ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
# Stopwords EN: ≥2 hit in una frase corta → testo probabilmente inglese
_EN_STOPS: frozenset[str] = frozenset({
    "the", "this", "that", "is", "are", "was", "were", "have", "has", "been",
    "and", "but", "for", "with", "from", "you", "not", "how", "what", "when",
    "where", "which", "who", "source", "via", "linked", "kinda", "wild",
    "would", "could", "should", "their", "there", "here", "your", "our",
    "consider", "subscribing", "premium", "already", "someone", "recently",
    "brilliant", "beautiful", "creature",
})
# Pattern di messaggi-bot noti nel corpus
_BOT_PATTERN_RE = re.compile(
    r"source\s*[✤•·]\s*via\s*@"          # forward canale
    r"|avviane\s+una\s+con\s+/"           # comandi bot quiz/game
    r"|/tstart|/premium|/premi\b"
    r"|meow\s+vpn"                         # spam VPN
    r"|попробуйте\s+позже"                 # russo: "try again later"
    r"|подключайся"                        # russo: "connect"
    r"|знакомиться",                       # russo: "get acquainted"
    re.IGNORECASE,
)
DISCOURSE_MARKERS = {
    "ma",
    "però",
    "pero",
    "allora",
    "quindi",
    "comunque",
    "cioè",
    "cioe",
    "perché",
    "perche",
    "poi",
}
SOFT_RESTARTERS = DISCOURSE_MARKERS | {
    "ah",
    "ahah",
    "ahah",
    "ahahah",
    "anche",
    "boh",
    "bro",
    "capito",
    "che",
    "chi",
    "come",
    "cosa",
    "dai",
    "dove",
    "eri",
    "era",
    "ho",
    "hai",
    "ha",
    "io",
    "lei",
    "loro",
    "lui",
    "mi",
    "noi",
    "non",
    "raga",
    "sei",
    "si",
    "sono",
    "sta",
    "stai",
    "sto",
    "ti",
    "tu",
    "vabbè",
    "vabbe",
    "voi",
}


def _lowercase_restart_capitals(text: str) -> str:
    """Abbassa la prima lettera delle parole capitalizzate a metà frase.

    markovify può produrre transizioni dove il secondo "pezzo" inizia con la
    maiuscola del token di training (era inizio frase). Esempio:
        "bene Qua costa ancora"  →  "bene qua costa ancora"

    Sono escluse dal lowercasing:
    - parole con uppercase non in posizione 0 (nomi composti tipo "FkManu", "iPhone")
    - parole completamente uppercase (acronimi tipo "AHAH", "LOL")
    - parole precedute da punteggiatura (.!?) — lì la maiuscola è corretta
    """
    tokens = text.split()
    result = []
    for i, tok in enumerate(tokens):
        if i == 0:
            result.append(tok)
            continue
        prev = tokens[i - 1]
        # se il token precedente finisce in punteggiatura forte → maiuscola ok
        if prev[-1:] in ".!?":
            result.append(tok)
            continue
        # se il token NON inizia con maiuscola → niente da fare
        if not tok[:1].isupper():
            result.append(tok)
            continue
        # rimuovi punteggiatura attorno al token per analizzare la parola
        word = re.sub(r"^[^\w]+|[^\w]+$", "", tok)
        if not word:
            result.append(tok)
            continue
        # Acronimo (tutto maiuscolo) → mantieni
        if word.isupper():
            result.append(tok)
            continue
        # Nome composto con uppercase non in pos 0 ("FkManu", "iPhone") → mantieni
        if any(c.isupper() for c in word[1:]):
            result.append(tok)
            continue
        # Altrimenti: abbassa la prima lettera del token (preservando eventuali
        # caratteri di punteggiatura che precedono la parola nel token)
        lowered = tok[0].lower() + tok[1:]
        result.append(lowered)
    return " ".join(result)


def _load_json_model(path: Path) -> markovify.Text | None:
    if not path.exists():
        return None
    try:
        return markovify.Text.from_json(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        LOGGER.warning("Impossibile caricare il modello %s", path)
        return None


def _read_models_from_dir(models_dir: Path) -> tuple[dict[int, dict[str, markovify.Text]], dict[str, Any]]:
    loaded: dict[int, dict[str, markovify.Text]] = {1: {}, 2: {}}
    for state_size in (1, 2):
        state_dir = models_dir / f"state_{state_size}"
        if not state_dir.exists():
            continue
        for model_path in state_dir.glob("*.json"):
            model = _load_json_model(model_path)
            if model is None:
                continue
            loaded[state_size][model_path.stem] = model

    metadata: dict[str, Any] = {}
    metadata_path = models_dir / "metadata.json"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            metadata = {}
    return loaded, metadata


def load_models(chat_id: int | None = None) -> int:
    global _MODELS, _METADATA

    if chat_id is None:
        _MODELS, _METADATA = _read_models_from_dir(config.resolve_models_dir(None))

        chats_root = config.MODELS_DIR / "chats"
        if chats_root.exists():
            for chat_dir in chats_root.iterdir():
                if not chat_dir.is_dir():
                    continue
                try:
                    namespace_chat_id = int(chat_dir.name)
                except ValueError:
                    continue
                loaded, metadata = _read_models_from_dir(chat_dir)
                _CHAT_MODELS[namespace_chat_id] = loaded
                _CHAT_METADATA[namespace_chat_id] = metadata

        return sum(len(models) for models in _MODELS.values()) + sum(
            sum(len(models) for models in bundle.values())
            for bundle in _CHAT_MODELS.values()
        )

    loaded, metadata = _read_models_from_dir(config.resolve_models_dir(chat_id))
    _CHAT_MODELS[chat_id] = loaded
    _CHAT_METADATA[chat_id] = metadata
    return sum(len(models) for models in loaded.values())


def _ensure_models_loaded(chat_id: int | None = None) -> None:
    if chat_id is None:
        if not any(_MODELS.values()) and not _METADATA:
            load_models()
        return
    if chat_id not in _CHAT_MODELS:
        load_models(chat_id=chat_id)


def _get_namespace_models(chat_id: int | None = None) -> dict[int, dict[str, markovify.Text]]:
    _ensure_models_loaded(chat_id)
    if chat_id is None:
        return _MODELS
    return _CHAT_MODELS.get(chat_id, {1: {}, 2: {}})


def _get_namespace_metadata(chat_id: int | None = None) -> dict[str, Any]:
    _ensure_models_loaded(chat_id)
    if chat_id is None:
        return _METADATA
    return _CHAT_METADATA.get(chat_id, {})


def get_model_summary(chat_id: int | None = None) -> dict[str, Any]:
    if chat_id is None:
        metadata = _get_namespace_metadata(None)
        loaded_total = sum(len(models) for models in _MODELS.values()) + sum(
            sum(len(models) for models in bundle.values())
            for bundle in _CHAT_MODELS.values()
        )
        return {
            "loaded_total": loaded_total,
            "loaded_state_1": len(_MODELS[1]),
            "loaded_state_2": len(_MODELS[2]),
            "available_personas": sorted(
                key for key in _MODELS[2].keys() if key != "global"
            ),
            "metadata": metadata,
            "models_dir": str(config.resolve_models_dir(None)),
            "loaded_chat_namespaces": sorted(_CHAT_MODELS.keys()),
        }

    models = _get_namespace_models(chat_id)
    metadata = _get_namespace_metadata(chat_id)
    return {
        "loaded_total": sum(len(state_models) for state_models in models.values()),
        "loaded_state_1": len(models[1]),
        "loaded_state_2": len(models[2]),
        "available_personas": sorted(
            key for key in models[2].keys() if key != "global"
        ),
        "metadata": metadata,
        "models_dir": str(config.resolve_models_dir(chat_id)),
        "chat_id": chat_id,
    }


def _persona_weight(persona_id: str) -> float:
    message_counts = _METADATA.get("message_counts", {})
    try:
        count = int(message_counts.get(persona_id, 1))
    except (TypeError, ValueError):
        count = 1
    return max(1.0, math.sqrt(count))


def _persona_weight_for_namespace(persona_id: str, metadata: dict[str, Any]) -> float:
    message_counts = metadata.get("message_counts", {})
    try:
        count = int(message_counts.get(persona_id, 1))
    except (TypeError, ValueError):
        count = 1
    return max(1.0, math.sqrt(count))


def _get_model_bundle(
    state_size: int,
    persona_ids: list[str] | None,
    chat_id: int | None = None,
) -> markovify.Text | None:
    models_by_state = _get_namespace_models(chat_id)
    metadata = _get_namespace_metadata(chat_id)
    models = models_by_state.get(state_size, {})
    if not models:
        return None

    if not persona_ids:
        return models.get("global")

    selected = [models[persona_id] for persona_id in persona_ids if persona_id in models]
    if not selected:
        return models.get("global")
    if len(selected) == 1:
        return selected[0]

    try:
        weights = [
            _persona_weight_for_namespace(persona_id, metadata)
            for persona_id in persona_ids
            if persona_id in models
        ]
        return markovify.combine(selected, weights)
    except (KeyError, ValueError):
        return models.get("global")


def _truncate_text(text: str, max_chars: int) -> str:
    cleaned = " ".join(text.split()).strip()
    if len(cleaned) <= max_chars:
        return cleaned

    truncated = cleaned[:max_chars].rsplit(" ", 1)[0].strip()
    if not truncated:
        truncated = cleaned[:max_chars].strip()
    return truncated.rstrip(",;:-")


def _make_markov_sentence(model: markovify.Text) -> str | None:
    short_sentence_factory = getattr(model, "make_short_sentence", None)
    if callable(short_sentence_factory):
        sentence = short_sentence_factory(config.MARKOV_DRAFT_MAX_CHARS, tries=100)
        if sentence:
            return sentence

    sentence_factory = getattr(model, "make_sentence", None)
    if callable(sentence_factory):
        sentence = sentence_factory(tries=100)
        if sentence:
            return _truncate_text(sentence, config.MARKOV_DRAFT_MAX_CHARS)
    return None


def _score_candidate(text: str) -> float:
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return float("-inf")

    words = TOKEN_RE.findall(cleaned.lower())
    if not words:
        return float("-inf")

    chars = len(cleaned)
    unique_ratio = len(set(words)) / max(1, len(words))
    repeated_adjacent = sum(1 for left, right in zip(words, words[1:]) if left == right)
    short_window_repeats = 0
    for index, word in enumerate(words):
        if word in words[max(0, index - 3):index]:
            short_window_repeats += 1
    placeholder_penalty = cleaned.lower().count("@user") * 0.5 + cleaned.lower().count(" link ") * 0.5
    # '?' è il terminal state dominante nel corpus (~70-80% dei candidati).
    # Penalità elevata per far emergere i candidati non-domanda nel ranking.
    if cleaned[-1] == "?":
        punctuation_bonus = -2.0
    elif cleaned[-1] in ".!":
        punctuation_bonus = 0.3
    else:
        punctuation_bonus = 0.0
    long_word_penalty = sum(1 for word in words if len(word) > 20) * 0.2
    alpha_tokens = [word for word in words if any(char.isalpha() for char in word)]
    alpha_token_penalty = 2.5 if len(alpha_tokens) < 3 else 0.0
    digit_penalty = (sum(char.isdigit() for char in cleaned) / max(1, chars)) * 8.0
    structured_noise_penalty = 1.75 if DIGIT_HEAVY_RE.search(cleaned) else 0.0
    # Penalità lingua straniera e pattern bot noti nel corpus
    cyrillic_chars = len(_CYRILLIC_RE.findall(cleaned))
    arabic_chars = len(_ARABIC_RE.findall(cleaned))
    foreign_script_penalty = min(cyrillic_chars + arabic_chars, 3) * 4.0
    en_hits = sum(1 for w in words if w in _EN_STOPS)
    # ≥2 stopword EN in ≤15 parole → quasi certamente frase inglese
    english_penalty = max(0, en_hits - 1) * 1.5 if len(words) <= 15 else max(0, en_hits - 2) * 1.0
    bot_pattern_penalty = 8.0 if _BOT_PATTERN_RE.search(cleaned) else 0.0
    discourse_count = sum(1 for word in words if word in DISCOURSE_MARKERS)
    discourse_penalty = max(0, discourse_count - 2) * 0.4
    clause_count = len(re.findall(r"[,.!?;:]", cleaned)) + 1
    clause_penalty = max(0, clause_count - 3) * 0.35
    raw_tokens = cleaned.split()
    restart_count = 0
    soft_restart_count = 0
    for index, token in enumerate(raw_tokens[1:], start=1):
        previous = raw_tokens[index - 1]
        if token[:1].isupper() and previous[-1:] not in ".!?":
            restart_count += 1
            normalized = re.sub(r"^[^\w@#']+|[^\w@#']+$", "", token).lower()
            if normalized in SOFT_RESTARTERS:
                soft_restart_count += 1
    # 1 restart: costo 2.0 (scoraggiato — candidato 0-restart vince quasi sempre)
    # 2+ restart: costo 2.0 + 5.0*(r-1) → garantito sotto threshold 2.5
    restart_penalty = min(restart_count, 1) * 2.0 + max(0, restart_count - 1) * 5.0
    soft_restart_penalty = soft_restart_count * 0.55

    target_chars = 55
    length_score = max(0.0, 1 - abs(chars - target_chars) / target_chars)
    word_score = max(0.0, 1 - abs(len(words) - 9) / 9)

    return (
        (length_score * 3.0)
        + (word_score * 2.0)
        + (unique_ratio * 2.0)
        + punctuation_bonus
        - (repeated_adjacent * 1.25)
        - (short_window_repeats * 0.45)
        - placeholder_penalty
        - long_word_penalty
        - alpha_token_penalty
        - digit_penalty
        - structured_noise_penalty
        - discourse_penalty
        - clause_penalty
        - restart_penalty
        - soft_restart_penalty
        - foreign_script_penalty
        - english_penalty
        - bot_pattern_penalty
    )


def build_live_model(texts: list[str], state_size: int) -> markovify.Text | None:
    """Costruisce un modello markovify temporaneo dai testi live della chat.

    Richiede almeno LIVE_CORPUS_MIN_MESSAGES testi per state_size=1,
    il doppio per state_size=2. Ritorna None se i dati sono insufficienti
    o la costruzione fallisce.
    """
    min_required = config.LIVE_CORPUS_MIN_MESSAGES * (1 if state_size == 1 else 2)
    cleaned = [" ".join(t.split()).strip() for t in texts if t and t.strip()]
    if len(cleaned) < min_required:
        return None
    # Usiamo parsed_sentences per passare ogni messaggio come frase indipendente,
    # bypassando il sentence splitter nativo (che fonde messaggi senza punteggiatura
    # o seguiti da minuscola, creando bigrammi cross-messaggio indesiderati).
    parsed = [t.split() for t in cleaned if t.split()]
    try:
        return markovify.Text(
            input_text=None,
            parsed_sentences=parsed,
            state_size=state_size,
        )
    except Exception:
        return None


def _get_combined_model(
    state_size: int,
    persona_ids: list[str] | None,
    live_texts: list[str] | None,
    chat_id: int | None = None,
) -> markovify.Text | None:
    """Ottiene il modello base e lo combina opzionalmente con il live model."""
    model = _get_model_bundle(state_size=state_size, persona_ids=persona_ids, chat_id=chat_id)
    if model is None:
        return None
    if live_texts:
        live_model = build_live_model(live_texts, state_size)
        if live_model is not None:
            try:
                model = markovify.combine(
                    [model, live_model],
                    [1.0, config.LIVE_CORPUS_WEIGHT],
                )
            except Exception:
                pass  # fallback silenzioso al modello base
    return model


def generate_question_candidates(
    question_type: str,
    seed_words: list[str],
    persona_ids: list[str] | None = None,
    candidate_count: int = config.MARKOV_CANDIDATE_COUNT,
    live_texts: list[str] | None = None,
    chat_id: int | None = None,
) -> list[dict[str, Any]]:
    """Genera candidati che iniziano con seed_words per rispondere a una domanda.

    Usa make_sentence_with_start() su ogni seed. Ritorna lista vuota se non
    trova candidati validi — il chiamante deve fare fallback alla generazione normale.
    """
    if not seed_words:
        return []

    normalized_personas = [str(p) for p in (persona_ids or [])]
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    seeds = seed_words[:6]  # max 6 seed per non perdere troppo tempo

    for state_size in (2, 1):
        model = _get_combined_model(state_size, normalized_personas, live_texts, chat_id=chat_id)
        if model is None:
            continue

        make_start = getattr(model, "make_sentence_with_start", None)
        if not callable(make_start):
            continue

        for seed in seeds:
            for _ in range(3):  # 3 tentativi per seed
                try:
                    sentence = make_start(seed, strict=False, tries=60)
                except (KeyError, Exception):
                    sentence = None
                if not sentence:
                    continue

                cleaned = _lowercase_restart_capitals(" ".join(sentence.split()).strip())
                if not cleaned or cleaned in seen:
                    continue

                score = _score_candidate(cleaned) + (state_size * 0.35)
                if score < config.MARKOV_MIN_CANDIDATE_SCORE:
                    continue

                seen.add(cleaned)
                candidates.append({"text": cleaned, "state_size": state_size, "score": score})
                if len(candidates) >= candidate_count:
                    break

            if len(candidates) >= candidate_count:
                break

        if len(candidates) >= 2:
            break

    return sorted(candidates, key=lambda item: item["score"], reverse=True)


def generate_candidates(
    persona_ids: list[str] | None = None,
    candidate_count: int = config.MARKOV_CANDIDATE_COUNT,
    live_texts: list[str] | None = None,
    chat_id: int | None = None,
) -> list[dict[str, Any]]:
    normalized_personas = [str(persona_id) for persona_id in (persona_ids or [])]
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for state_size in (2, 1):
        model = _get_combined_model(state_size, normalized_personas, live_texts, chat_id=chat_id)
        if model is None:
            continue

        attempts = max(candidate_count * 4, 12)
        for _ in range(attempts):
            sentence = None
            for _attempt in range(10):
                sentence = _make_markov_sentence(model)
                if sentence:
                    break
            if not sentence:
                continue

            cleaned = _lowercase_restart_capitals(" ".join(sentence.split()).strip())
            if not cleaned or cleaned in seen:
                continue

            seen.add(cleaned)
            candidates.append(
                {
                    "text": cleaned,
                    "state_size": state_size,
                    "score": _score_candidate(cleaned) + (state_size * 0.35),
                }
            )
            if len(candidates) >= candidate_count:
                break

        if len(candidates) >= candidate_count:
            break

    ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
    viable = [
        candidate
        for candidate in ranked
        if candidate["score"] >= config.MARKOV_MIN_CANDIDATE_SCORE
    ]
    return viable or ranked


def generate_draft(
    persona_ids: list[str] | None = None,
    sentences: int = 1,
    live_texts: list[str] | None = None,
    question_type: str | None = None,
    seed_words: list[str] | None = None,
    avoid_question_ending: bool = False,
    chat_id: int | None = None,
) -> str:
    if seed_words:
        q_candidates = generate_question_candidates(
            question_type=question_type or "generic",
            seed_words=seed_words,
            persona_ids=persona_ids,
            live_texts=live_texts,
            chat_id=chat_id,
        )
        if avoid_question_ending:
            q_candidates = [c for c in q_candidates if not c["text"].endswith("?")]
        if q_candidates:
            return q_candidates[0]["text"]
    candidate_count = config.MARKOV_CANDIDATE_COUNT * 2 if avoid_question_ending else config.MARKOV_CANDIDATE_COUNT
    candidates = generate_candidates(
        persona_ids=persona_ids,
        live_texts=live_texts,
        candidate_count=candidate_count,
        chat_id=chat_id,
    )
    if avoid_question_ending:
        non_q = [c for c in candidates if not c["text"].endswith("?")]
        candidates = non_q if non_q else candidates
    if candidates:
        return candidates[0]["text"]
    return "raga sono in buffering cosmico"
