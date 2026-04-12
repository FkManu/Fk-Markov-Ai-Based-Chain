from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from cumbot.access import is_chat_allowed
from cumbot.db.state import (
    get_chat_settings,
    log_generated_message,
    register_chat,
    reset_autopost_cooldown,
)
from cumbot.groq.chat import ask_groq


async def handle_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return
    user_id = update.effective_user.id if update.effective_user else None
    if not is_chat_allowed(chat.id, user_id):
        return

    await register_chat(chat.id, chat.type, chat.title)
    settings = await get_chat_settings(chat.id)

    question = " ".join(context.args).strip()
    if not question:
        await message.reply_text("Uso: /ask <domanda>")
        return

    if settings is not None and not settings.groq_enabled:
        reply = await message.reply_text("Groq e disabilitato in questa chat.")
        await log_generated_message(
            chat_id=chat.id,
            trigger_type="ask",
            groq_enabled=False,
            used_groq=False,
            input_text=question,
            output_text="Groq e disabilitato in questa chat.",
            request_message_id=message.message_id,
            response_message_id=reply.message_id,
            notes="ask_blocked_groq_disabled",
        )
        await reset_autopost_cooldown(chat.id)
        return

    answer = await ask_groq(
        question,
        temperature=settings.groq_temperature if settings is not None else None,
    )
    reply = await message.reply_text(answer)
    await log_generated_message(
        chat_id=chat.id,
        trigger_type="ask",
        groq_enabled=settings.groq_enabled if settings is not None else True,
        used_groq=settings.groq_enabled if settings is not None else True,
        input_text=question,
        output_text=answer,
        request_message_id=message.message_id,
        response_message_id=reply.message_id,
    )
    await reset_autopost_cooldown(chat.id)


def get_ask_handler() -> CommandHandler:
    return CommandHandler("ask", handle_ask)
