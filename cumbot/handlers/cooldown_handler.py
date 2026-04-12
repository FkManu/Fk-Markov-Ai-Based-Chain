from __future__ import annotations

import random

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from cumbot.access import is_chat_allowed
from cumbot import config
from cumbot.db.state import (
    advance_autopost_cooldown,
    count_recent_gifs,
    get_random_gif,
    reset_autopost_cooldown,
)
from cumbot.scheduler import send_autopost_message


def _is_direct_bot_trigger(update: Update, bot_username: str | None, bot_id: int | None) -> bool:
    message = update.effective_message
    if message is None:
        return False

    text = (message.text or message.caption or "").strip()
    username = (bot_username or "").lower()
    has_mention = bool(username and f"@{username}" in text.lower())

    reply = message.reply_to_message
    is_reply_to_bot = bool(
        reply
        and reply.from_user
        and bot_id is not None
        and reply.from_user.id == bot_id
    )
    return has_mention or is_reply_to_bot


async def handle_cooldown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    bot = context.bot
    if message is None or chat is None:
        return
    user_id = update.effective_user.id if update.effective_user else None
    if not is_chat_allowed(chat.id, user_id):
        return
    if chat.type not in {"group", "supergroup"}:
        return
    if message.from_user and message.from_user.is_bot:
        return
    if not any(
        (
            message.text,
            message.caption,
            message.sticker,
            message.photo,
            message.video,
            message.document,
            message.voice,
            message.audio,
            message.animation,
        )
    ):
        return

    if _is_direct_bot_trigger(update, bot.username, bot.id):
        await reset_autopost_cooldown(chat.id)
        return

    triggered, _, _ = await advance_autopost_cooldown(chat.id)
    if not triggered:
        return

    sent = await send_autopost_message(context.application, chat.id)
    if not sent:
        return
    if random.random() < config.GIF_RESEND_PROBABILITY:
        gif_count = await count_recent_gifs(chat.id, config.GIF_CONTEXT_MINUTES)
        if gif_count >= config.GIF_TRIGGER_COUNT:
            gif_file_id = await get_random_gif(chat.id)
            if gif_file_id:
                try:
                    await context.bot.send_animation(chat_id=chat.id, animation=gif_file_id)
                except Exception:
                    pass


def get_cooldown_handler() -> MessageHandler:
    return MessageHandler(filters.ALL & ~filters.COMMAND, handle_cooldown)
