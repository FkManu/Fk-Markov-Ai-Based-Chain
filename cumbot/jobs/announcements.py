from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime

from telegram.ext import ContextTypes

from cumbot.announcement_store import announcement_store
from cumbot import config
from cumbot.db.state import get_due_announcements


LOGGER = logging.getLogger(__name__)


def _local_now() -> datetime:
    try:
        tz = zoneinfo.ZoneInfo(config.ANNOUNCEMENT_TIMEZONE)
    except Exception:
        tz = zoneinfo.ZoneInfo("Europe/Rome")
    return datetime.now(tz)


async def send_due_announcements(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job eseguito ogni minuto: invia gli annunci programmati per l'ora corrente."""
    now = _local_now()
    hour = now.hour
    minute = now.minute

    announcements = await get_due_announcements(hour, minute)
    if not announcements:
        return

    for ann in announcements:
        try:
            sent = await context.bot.send_message(chat_id=ann.chat_id, text=ann.text)
            announcement_store.mark(ann.chat_id, sent.message_id)
            LOGGER.info(
                "[ANNUNCIO] chat=%s id=%s ora=%02d:%02d inviato",
                ann.chat_id,
                ann.id,
                hour,
                minute,
            )
        except Exception as exc:
            LOGGER.warning(
                "[ANNUNCIO] chat=%s id=%s errore: %s",
                ann.chat_id,
                ann.id,
                exc,
            )
