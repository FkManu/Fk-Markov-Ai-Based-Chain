from __future__ import annotations

import re
import zoneinfo
from dataclasses import dataclass
from datetime import date, datetime

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from cumbot import config
from cumbot.access import is_chat_allowed
from cumbot.db.state import (
    BirthdayEntry,
    delete_birthday,
    get_birthday,
    register_chat,
    resolve_known_chat_user,
    upsert_birthday,
)


_DATE_RE = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2}|\d{4})$")
_REMOVE_ALIASES = {"remove", "delete", "rm", "rimuovi"}
_SHOW_ALIASES = {"show", "info", "vedi"}


@dataclass(slots=True)
class BirthdayTarget:
    user_id: int
    username: str
    display_name: str


def _usage_text() -> str:
    return (
        "Uso:\n"
        "/cumpleanno 14/05/1994\n"
        "/cumpleanno @tag 14-05-94\n"
        "/cumpleanno show @tag\n"
        "/cumpleanno remove @tag"
    )


def _tz() -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(config.ANNOUNCEMENT_TIMEZONE)
    except Exception:
        return zoneinfo.ZoneInfo("Europe/Rome")


def _local_today() -> date:
    return datetime.now(_tz()).date()


def _normalize_two_digit_year(value: str) -> int:
    year = int(value)
    if year <= 25:
        return 2000 + year
    return 1900 + year


def _parse_birthday_date(raw_value: str) -> tuple[int, int, int] | None:
    match = _DATE_RE.fullmatch(raw_value.strip())
    if match is None:
        return None

    day = int(match.group(1))
    month = int(match.group(2))
    raw_year = match.group(3)
    year = int(raw_year) if len(raw_year) == 4 else _normalize_two_digit_year(raw_year)

    try:
        parsed = date(year, month, day)
    except ValueError:
        return None

    if parsed > _local_today():
        return None
    return parsed.day, parsed.month, parsed.year


def _target_label(target: BirthdayTarget | BirthdayEntry) -> str:
    if target.username:
        return f"@{target.username}"
    return target.display_name or str(target.user_id)


def _format_birthday(entry: BirthdayEntry) -> str:
    return f"{entry.day:02d}/{entry.month:02d}/{entry.birth_year:04d}"


async def _resolve_target_from_username(chat_id: int, token: str) -> BirthdayTarget | None:
    resolved = await resolve_known_chat_user(chat_id, token)
    if resolved is None:
        return None
    user_id, username, display_name = resolved
    return BirthdayTarget(
        user_id=user_id,
        username=username,
        display_name=display_name or (f"@{username}" if username else str(user_id)),
    )


def _self_target(update: Update) -> BirthdayTarget | None:
    user = update.effective_user
    if user is None:
        return None
    display_name = " ".join(
        part for part in [user.first_name, user.last_name] if part
    ).strip() or (f"@{user.username}" if user.username else str(user.id))
    return BirthdayTarget(
        user_id=user.id,
        username=user.username or "",
        display_name=display_name,
    )


async def _resolve_target(
    update: Update,
    chat_id: int,
    token: str | None,
) -> BirthdayTarget | None:
    if token is None:
        return _self_target(update)
    if not token.startswith("@"):
        return None
    return await _resolve_target_from_username(chat_id, token)


async def handle_cumpleanno(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if message is None or chat is None:
        return

    user_id = user.id if user is not None else None
    if not is_chat_allowed(chat.id, user_id):
        return

    if chat.type not in {"group", "supergroup"}:
        await message.reply_text(
            "Questo comando funziona solo nei gruppi: i compleanni vengono salvati per chat."
        )
        return

    await register_chat(chat.id, chat.type, chat.title)
    args = list(context.args)
    if not args:
        await message.reply_text(_usage_text())
        return

    first = args[0].strip()
    first_lower = first.lower()

    if first_lower in _SHOW_ALIASES:
        if len(args) > 2 or (len(args) == 2 and not args[1].startswith("@")):
            await message.reply_text(_usage_text())
            return
        target = await _resolve_target(update, chat.id, args[1] if len(args) > 1 else None)
        if target is None:
            await message.reply_text(
                "Non riesco a capire il tag indicato. Se usi `@tag`, quella persona deve "
                "essere gia nota in questo gruppo oppure deve impostarsi il compleanno da sola.\n\n"
                + _usage_text(),
            )
            return
        entry = await get_birthday(chat.id, target.user_id)
        if entry is None:
            await message.reply_text(
                f"Non trovo nessun compleanno salvato per {_target_label(target)} in questa chat."
            )
            return
        await message.reply_text(
            f"Compleanno salvato per {_target_label(entry)}: {_format_birthday(entry)}."
        )
        return

    if first_lower in _REMOVE_ALIASES:
        if len(args) > 2 or (len(args) == 2 and not args[1].startswith("@")):
            await message.reply_text(_usage_text())
            return
        target = await _resolve_target(update, chat.id, args[1] if len(args) > 1 else None)
        if target is None:
            await message.reply_text(
                "Non riesco a capire il tag indicato. Se usi `@tag`, quella persona deve "
                "essere gia nota in questo gruppo oppure deve impostarsi il compleanno da sola.\n\n"
                + _usage_text(),
            )
            return
        deleted = await delete_birthday(chat.id, target.user_id)
        if not deleted:
            await message.reply_text(
                f"Non trovo nessun compleanno salvato per {_target_label(target)} in questa chat."
            )
            return
        await message.reply_text(
            f"Compleanno rimosso per {_target_label(target)} in questa chat."
        )
        return

    if len(args) == 1:
        target = _self_target(update)
        date_token = args[0]
    elif len(args) == 2 and args[0].startswith("@"):
        target = await _resolve_target_from_username(chat.id, args[0])
        date_token = args[1]
    else:
        await message.reply_text(_usage_text())
        return

    if target is None:
        await message.reply_text(
            "Non riesco a capire il tag indicato. Se usi `@tag`, quella persona deve "
            "essere gia nota in questo gruppo oppure deve impostarsi il compleanno da sola.\n\n"
            + _usage_text(),
        )
        return

    parsed = _parse_birthday_date(date_token)
    if parsed is None:
        await message.reply_text(
            "Data non valida o nel futuro.\n\n" + _usage_text()
        )
        return

    day, month, year = parsed
    entry = await upsert_birthday(
        chat_id=chat.id,
        user_id=target.user_id,
        username=target.username,
        display_name=target.display_name,
        day=day,
        month=month,
        birth_year=year,
    )
    await message.reply_text(
        f"Compleanno aggiunto per {_target_label(entry)} il giorno {_format_birthday(entry)}."
    )


def get_cumpleanno_handlers() -> list[CommandHandler]:
    return [CommandHandler("cumpleanno", handle_cumpleanno)]
