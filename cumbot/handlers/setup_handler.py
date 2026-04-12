from __future__ import annotations

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from cumbot.db.state import (
    clear_active_persona_ids,
    get_all_chats,
    get_chat_settings,
    register_chat,
    set_groq_enabled,
    set_message_cooldown,
)
from cumbot.handlers.admin_handler import admin_only
from cumbot.handlers.admin_handler import _format_temperature


def _settings_text(settings) -> str:
    personas = ", ".join(settings.active_persona_ids) if settings.active_persona_ids else "globale"
    groq_state = "on" if settings.groq_enabled else "off"
    return (
        f"Configurazione chat: {settings.title or settings.chat_id}\n"
        f"Groq: {groq_state}\n"
        f"Temp: {_format_temperature(settings.groq_temperature)}\n"
        f"Persona: {personas}\n"
        f"Cooldown: {settings.cooldown_min_messages}-{settings.cooldown_max_messages} msg"
    )


def _make_main_keyboard(settings, chat_id: int) -> InlineKeyboardMarkup:
    groq_label = "Groq ON" if settings.groq_enabled else "Groq OFF"
    groq_toggle = "off" if settings.groq_enabled else "on"
    persona_label = (
        f"Persona: {', '.join(settings.active_persona_ids)}"
        if settings.active_persona_ids
        else "Persona globale"
    )
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(groq_label, callback_data=f"setup:groq_{groq_toggle}:{chat_id}")],
            [InlineKeyboardButton(persona_label, callback_data=f"setup:persona_info:{chat_id}")],
            [InlineKeyboardButton("Reset persona", callback_data=f"setup:persona_reset:{chat_id}")],
            [
                InlineKeyboardButton(
                    f"Cooldown: {settings.cooldown_min_messages}-{settings.cooldown_max_messages}",
                    callback_data=f"setup:cooldown_menu:{chat_id}",
                )
            ],
            [InlineKeyboardButton("Refresh", callback_data=f"setup:select:{chat_id}")],
            [InlineKeyboardButton("Indietro", callback_data="setup:list")],
        ]
    )


def _make_cooldown_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    presets = [("5-10 msg", "5_10"), ("20-30 msg", "20_30"), ("40-60 msg", "40_60"), ("80-100 msg", "80_100")]
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data=f"setup:cooldown:{chat_id}:{value}")]
            for label, value in presets
        ]
        + [[InlineKeyboardButton("Indietro", callback_data=f"setup:select:{chat_id}")]]
    )


async def _send_chat_list(target, chats) -> None:
    if not chats:
        text = "Nessuna chat nota. Aggiungi il bot a un gruppo prima."
        keyboard = None
    else:
        text = "Seleziona la chat da configurare:"
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"{chat.title or chat.chat_id} ({chat.chat_type})",
                        callback_data=f"setup:select:{chat.chat_id}",
                    )
                ]
                for chat in chats
            ]
        )

    if hasattr(target, "edit_message_text"):
        await target.edit_message_text(text, reply_markup=keyboard)
    else:
        await target.reply_text(text, reply_markup=keyboard)


@admin_only
async def handle_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return
    if chat.type != "private":
        await register_chat(chat.id, chat.type, chat.title)
    await _send_chat_list(message, await get_all_chats())


async def _safe_edit(query: CallbackQuery, text: str, **kwargs) -> None:
    """Edit message ignorando 'Message is not modified' (doppio click, refresh senza variazioni)."""
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


@admin_only
async def handle_setup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query: CallbackQuery | None = update.callback_query
    if query is None:
        return
    raw = query.data or ""
    parts = raw.split(":")
    if len(parts) < 2 or parts[0] != "setup":
        await query.answer()
        return

    action = parts[1]

    # persona_info: mostra popup senza editare il messaggio (evita "not modified")
    if action == "persona_info" and len(parts) >= 3:
        chat_id = int(parts[2])
        settings = await get_chat_settings(chat_id)
        personas = ", ".join(settings.active_persona_ids) if (settings and settings.active_persona_ids) else "globale"
        await query.answer(f"Persona attiva: {personas}\n/persona per cambiarla.", show_alert=True)
        return

    await query.answer()

    if action == "list":
        await _send_chat_list(query, await get_all_chats())
        return

    if action.startswith("groq_") and len(parts) >= 3:
        chat_id = int(parts[2])
        await set_groq_enabled(chat_id, action.endswith("on"))
        settings = await get_chat_settings(chat_id)
        if settings is None:
            await query.edit_message_text("Chat non trovata.")
            return
        await _safe_edit(query, _settings_text(settings), reply_markup=_make_main_keyboard(settings, chat_id))
        return

    if action == "select" and len(parts) >= 3:
        chat_id = int(parts[2])
        settings = await get_chat_settings(chat_id)
        if settings is None:
            await query.edit_message_text("Chat non trovata.")
            return
        await _safe_edit(query, _settings_text(settings), reply_markup=_make_main_keyboard(settings, chat_id))
        return

    if action == "persona_reset" and len(parts) >= 3:
        chat_id = int(parts[2])
        await clear_active_persona_ids(chat_id)
        settings = await get_chat_settings(chat_id)
        if settings is None:
            await query.edit_message_text("Chat non trovata.")
            return
        await _safe_edit(query, _settings_text(settings), reply_markup=_make_main_keyboard(settings, chat_id))
        return

    if action == "cooldown_menu" and len(parts) >= 3:
        chat_id = int(parts[2])
        settings = await get_chat_settings(chat_id)
        if settings is None:
            await query.edit_message_text("Chat non trovata.")
            return
        await _safe_edit(query, _settings_text(settings), reply_markup=_make_cooldown_keyboard(chat_id))
        return

    if action == "cooldown" and len(parts) >= 4:
        chat_id = int(parts[2])
        try:
            lower, upper = [int(value) for value in parts[3].split("_", 1)]
        except ValueError:
            await query.edit_message_text("Preset cooldown non valido.")
            return
        await set_message_cooldown(chat_id, lower, upper)
        settings = await get_chat_settings(chat_id)
        if settings is None:
            await query.edit_message_text("Chat non trovata.")
            return
        await _safe_edit(query, _settings_text(settings), reply_markup=_make_main_keyboard(settings, chat_id))


def get_setup_handlers() -> list:
    return [
        CommandHandler("setup", handle_setup),
        CallbackQueryHandler(handle_setup_callback, pattern=r"^setup:"),
    ]
