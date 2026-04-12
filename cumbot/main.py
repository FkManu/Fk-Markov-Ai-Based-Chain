from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone

from telegram import BotCommand, Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from cumbot.access import is_chat_allowed
from cumbot import config
from cumbot.db.state import init_db, log_gif, log_live_message, log_sticker, register_chat
from cumbot.handlers import (
    get_admin_handlers,
    get_annuncio_handlers,
    get_ask_handler,
    get_cooldown_handler,
    get_mention_handler,
    get_reaction_handler,
    get_setup_handlers,
)
from cumbot.jobs.announcements import send_due_announcements
from cumbot.jobs.retrain import scheduled_retrain
from cumbot.markov.generator import load_models
from cumbot.telegram_context.collector import collector


def _message_text(update: Update) -> str:
    message = update.effective_message
    if message is None:
        return ""
    return (message.text or message.caption or "").strip()


def _message_author(update: Update) -> tuple[int | None, str, str]:
    user = update.effective_user
    if user is None:
        return None, "", "unknown"
    username = user.username or ""
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part).strip()
    display_name = full_name or username or str(user.id)
    return user.id, username, display_name


async def _try_react(bot, chat_id: int, message_id: int, emoji: str) -> None:
    try:
        from telegram import ReactionTypeEmoji

        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception:
        pass


async def context_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return

    user_id, username, display_name = _message_author(update)
    if not is_chat_allowed(chat.id, user_id):
        return

    await register_chat(chat.id, chat.type, chat.title)

    if message.from_user and message.from_user.is_bot:
        return

    if message.animation:
        asyncio.ensure_future(
            log_gif(chat.id, message.animation.file_unique_id, message.animation.file_id)
        )
    if message.sticker and message.sticker.file_unique_id:
        asyncio.ensure_future(
            log_sticker(chat.id, message.sticker.file_unique_id, message.sticker.file_id)
        )

    text = _message_text(update)
    if not text:
        return

    collector.add_message(
        chat.id,
        user_id=user_id,
        username=username,
        display_name=display_name,
        text=text,
    )
    asyncio.ensure_future(log_live_message(chat.id, user_id=user_id, username=username, text=text))
    if config.REACTION_EMOJI and random.random() < config.REACTION_PROBABILITY:
        asyncio.ensure_future(
            _try_react(
                context.bot,
                chat.id,
                message.message_id,
                random.choice(config.REACTION_EMOJI),
            )
        )


_BOT_COMMANDS = [
    BotCommand("ask", "Fai una domanda al bot"),
    BotCommand("setup", "Configura il bot per una chat (admin)"),
    BotCommand("status", "Stato del bot e della chat corrente (admin)"),
    BotCommand("persona", "Imposta la persona attiva (admin)"),
    BotCommand("cooldown", "Imposta il cooldown autopost (admin)"),
    BotCommand("groq", "Abilita/disabilita il refiner LLM (admin)"),
    BotCommand("groqtemp", "Regola la temperatura Groq (admin)"),
    BotCommand("outputs", "Ultimi output generati (admin)"),
    BotCommand("draft", "Draft vs output Groq a confronto (admin)"),
    BotCommand("reactions", "Top messaggi per reaction (admin)"),
    BotCommand("importlive", "Importa un export nel live corpus (admin)"),
    BotCommand("retrain", "Riaddestra il modello Markov (admin)"),
    BotCommand("annuncio", "Gestisci annunci programmati (admin)"),
]


async def post_init(application: Application) -> None:
    await init_db()
    load_models()
    application.bot_data["start_time"] = datetime.now(timezone.utc)
    application.bot_data["retrain_lock"] = asyncio.Lock()
    try:
        await application.bot.set_my_commands(_BOT_COMMANDS)
    except Exception:
        pass  # non blocca l'avvio se il token non ha permessi o è offline


def build_application() -> Application:
    if not config.TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN non configurato.")

    application = Application.builder().token(config.TELEGRAM_TOKEN).post_init(post_init).build()

    application.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, context_middleware),
        group=-1,
    )
    application.add_handler(get_ask_handler())
    for handler in get_admin_handlers():
        application.add_handler(handler)
    for handler in get_setup_handlers():
        application.add_handler(handler)
    for handler in get_annuncio_handlers():
        application.add_handler(handler, group=3)
    application.add_handler(get_mention_handler(), group=1)
    application.add_handler(get_cooldown_handler(), group=2)
    application.add_handler(get_reaction_handler())

    # Job: ogni minuto controlla e invia gli annunci programmati
    if application.job_queue is not None:
        application.job_queue.run_repeating(send_due_announcements, interval=60, first=5)
        # Job: retrain giornaliero per chat — verifica ogni ora, gira solo nella finestra configurata
        application.job_queue.run_repeating(scheduled_retrain, interval=3600, first=60)

    return application


def run() -> None:
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    application = build_application()
    application.run_polling(allowed_updates=Update.ALL_TYPES)
