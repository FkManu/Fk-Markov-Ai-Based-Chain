from __future__ import annotations

import asyncio
import logging
import re
import zoneinfo
from datetime import datetime, timezone

from telegram.ext import ContextTypes

from cumbot import config
from cumbot.db.state import (
    count_training_corpus_rows,
    get_all_chats,
    get_chat_settings,
    get_chat_training_state,
    get_latest_live_corpus_id,
    get_live_corpus_rows_for_training_corpus,
    get_training_corpus_for_training,
    insert_training_corpus_rows,
    trim_training_corpus,
    update_chat_training_state,
)
from cumbot.markov.generator import load_models
from cumbot.markov.trainer import train_all


LOGGER = logging.getLogger(__name__)

_HOUR_RANGE_RE = re.compile(r"^(\d{1,2})(?:-(\d{1,2}))?$")


def _is_within_schedule_window() -> bool:
    """Controlla se l'ora locale corrente rientra nella finestra RETRAIN_SCHEDULE_HOUR.

    Formato: "3" (solo alle 3) oppure "2-4" (tra le 2 e le 4 incluse).
    Se il valore è malformato, ritorna True (finestra sempre aperta — fail-safe).
    """
    raw = config.RETRAIN_SCHEDULE_HOUR.strip()
    m = _HOUR_RANGE_RE.match(raw)
    if not m:
        return True
    try:
        tz = zoneinfo.ZoneInfo(config.ANNOUNCEMENT_TIMEZONE)
    except Exception:
        tz = zoneinfo.ZoneInfo("Europe/Rome")
    current_hour = datetime.now(tz).hour
    start_hour = int(m.group(1))
    end_hour = int(m.group(2)) if m.group(2) is not None else start_hour
    return start_hour <= current_hour <= end_hour


async def _retrain_chat(chat_id: int, lock: asyncio.Lock) -> None:
    """Consolida il live corpus e ricostruisce i modelli per una singola chat.

    Non lancia eccezioni: tutti gli errori vengono loggati.
    """
    settings = await get_chat_settings(chat_id)
    if settings is None:
        return

    async with lock:
        try:
            training_state = await get_chat_training_state(chat_id)
            last_live_id = training_state.last_live_corpus_id if training_state else None

            pending_rows = await get_live_corpus_rows_for_training_corpus(
                chat_id, after_id=last_live_id
            )
            new_count = len(pending_rows)

            if new_count < config.RETRAIN_MIN_NEW_MESSAGES:
                LOGGER.debug(
                    "[AUTO-RETRAIN] chat=%s: %d nuovi messaggi < soglia %d, skip",
                    chat_id,
                    new_count,
                    config.RETRAIN_MIN_NEW_MESSAGES,
                )
                return

            consolidated = await insert_training_corpus_rows(chat_id, pending_rows)
            await trim_training_corpus(chat_id, config.TRAINING_CORPUS_MAX_PER_CHAT)
            corpus_count = await count_training_corpus_rows(chat_id)

            if corpus_count == 0:
                LOGGER.warning("[AUTO-RETRAIN] chat=%s: training_corpus vuoto, skip", chat_id)
                return

            base_messages = await get_training_corpus_for_training(chat_id)
            stats = await asyncio.to_thread(
                train_all,
                None,      # export_path: non serve, usiamo base_messages
                None,      # extra_messages
                chat_id,
                base_messages,
                f"training_corpus:{chat_id}",
            )
            load_models(chat_id=chat_id)

            latest_live_id = await get_latest_live_corpus_id(chat_id)
            training_corpus_size = await count_training_corpus_rows(chat_id)
            await update_chat_training_state(
                chat_id,
                last_retrain_at=datetime.now(timezone.utc).isoformat(),
                last_live_corpus_id=latest_live_id,
                training_corpus_size=training_corpus_size,
                models_path=str(config.resolve_models_dir(chat_id)),
            )
            LOGGER.info(
                "[AUTO-RETRAIN] chat=%s: +%d live consolidati, %d totali, %d msgs usati, "
                "%d personas, %d skipped",
                chat_id,
                consolidated,
                corpus_count,
                stats.get("total_messages", 0),
                stats.get("users_trained", 0),
                len(stats.get("skipped", {})),
            )
        except Exception as exc:
            LOGGER.exception("[AUTO-RETRAIN] chat=%s: errore - %s", chat_id, exc)


async def scheduled_retrain(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job giornaliero: consolida il live corpus e ricostruisce i modelli per ogni chat.

    Guardrail:
    - gira solo se l'ora locale rientra in RETRAIN_SCHEDULE_HOUR;
    - per ogni chat verifica che ci siano almeno RETRAIN_MIN_NEW_MESSAGES nuovi
      messaggi live dall'ultimo retrain;
    - usa il retrain_lock per non sovrapporsi con retrain manuali;
    - un errore su una chat non blocca le altre.
    """
    if not _is_within_schedule_window():
        return

    lock: asyncio.Lock = context.application.bot_data.get("retrain_lock") or asyncio.Lock()
    chats = await get_all_chats()
    group_chats = [c for c in chats if c.chat_type in ("group", "supergroup")]

    LOGGER.info("[AUTO-RETRAIN] avvio per %d chat di gruppo", len(group_chats))
    for chat in group_chats:
        await _retrain_chat(chat.chat_id, lock)
    LOGGER.info("[AUTO-RETRAIN] completato")
