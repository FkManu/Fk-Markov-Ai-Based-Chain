from __future__ import annotations

import zoneinfo

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from cumbot import config
from cumbot.db.state import (
    Announcement,
    create_announcement,
    delete_announcement,
    get_all_chats,
    get_announcement,
    get_announcements,
    get_chat_settings,
    toggle_announcement,
    update_announcement,
)
from cumbot.handlers.admin_handler import admin_only


# user_data key usato per lo stato di attesa testo annuncio
_PENDING_KEY = "annuncio_pending"


# ---------------------------------------------------------------------------
# Helpers UI
# ---------------------------------------------------------------------------

def _tz() -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(config.ANNOUNCEMENT_TIMEZONE)
    except Exception:
        return zoneinfo.ZoneInfo("Europe/Rome")


def _tz_label() -> str:
    try:
        return _tz().key
    except Exception:
        return "Europe/Rome"


def _fmt_time(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _ann_label(ann: Announcement) -> str:
    status = "✅" if ann.enabled else "⏸"
    preview = ann.text[:30].replace("\n", " ")
    if len(ann.text) > 30:
        preview += "…"
    return f"{status} {_fmt_time(ann.hour, ann.minute)} — {preview}"


async def _safe_edit(query: CallbackQuery, text: str, **kwargs) -> None:
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def _make_chat_list_keyboard(chats) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"{chat.title or chat.chat_id} ({chat.chat_type})",
                    callback_data=f"ann:list:{chat.chat_id}",
                )
            ]
            for chat in chats
        ]
    )


def _make_announcement_list_keyboard(chat_id: int, announcements: list[Announcement]) -> InlineKeyboardMarkup:
    rows = []
    for ann in announcements:
        rows.append([
            InlineKeyboardButton(_ann_label(ann), callback_data=f"ann:view:{ann.id}"),
        ])
    rows.append([InlineKeyboardButton("➕ Nuovo annuncio", callback_data=f"ann:new:{chat_id}")])
    rows.append([InlineKeyboardButton("🔙 Indietro", callback_data="ann:chats")])
    return InlineKeyboardMarkup(rows)


def _make_announcement_view_keyboard(ann: Announcement) -> InlineKeyboardMarkup:
    toggle_label = "⏸ Disabilita" if ann.enabled else "▶️ Abilita"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=f"ann:toggle:{ann.id}")],
        [InlineKeyboardButton("✏️ Modifica testo", callback_data=f"ann:edit_text:{ann.id}")],
        [InlineKeyboardButton("🕐 Modifica orario", callback_data=f"ann:edit_time:{ann.id}")],
        [InlineKeyboardButton("🗑 Elimina", callback_data=f"ann:delete_confirm:{ann.id}")],
        [InlineKeyboardButton("🔙 Indietro", callback_data=f"ann:list:{ann.chat_id}")],
    ])


_TIME_PRESETS = [
    ("00:00", 0, 0),
    ("01:00", 1, 0),
    ("02:00", 2, 0),
    ("03:00", 3, 0),
    ("04:00", 4, 0),
    ("05:00", 5, 0),
    ("06:00", 6, 0),
    ("07:00", 7, 0),
    ("08:00", 8, 0),
    ("09:00", 9, 0),
    ("10:00", 10, 0),
    ("11:00", 11, 0),   
    ("12:00", 12, 0),
    ("13:00", 13, 0),
    ("14:00", 14, 0),
    ("15:00", 15, 0),
    ("16:00", 16, 0),
    ("17:00", 17, 0),
    ("18:00", 18, 0),
    ("19:00", 19, 0),
    ("20:00", 20, 0),
    ("21:00", 21, 0),
    ("22:00", 22, 0),
    ("23:00", 23, 0),
]


def _make_time_keyboard(chat_id: int, back_callback: str) -> InlineKeyboardMarkup:
    rows = []
    row: list[InlineKeyboardButton] = []
    for label, h, m in _TIME_PRESETS:
        row.append(InlineKeyboardButton(label, callback_data=f"ann:time:{chat_id}:{h}:{m}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 Indietro", callback_data=back_callback)])
    return InlineKeyboardMarkup(rows)


def _make_edit_time_keyboard(ann_id: int) -> InlineKeyboardMarkup:
    rows = []
    row: list[InlineKeyboardButton] = []
    for label, h, m in _TIME_PRESETS:
        row.append(InlineKeyboardButton(label, callback_data=f"ann:set_time:{ann_id}:{h}:{m}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 Indietro", callback_data=f"ann:view:{ann_id}")])
    return InlineKeyboardMarkup(rows)


def _make_delete_confirm_keyboard(ann_id: int, chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Sì, elimina", callback_data=f"ann:delete:{ann_id}:{chat_id}"),
            InlineKeyboardButton("❌ No", callback_data=f"ann:view:{ann_id}"),
        ]
    ])


# ---------------------------------------------------------------------------
# Text formatters
# ---------------------------------------------------------------------------

def _chat_list_text() -> str:
    return f"Seleziona la chat per cui gestire gli annunci. Orari in timezone italiana ({_tz_label()}):"


def _ann_list_text(chat_id: int, title: str | None, announcements: list[Announcement]) -> str:
    header = f"Annunci per {title or chat_id} ({_tz_label()}):"
    if not announcements:
        return f"{header}\n\nNessun annuncio configurato."
    lines = [header, ""]
    for ann in announcements:
        status = "✅ attivo" if ann.enabled else "⏸ disabilitato"
        lines.append(f"• {_fmt_time(ann.hour, ann.minute)} — {status}")
    return "\n".join(lines)


def _ann_view_text(ann: Announcement) -> str:
    status = "✅ abilitato" if ann.enabled else "⏸ disabilitato"
    return (
        f"Annuncio #{ann.id}\n"
        f"Orario: {_fmt_time(ann.hour, ann.minute)} ({_tz_label()}, ora italiana)\n"
        f"Stato: {status}\n\n"
        f"Testo:\n{ann.text}"
    )


# ---------------------------------------------------------------------------
# Entry command
# ---------------------------------------------------------------------------

@admin_only
async def handle_annuncio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return

    if chat.type != "private":
        # In gruppo: vai direttamente alla lista annunci per questa chat
        announcements = await get_announcements(chat.id)
        settings = await get_chat_settings(chat.id)
        title = settings.title if settings else None
        keyboard = _make_announcement_list_keyboard(chat.id, announcements)
        await message.reply_text(_ann_list_text(chat.id, title, announcements), reply_markup=keyboard)
    else:
        # In privato: mostra la lista delle chat note
        chats = await get_all_chats()
        if not chats:
            await message.reply_text("Nessuna chat nota. Aggiungi prima il bot a un gruppo.")
            return
        await message.reply_text(_chat_list_text(), reply_markup=_make_chat_list_keyboard(chats))


# ---------------------------------------------------------------------------
# Callback dispatcher
# ---------------------------------------------------------------------------

@admin_only
async def handle_annuncio_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query: CallbackQuery | None = update.callback_query
    if query is None:
        return
    raw = query.data or ""
    parts = raw.split(":")
    if len(parts) < 2 or parts[0] != "ann":
        await query.answer()
        return

    action = parts[1]

    # --- Chat list ---
    if action == "chats":
        await query.answer()
        chats = await get_all_chats()
        if not chats:
            await _safe_edit(query, "Nessuna chat nota.")
            return
        await _safe_edit(query, _chat_list_text(), reply_markup=_make_chat_list_keyboard(chats))
        return

    # --- Announcement list for a chat ---
    if action == "list" and len(parts) >= 3:
        await query.answer()
        chat_id = int(parts[2])
        settings = await get_chat_settings(chat_id)
        title = settings.title if settings else None
        announcements = await get_announcements(chat_id)
        keyboard = _make_announcement_list_keyboard(chat_id, announcements)
        await _safe_edit(query, _ann_list_text(chat_id, title, announcements), reply_markup=keyboard)
        return

    # --- View announcement detail ---
    if action == "view" and len(parts) >= 3:
        await query.answer()
        ann_id = int(parts[2])
        ann = await get_announcement(ann_id)
        if ann is None:
            await _safe_edit(query, "Annuncio non trovato.")
            return
        await _safe_edit(query, _ann_view_text(ann), reply_markup=_make_announcement_view_keyboard(ann))
        return

    # --- Toggle enable/disable ---
    if action == "toggle" and len(parts) >= 3:
        await query.answer()
        ann_id = int(parts[2])
        ann = await toggle_announcement(ann_id)
        if ann is None:
            await _safe_edit(query, "Annuncio non trovato.")
            return
        await _safe_edit(query, _ann_view_text(ann), reply_markup=_make_announcement_view_keyboard(ann))
        return

    # --- New announcement: pick time ---
    if action == "new" and len(parts) >= 3:
        await query.answer()
        chat_id = int(parts[2])
        await _safe_edit(
            query,
            f"Seleziona l'orario per il nuovo annuncio ({_tz_label()}, ora italiana):",
            reply_markup=_make_time_keyboard(chat_id, back_callback=f"ann:list:{chat_id}"),
        )
        return

    # --- New announcement: time selected, ask for text ---
    if action == "time" and len(parts) >= 5:
        await query.answer()
        chat_id = int(parts[2])
        hour = int(parts[3])
        minute = int(parts[4])
        # Store pending state
        if context.user_data is None:
            await _safe_edit(query, "Errore interno: user_data non disponibile.")
            return
        context.user_data[_PENDING_KEY] = {
            "chat_id": chat_id,
            "hour": hour,
            "minute": minute,
            "mode": "create",
        }
        await _safe_edit(
            query,
            f"Orario selezionato: {_fmt_time(hour, minute)} ({_tz_label()}, ora italiana)\n\nInvia ora il testo dell'annuncio:",
        )
        return

    # --- Edit time for existing announcement ---
    if action == "edit_time" and len(parts) >= 3:
        await query.answer()
        ann_id = int(parts[2])
        ann = await get_announcement(ann_id)
        if ann is None:
            await _safe_edit(query, "Annuncio non trovato.")
            return
        await _safe_edit(
            query,
            f"Annuncio #{ann_id} — seleziona il nuovo orario ({_tz_label()}, ora italiana):",
            reply_markup=_make_edit_time_keyboard(ann_id),
        )
        return

    # --- Set time for existing announcement ---
    if action == "set_time" and len(parts) >= 5:
        await query.answer()
        ann_id = int(parts[2])
        hour = int(parts[3])
        minute = int(parts[4])
        ann = await update_announcement(ann_id, hour=hour, minute=minute)
        if ann is None:
            await _safe_edit(query, "Annuncio non trovato.")
            return
        await _safe_edit(query, _ann_view_text(ann), reply_markup=_make_announcement_view_keyboard(ann))
        return

    # --- Edit text for existing announcement ---
    if action == "edit_text" and len(parts) >= 3:
        await query.answer()
        ann_id = int(parts[2])
        ann = await get_announcement(ann_id)
        if ann is None:
            await _safe_edit(query, "Annuncio non trovato.")
            return
        if context.user_data is None:
            await _safe_edit(query, "Errore interno: user_data non disponibile.")
            return
        context.user_data[_PENDING_KEY] = {
            "ann_id": ann_id,
            "mode": "edit_text",
        }
        await _safe_edit(query, f"Annuncio #{ann_id} — invia il nuovo testo:")
        return

    # --- Delete confirm dialog ---
    if action == "delete_confirm" and len(parts) >= 3:
        await query.answer()
        ann_id = int(parts[2])
        ann = await get_announcement(ann_id)
        if ann is None:
            await _safe_edit(query, "Annuncio non trovato.")
            return
        await _safe_edit(
            query,
            f"Confermi l'eliminazione dell'annuncio #{ann_id} ({_fmt_time(ann.hour, ann.minute)})?",
            reply_markup=_make_delete_confirm_keyboard(ann_id, ann.chat_id),
        )
        return

    # --- Delete confirmed ---
    if action == "delete" and len(parts) >= 4:
        await query.answer()
        ann_id = int(parts[2])
        chat_id = int(parts[3])
        await delete_announcement(ann_id)
        settings = await get_chat_settings(chat_id)
        title = settings.title if settings else None
        announcements = await get_announcements(chat_id)
        keyboard = _make_announcement_list_keyboard(chat_id, announcements)
        await _safe_edit(query, _ann_list_text(chat_id, title, announcements), reply_markup=keyboard)
        return

    await query.answer()


# ---------------------------------------------------------------------------
# Text input handler (pending state)
# ---------------------------------------------------------------------------

@admin_only
async def handle_annuncio_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Intercepts plain text messages when the admin has a pending /annuncio action."""
    if context.user_data is None:
        return
    pending = context.user_data.get(_PENDING_KEY)
    if not pending:
        return

    message = update.effective_message
    if message is None:
        return

    text = (message.text or "").strip()
    if not text:
        await message.reply_text("Il testo non può essere vuoto. Riprova:")
        return

    mode = pending.get("mode")

    if mode == "create":
        chat_id = pending["chat_id"]
        hour = pending["hour"]
        minute = pending["minute"]
        del context.user_data[_PENDING_KEY]

        ann = await create_announcement(chat_id, text, hour, minute)
        settings = await get_chat_settings(chat_id)
        title = settings.title if settings else None
        announcements = await get_announcements(chat_id)
        keyboard = _make_announcement_list_keyboard(chat_id, announcements)
        await message.reply_text(
            f"✅ Annuncio #{ann.id} creato per {title or chat_id} alle {_fmt_time(hour, minute)} ({_tz_label()}, ora italiana).",
            reply_markup=keyboard,
        )

    elif mode == "edit_text":
        ann_id = pending["ann_id"]
        del context.user_data[_PENDING_KEY]

        ann = await update_announcement(ann_id, text=text)
        if ann is None:
            await message.reply_text("Annuncio non trovato.")
            return
        await message.reply_text(
            f"✅ Testo aggiornato.",
            reply_markup=_make_announcement_view_keyboard(ann),
        )


# ---------------------------------------------------------------------------
# Handler registration
# ---------------------------------------------------------------------------

def get_annuncio_handlers() -> list:
    return [
        CommandHandler("annuncio", handle_annuncio),
        CallbackQueryHandler(handle_annuncio_callback, pattern=r"^ann:"),
        # Only handle plain non-command text when user has pending state.
        # This runs at group 3 (after cooldown) to avoid conflict with mention handler.
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            handle_annuncio_text_input,
        ),
    ]
