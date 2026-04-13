from __future__ import annotations

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import CommandHandler, ContextTypes

from cumbot.access import is_chat_allowed
from cumbot.db.state import (
    get_chat_settings,
    log_generated_message,
    register_chat,
    reset_autopost_cooldown,
)
from cumbot.groq.chat import ASK_SYSTEM_PROMPT, ask_groq
from cumbot.groq.conversation_store import ask_store
from cumbot.telegram_utils import split_message


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

    try:
        await chat.send_action(ChatAction.TYPING)
    except Exception:
        pass

    temp = settings.groq_temperature if settings is not None else None
    answer = await ask_groq(question, temperature=temp)

    chunks = split_message(answer)
    first_reply = await message.reply_text(chunks[0])
    for chunk in chunks[1:]:
        await message.reply_text(chunk)

    # Salva la conversazione per eventuali reply di follow-up
    ask_store.set(
        chat_id=chat.id,
        bot_message_id=first_reply.message_id,
        messages=[
            {"role": "system", "content": ASK_SYSTEM_PROMPT},
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ],
    )

    await log_generated_message(
        chat_id=chat.id,
        trigger_type="ask",
        groq_enabled=settings.groq_enabled if settings is not None else True,
        used_groq=settings.groq_enabled if settings is not None else True,
        input_text=question,
        output_text=answer,
        request_message_id=message.message_id,
        response_message_id=first_reply.message_id,
    )
    await reset_autopost_cooldown(chat.id)


def get_ask_handler() -> CommandHandler:
    return CommandHandler("ask", handle_ask)
