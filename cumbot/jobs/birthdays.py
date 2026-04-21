from __future__ import annotations

import calendar
import html
import logging
import random
import zoneinfo
from datetime import datetime

from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from cumbot import config
from cumbot.db.state import get_pending_birthdays_for_date, mark_birthday_delivered


LOGGER = logging.getLogger(__name__)

_BIRTHDAY_TEMPLATES = [
    "Facciamo tantissimi auguri di compleanno a {mention} per i suoi {age} anni {emoji}",
    "Auguroni a {mention}, oggi festeggia i suoi {age} anni {emoji}",
    "Buon compleanno a {mention}, tanti auguri per i suoi {age} anni {emoji}",
]
_PARTY_EMOJIS = ["🎉", "🥳", "🎂", "🍾", "🎊"]
_FEB29_SUFFIXES = [
    "Il compleanno vero sarebbe il 29/02, ma quest'anno febbraio ha fatto il ricchione🤣",
    "Tecnicamente il compleanno sarebbe il 29/02, ma l'anno non bisestile sta facendo il furbo.",
]


def _tz() -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(config.ANNOUNCEMENT_TIMEZONE)
    except Exception:
        return zoneinfo.ZoneInfo("Europe/Rome")


def _local_now() -> datetime:
    return datetime.now(_tz())


def _html_mention(*, user_id: int, username: str, display_name: str) -> str:
    label = f"@{username}" if username else (display_name or str(user_id))
    return f'<a href="tg://user?id={user_id}">{html.escape(label)}</a>'


def _build_birthday_message(
    *,
    user_id: int,
    username: str,
    display_name: str,
    birth_year: int,
    current_year: int,
    is_feb29_fallback: bool,
) -> str:
    template = random.choice(_BIRTHDAY_TEMPLATES)
    emoji = random.choice(_PARTY_EMOJIS)
    mention = _html_mention(user_id=user_id, username=username, display_name=display_name)
    message = template.format(
        mention=mention,
        age=max(0, current_year - birth_year),
        emoji=emoji,
    )
    if is_feb29_fallback:
        message += " " + random.choice(_FEB29_SUFFIXES)
    return message


async def send_due_birthdays(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = _local_now()
    if now.hour != 0 or now.minute != 0:
        return

    is_feb29_fallback_day = now.month == 2 and now.day == 28 and not calendar.isleap(now.year)
    birthdays = await get_pending_birthdays_for_date(
        month=now.month,
        day=now.day,
        celebration_year=now.year,
        include_feb29_fallback=is_feb29_fallback_day,
    )
    if not birthdays:
        return

    for birthday in birthdays:
        is_fallback = is_feb29_fallback_day and birthday.month == 2 and birthday.day == 29
        try:
            sent = await context.bot.send_message(
                chat_id=birthday.chat_id,
                text=_build_birthday_message(
                    user_id=birthday.user_id,
                    username=birthday.username,
                    display_name=birthday.display_name,
                    birth_year=birthday.birth_year,
                    current_year=now.year,
                    is_feb29_fallback=is_fallback,
                ),
                parse_mode=ParseMode.HTML,
            )
            delivered = await mark_birthday_delivered(
                birthday_id=birthday.id,
                celebration_year=now.year,
                delivered_at=now.isoformat(),
            )
            LOGGER.info(
                "[CUMPLEANNO] chat=%s birthday_id=%s delivered=%s message_id=%s fallback_2902=%s",
                birthday.chat_id,
                birthday.id,
                delivered,
                sent.message_id,
                is_fallback,
            )
        except Exception as exc:
            LOGGER.warning(
                "[CUMPLEANNO] chat=%s birthday_id=%s errore: %s",
                birthday.chat_id,
                birthday.id,
                exc,
            )
