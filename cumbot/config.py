from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ADMIN_USER_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_USER_IDS", "").split(",")
    if value.strip()
}
ALLOWED_CHAT_IDS: frozenset[int] = frozenset(
    int(v.strip())
    for v in os.getenv("ALLOWED_CHAT_IDS", "").split(",")
    if v.strip().lstrip("-").isdigit()
)
# User ID da escludere dal training (bot noti, account da ignorare).
# Formato: EXCLUDE_USER_IDS=5448250840,123456789
EXCLUDE_USER_IDS: frozenset[int] = frozenset(
    int(value.strip())
    for value in os.getenv("EXCLUDE_USER_IDS", "").split(",")
    if value.strip().lstrip("-").isdigit()
)

RECENT_CONTEXT_MAX_MESSAGES = 20
RECENT_CONTEXT_WINDOW = 10
MIN_PERSONA_MESSAGES = 100
MIN_TRAINING_WORDS = 3
MARKOV_PIPELINE_VERSION = "2.0"
MARKOV_TEXT_MODE = os.getenv("MARKOV_TEXT_MODE", "normalized").strip().lower() or "normalized"
MARKOV_CANDIDATE_COUNT = int(os.getenv("MARKOV_CANDIDATE_COUNT", "18"))
MARKOV_DRAFT_MAX_CHARS = int(os.getenv("MARKOV_DRAFT_MAX_CHARS", "120"))
MARKOV_MIN_CANDIDATE_SCORE = float(os.getenv("MARKOV_MIN_CANDIDATE_SCORE", "2.5"))
AUTOPOST_MIN_MESSAGES = int(os.getenv("AUTOPOST_MIN_MESSAGES", "20"))
AUTOPOST_MAX_MESSAGES = int(os.getenv("AUTOPOST_MAX_MESSAGES", "30"))
REACTION_PROBABILITY = float(os.getenv("REACTION_PROBABILITY", "0.06"))
REACTION_EMOJI = [
    e.strip()
    for e in os.getenv(
        "REACTION_EMOJI",
        "😂,💀,🔥,😭,👀,🤣,😈,💯,🤡,😤,🫡,🥹,💅,🤌",
    ).split(",")
    if e.strip()
]
GIF_CONTEXT_MINUTES = int(os.getenv("GIF_CONTEXT_MINUTES", "15"))
GIF_TRIGGER_COUNT = int(os.getenv("GIF_TRIGGER_COUNT", "3"))
GIF_RESEND_PROBABILITY = float(os.getenv("GIF_RESEND_PROBABILITY", "0.4"))
GIF_MENTION_PROBABILITY = float(os.getenv("GIF_MENTION_PROBABILITY", "0.15"))
GIF_CORPUS_MAX = int(os.getenv("GIF_CORPUS_MAX", "200"))
STICKER_RESEND_PROBABILITY = float(os.getenv("STICKER_RESEND_PROBABILITY", "0.08"))
STICKER_CORPUS_MAX = int(os.getenv("STICKER_CORPUS_MAX", "100"))

DATABASE_PATH = BASE_DIR / os.getenv("DATABASE_PATH", "runtime/cumbot.sqlite3")
EXPORT_PATH = BASE_DIR / os.getenv("EXPORT_PATH", "data/export.json")
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = BASE_DIR / "models"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# API key dedicata per /ask (compound-beta). Se vuota usa GROQ_API_KEY.
# Tenerla separata evita che i rate limit di /ask impattino refiner e classifier.
GROQ_ASK_API_KEY = os.getenv("GROQ_ASK_API_KEY", "")
GROQ_REFINER_MODEL = os.getenv("GROQ_REFINER_MODEL", "llama-3.3-70b-versatile")
GROQ_ASK_MODEL = os.getenv("GROQ_ASK_MODEL", "llama-3.3-70b-versatile")
# Catena di fallback per /ask: compound-beta → compound-beta-mini → GROQ_ASK_MODEL
GROQ_COMPOUND_MODEL = os.getenv("GROQ_COMPOUND_MODEL", "compound-beta")
GROQ_COMPOUND_MINI_MODEL = os.getenv("GROQ_COMPOUND_MINI_MODEL", "compound-beta-mini")
GROQ_REFINER_TEMPERATURE = float(os.getenv("GROQ_REFINER_TEMPERATURE", "0.76"))
GROQ_ASK_TEMPERATURE = float(os.getenv("GROQ_ASK_TEMPERATURE", "0.6"))
GROQ_CLASSIFY_ENABLED = os.getenv("GROQ_CLASSIFY_ENABLED", "false").strip().lower() == "true"

LIVE_CORPUS_WEIGHT = float(os.getenv("LIVE_CORPUS_WEIGHT", "0.2"))
LIVE_CORPUS_MIN_MESSAGES = int(os.getenv("LIVE_CORPUS_MIN_MESSAGES", "15"))
LIVE_CORPUS_LIMIT = int(os.getenv("LIVE_CORPUS_LIMIT", "30"))
IMMEDIATE_CONTEXT_SIZE = int(os.getenv("IMMEDIATE_CONTEXT_SIZE", "5"))

TRAINING_CORPUS_MAX_PER_CHAT = int(os.getenv("TRAINING_CORPUS_MAX_PER_CHAT", "1000000"))

ANNOUNCEMENT_TIMEZONE = os.getenv("ANNOUNCEMENT_TIMEZONE", "Europe/Rome")
# Scheduler retrain: ora locale (0-23) entro cui il job giornaliero può girare.
# Formato: HH oppure HH-HH (es. "3" = solo alle 3, "2-4" = tra le 2 e le 4).
RETRAIN_SCHEDULE_HOUR = os.getenv("RETRAIN_SCHEDULE_HOUR", "3")
# Minimo di nuovi messaggi live dalla volta precedente per avviare il retrain.
RETRAIN_MIN_NEW_MESSAGES = int(os.getenv("RETRAIN_MIN_NEW_MESSAGES", "50"))


def resolve_models_dir(chat_id: int | None = None) -> Path:
    if chat_id is None:
        return MODELS_DIR
    return MODELS_DIR / "chats" / str(chat_id)
