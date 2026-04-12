from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import markovify

from cumbot import config


URL_RE = re.compile(r"^(https?://|www\.)\S+$", re.IGNORECASE)
INLINE_URL_RE = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)
MENTION_RE = re.compile(r"@\w+")
LONG_NUMBER_RE = re.compile(r"\b\d{5,}\b")
EMOJI_ONLY_RE = re.compile(r"^[\W_]+$", re.UNICODE)
USER_ID_RE = re.compile(r"(\d+)$")
TOKEN_RE = re.compile(r"\b[\w@#']+\b", re.UNICODE)
ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
BOT_COMMAND_RE = re.compile(r"^/[A-Za-z0-9_]+(?:@[A-Za-z0-9_]+)?$")
NOISE_TOKENS = {"link", "@user", "numero", "source"}
# Suffissi che indicano un bot come mittente (case-insensitive).
_BOT_NAME_SUFFIXES = ("bot", "Bot")
_BOT_NAME_RE = re.compile(r"\bbot\b", re.IGNORECASE)
# Filtri lingua straniera e pattern bot nel corpus di training
_CYRILLIC_HEAVY_RE = re.compile(r"[а-яёА-ЯЁ]{3,}")  # ≥3 char cirillici contigui
_ARABIC_HEAVY_RE = re.compile(r"[\u0600-\u06ff]{3,}")
_FORWARDED_CHANNEL_RE = re.compile(r"source\s*[✤•·]\s*via\s*@", re.IGNORECASE)
_BOT_NOISE_RE = re.compile(
    r"/tstart\b|/premium\b|/premi\b"        # comandi game/subscription bot
    r"|meow\s+vpn"                           # VPN spam
    r"|non[- ]premium\s+users"              # feature-bot
    r"|avviane\s+una\s+con\s+/",            # quiz/game bot
    re.IGNORECASE,
)
# Stopwords EN per rilevare testo prevalentemente inglese
_EN_STOPS_TRAINING: frozenset[str] = frozenset({
    "the", "this", "that", "is", "are", "was", "were", "have", "has", "been",
    "and", "but", "for", "with", "from", "you", "not", "how", "what", "when",
    "where", "which", "who", "kinda", "wild", "would", "could", "should",
    "their", "there", "here", "your", "our", "consider", "subscribing",
    "already", "someone", "recently", "brilliant", "beautiful", "creature",
    "linked", "wallet", "account", "feature", "content",
})


def flatten_export_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""

    parts: list[str] = []
    for item in value:
        if isinstance(item, str):
            parts.append(item)
            continue
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "".join(parts)


def normalize_sender_id(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, int):
        return str(raw_value)

    value = str(raw_value).strip()
    if not value:
        return None

    if value.isdigit():
        return value

    match = USER_ID_RE.search(value)
    if match:
        return match.group(1)
    return value


def extract_sender_id(message: dict[str, Any]) -> str | None:
    for key in ("from_id", "actor_id", "user_id"):
        sender_id = normalize_sender_id(message.get(key))
        if sender_id:
            return sender_id
    return None


def extract_display_name(message: dict[str, Any]) -> str | None:
    for key in ("from", "actor", "author"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def normalize_training_text(text: str, mode: str = config.MARKOV_TEXT_MODE) -> str:
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return ""

    if mode == "raw":
        return cleaned

    normalized = unicodedata.normalize("NFKC", cleaned)
    normalized = ZERO_WIDTH_RE.sub("", normalized)
    normalized = INLINE_URL_RE.sub(" link ", normalized)
    normalized = MENTION_RE.sub("@user", normalized)
    normalized = LONG_NUMBER_RE.sub(" numero ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def meaningful_token_count(text: str) -> int:
    tokens = TOKEN_RE.findall(text.lower())
    meaningful = [
        token
        for token in tokens
        if len(token) > 1 and token not in NOISE_TOKENS and any(char.isalpha() for char in token)
    ]
    return len(meaningful)


def should_keep_training_text(text: str) -> bool:
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return False
    if len(cleaned.split()) < config.MIN_TRAINING_WORDS:
        return False
    if URL_RE.match(cleaned):
        return False
    if EMOJI_ONLY_RE.match(cleaned):
        return False
    if BOT_COMMAND_RE.match(cleaned):
        return False
    if meaningful_token_count(cleaned) < config.MIN_TRAINING_WORDS:
        return False
    # Filtra testo straniero (Cirillico/Arabo dominante)
    if _CYRILLIC_HEAVY_RE.search(cleaned) or _ARABIC_HEAVY_RE.search(cleaned):
        return False
    # Filtra messaggi forwardati da canali e pattern bot noti
    if _FORWARDED_CHANNEL_RE.search(cleaned) or _BOT_NOISE_RE.search(cleaned):
        return False
    # Filtra testo prevalentemente inglese (≥3 EN stopwords in ≤12 parole)
    words = [w.lower() for w in TOKEN_RE.findall(cleaned)]
    if len(words) <= 12:
        en_hits = sum(1 for w in words if w in _EN_STOPS_TRAINING)
        if en_hits >= 3:
            return False
    return True


def is_bot_sender(sender_id: str | None, display_name: str | None) -> bool:
    """True se il mittente sembra un bot.

    Controlla:
    - sender_id nella lista EXCLUDE_USER_IDS di config;
    - display_name che termina per "bot" (es. "MarkolinoBot") o contiene
      la parola "bot" isolata (es. "Music Bot").
    """
    if sender_id is not None:
        try:
            if int(sender_id) in config.EXCLUDE_USER_IDS:
                return True
        except ValueError:
            pass

    if display_name:
        name = display_name.strip()
        if name.lower().endswith("bot"):
            return True
        if _BOT_NAME_RE.search(name):
            return True

    return False


def classify_skip_reason(message: dict[str, Any], raw_text: str, normalized_text: str) -> str | None:
    raw_cleaned = " ".join(raw_text.split()).strip()
    normalized_cleaned = " ".join(normalized_text.split()).strip()

    if not raw_cleaned:
        return "empty_text"
    if URL_RE.match(raw_cleaned):
        return "url_only"
    if EMOJI_ONLY_RE.match(raw_cleaned):
        return "emoji_only"
    if BOT_COMMAND_RE.match(raw_cleaned):
        return "bot_command"

    if message.get("via_bot"):
        return "via_bot"

    # Messaggi inoltrati da altri: il testo appartiene alla fonte originale,
    # non al mittente del messaggio — escludiamo sempre per non contaminare le personas.
    # Eccezione: forwarded_from_id == from_id (persona che ha inoltrato un proprio vecchio msg).
    forwarded_from_id = message.get("forwarded_from_id") or ""
    from_id = str(message.get("from_id") or "")
    if forwarded_from_id and forwarded_from_id != from_id:
        return "forwarded_external"

    has_media = any(
        message.get(key)
        for key in ("media_type", "mime_type", "photo", "file", "thumbnail", "sticker_emoji")
    )
    if has_media and meaningful_token_count(normalized_cleaned) < config.MIN_TRAINING_WORDS:
        return "media_low_signal"

    if meaningful_token_count(normalized_cleaned) < config.MIN_TRAINING_WORDS:
        return "low_information"

    return None


def _build_model(corpus: list[str], state_size: int) -> markovify.Text | None:
    if not corpus:
        return None
    # Usiamo parsed_sentences per passare ogni messaggio come frase indipendente,
    # bypassando split_into_sentences() di markovify. Il sentence splitter nativo
    # divide solo su '.?!' seguiti da carattere NON-minuscolo: messaggi senza
    # punteggiatura finale o seguiti da minuscola vengono fusi, creando bigrammi
    # cross-messaggio indesiderati (es. "Sei depressa rav\nfacciamo sex chat?").
    parsed = [s.split() for s in corpus if s and s.split()]
    if not parsed:
        return None
    try:
        return markovify.Text(
            input_text=None,
            parsed_sentences=parsed,
            state_size=state_size,
            retain_original=False,
        )
    except (KeyError, ValueError):
        return None


def _save_model(model: markovify.Text, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(model.to_json(), encoding="utf-8")


def _build_corpus_stats(corpus: list[str]) -> dict[str, Any]:
    if not corpus:
        return {
            "messages": 0,
            "avg_chars": 0.0,
            "avg_words": 0.0,
            "top_tokens": [],
        }

    char_lengths = [len(item) for item in corpus]
    word_lengths = [len(item.split()) for item in corpus]
    tokens = Counter(
        token.lower()
        for text in corpus
        for token in TOKEN_RE.findall(text)
        if len(token) > 1
    )
    return {
        "messages": len(corpus),
        "avg_chars": round(sum(char_lengths) / len(char_lengths), 2),
        "avg_words": round(sum(word_lengths) / len(word_lengths), 2),
        "top_tokens": tokens.most_common(25),
    }


def resolve_export_path(export_path: str | Path = config.EXPORT_PATH) -> Path:
    candidate = Path(export_path)
    if candidate.exists():
        return candidate

    fallback_matches = sorted(config.DATA_DIR.glob("**/result.json"))
    if len(fallback_matches) == 1:
        return fallback_matches[0]

    if len(fallback_matches) > 1:
        raise FileNotFoundError(
            "EXPORT_PATH non trovato e ci sono piu export candidati in data/. "
            "Imposta EXPORT_PATH esplicitamente nel file .env."
        )

    raise FileNotFoundError(f"Export non trovato: {candidate}")


def _extract_message_created_at(message: dict[str, Any]) -> str:
    raw_date = message.get("date")
    if isinstance(raw_date, str) and raw_date.strip():
        normalized = raw_date.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.isoformat()

    raw_unix = message.get("date_unixtime")
    if raw_unix is not None:
        try:
            return datetime.fromtimestamp(int(raw_unix), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            pass

    return datetime.now(timezone.utc).isoformat()


def build_live_corpus_import_rows(
    export_path: str | Path = config.EXPORT_PATH,
) -> list[dict[str, Any]]:
    """Converte un export Telegram in righe importabili per live_corpus.

    Non applica i filtri del training Markov: importa tutti i messaggi testuali
    non vuoti, preservando il timestamp originale quando disponibile.
    """
    resolved = resolve_export_path(export_path)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []

    for message in payload.get("messages", []):
        if not isinstance(message, dict):
            continue
        if message.get("type") != "message":
            continue

        text = " ".join(flatten_export_text(message.get("text")).split()).strip()
        if not text:
            continue

        sender_id = extract_sender_id(message)
        try:
            user_id = int(sender_id) if sender_id and str(sender_id).isdigit() else None
        except ValueError:
            user_id = None

        rows.append(
            {
                "user_id": user_id,
                "username": extract_display_name(message) or "",
                "text": text,
                "created_at": _extract_message_created_at(message),
            }
        )

    return rows


def _build_export_source_key(message: dict[str, Any], created_at: str, text: str) -> str:
    message_id = message.get("id")
    if isinstance(message_id, int):
        return f"export:{message_id}"
    if isinstance(message_id, str) and message_id.strip():
        return f"export:{message_id.strip()}"

    sender_id = extract_sender_id(message) or "unknown"
    digest = hashlib.sha1(
        f"{sender_id}|{created_at}|{text}".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
    return f"exporthash:{digest}"


def build_training_corpus_import_rows(
    export_path: str | Path = config.EXPORT_PATH,
) -> list[dict[str, Any]]:
    """Converte un export Telegram in righe importabili per training_corpus."""
    resolved = resolve_export_path(export_path)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []

    for message in payload.get("messages", []):
        if not isinstance(message, dict):
            continue
        if message.get("type") != "message":
            continue

        text = " ".join(flatten_export_text(message.get("text")).split()).strip()
        if not text:
            continue

        created_at = _extract_message_created_at(message)
        sender_id = extract_sender_id(message)
        try:
            user_id = int(sender_id) if sender_id and str(sender_id).isdigit() else None
        except ValueError:
            user_id = None

        rows.append(
            {
                "source_kind": "export",
                "source_key": _build_export_source_key(message, created_at, text),
                "user_id": user_id,
                "username": extract_display_name(message) or "",
                "text": text,
                "created_at": created_at,
            }
        )

    return rows


def train_all(
    export_path: str | Path | None = config.EXPORT_PATH,
    extra_messages: list[dict[str, Any]] | None = None,
    chat_id: int | None = None,
    base_messages: list[dict[str, Any]] | None = None,
    source_label: str | None = None,
) -> dict[str, Any]:
    """Esegue il training dai messaggi dell'export + eventuali messaggi extra.

    `extra_messages` accetta una lista di dict nello stesso formato dei messaggi
    dell'export Telegram (campo `from_id`, `from`, `text`, `type`). Usato per
    incorporare i messaggi del live_corpus nel retrain.
    """
    if base_messages is None:
        resolved_export_path = resolve_export_path(export_path or config.EXPORT_PATH)
        payload = json.loads(resolved_export_path.read_text(encoding="utf-8"))
        messages = payload.get("messages", [])
        metadata_source = str(resolved_export_path)
    else:
        messages = list(base_messages)
        metadata_source = source_label or str(export_path or "<base_messages>")

    messages += extra_messages or []
    global_corpus: list[str] = []
    per_user_corpus: dict[str, list[str]] = defaultdict(list)
    display_names: dict[str, str] = {}
    raw_global_corpus: list[str] = []
    skip_reasons: Counter[str] = Counter()

    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("type") != "message":
            continue

        raw_text = flatten_export_text(message.get("text"))
        sender_id = extract_sender_id(message)
        if sender_id is None:
            skip_reasons["missing_sender"] += 1
            continue

        display_name = extract_display_name(message)
        if is_bot_sender(sender_id, display_name):
            skip_reasons["bot_sender"] += 1
            continue

        cleaned = normalize_training_text(raw_text)
        skip_reason = classify_skip_reason(message, raw_text, cleaned)
        if skip_reason is not None:
            skip_reasons[skip_reason] += 1
            continue

        if not should_keep_training_text(cleaned):
            skip_reasons["filtered_post_normalization"] += 1
            continue

        global_corpus.append(cleaned)
        per_user_corpus[sender_id].append(cleaned)
        raw_global_corpus.append(" ".join(raw_text.split()).strip())

        display_name = extract_display_name(message)
        if display_name:
            display_names[sender_id] = display_name

    users_trained: list[str] = []
    skipped: dict[str, int] = {}

    models_dir = config.resolve_models_dir(chat_id)
    models_dir.mkdir(parents=True, exist_ok=True)
    for state_size in (1, 2):
        state_dir = models_dir / f"state_{state_size}"
        if not state_dir.exists():
            continue
        for existing_model in state_dir.glob("*.json"):
            existing_model.unlink()

    for state_size in (1, 2):
        global_model = _build_model(global_corpus, state_size=state_size)
        if global_model is not None:
            _save_model(
                global_model,
                models_dir / f"state_{state_size}" / "global.json",
            )

    for sender_id, corpus in per_user_corpus.items():
        if len(corpus) < config.MIN_PERSONA_MESSAGES:
            skipped[sender_id] = len(corpus)
            continue
        trained_any = False
        for state_size in (1, 2):
            model = _build_model(corpus, state_size=state_size)
            if model is None:
                continue
            _save_model(
                model,
                models_dir / f"state_{state_size}" / f"{sender_id}.json",
            )
            trained_any = True
        if trained_any:
            users_trained.append(sender_id)

    metadata = {
        "pipeline_version": config.MARKOV_PIPELINE_VERSION,
        "text_mode": config.MARKOV_TEXT_MODE,
        "chat_id": chat_id,
        "source_export": metadata_source,
        "models_dir": str(models_dir),
        "total_messages": len(global_corpus),
        "users_trained": users_trained,
        "skipped": skipped,
        "skip_reasons": dict(skip_reasons),
        "display_names": display_names,
        "message_counts": {sender_id: len(corpus) for sender_id, corpus in per_user_corpus.items()},
        "global_stats": _build_corpus_stats(global_corpus),
        "raw_global_stats": _build_corpus_stats(raw_global_corpus),
        "user_stats": {
            sender_id: _build_corpus_stats(corpus)
            for sender_id, corpus in per_user_corpus.items()
        },
    }
    (models_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    return {
        "pipeline_version": config.MARKOV_PIPELINE_VERSION,
        "text_mode": config.MARKOV_TEXT_MODE,
        "chat_id": chat_id,
        "total_messages": len(global_corpus),
        "base_messages_used": len(base_messages) if base_messages is not None else None,
        "live_messages_added": len(extra_messages) if extra_messages else 0,
        "users_trained": len(users_trained),
        "skipped": skipped,
    }
