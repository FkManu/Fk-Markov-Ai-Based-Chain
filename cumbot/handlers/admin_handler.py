from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from functools import wraps
from typing import Any

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from cumbot.access import is_chat_allowed
from cumbot import config
from cumbot.db.state import (
    clear_active_persona_ids,
    count_training_corpus_rows,
    get_all_chats,
    get_chat_settings,
    get_chat_training_state,
    get_live_corpus_rows_for_training_corpus,
    get_latest_live_corpus_id,
    get_recent_generated_messages,
    get_training_corpus_for_training,
    get_top_reacted_messages,
    insert_training_corpus_rows,
    register_chat,
    replace_training_corpus_source,
    set_active_persona_ids,
    set_groq_enabled,
    set_groq_temperature,
    set_message_cooldown,
    trim_training_corpus,
    update_chat_training_state,
)
from cumbot.markov.generator import get_model_summary, load_models
from cumbot.markov.trainer import build_training_corpus_import_rows, train_all


CHAT_ID_RE = re.compile(r"-?\d+$")
GROQTEMP_PENDING_KEY = "groqtemp_pending_action"


def admin_only(
    func: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]:
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        message = update.effective_message
        if user is None or user.id not in config.ADMIN_USER_IDS:
            if message is not None:
                await message.reply_text("⛔ Non autorizzato")
            return
        chat = update.effective_chat
        if chat is not None and not is_chat_allowed(chat.id, user.id):
            return
        await func(update, context)

    return wrapper


def _format_uptime(start_time: datetime | None) -> str:
    if start_time is None:
        return "sconosciuto"
    delta = datetime.now(timezone.utc) - start_time
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _looks_like_chat_id(value: str) -> bool:
    return bool(CHAT_ID_RE.fullmatch(value.strip()))


def _parse_explicit_chat_token(value: str) -> int | None:
    token = value.strip()
    if token.startswith("chat:") and _looks_like_chat_id(token[5:]):
        return int(token[5:])
    return None


async def _resolve_target_chat(
    update: Update,
    args: list[str],
) -> tuple[int | None, list[str], str | None]:
    chat = update.effective_chat
    if chat is None:
        return None, args, "Chat non disponibile."

    if chat.type in {"group", "supergroup"}:
        if args:
            explicit_chat_id = _parse_explicit_chat_token(args[0])
            if explicit_chat_id is not None:
                return explicit_chat_id, args[1:], None
        return chat.id, args, None

    if args:
        explicit_chat_id = _parse_explicit_chat_token(args[0])
        if explicit_chat_id is not None:
            return explicit_chat_id, args[1:], None
        if _looks_like_chat_id(args[0]):
            return int(args[0]), args[1:], None
    return None, args, "In chat privata devi specificare il chat_id come primo argomento."


def _parse_persona_ids(raw_values: list[str]) -> list[str]:
    tokens: list[str] = []
    for value in raw_values:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        tokens.extend(parts)
    return [token for token in tokens if token.isdigit()]


def _parse_temperature_arg(raw_value: str) -> float | None:
    try:
        value = float(raw_value.strip().replace(",", "."))
    except ValueError:
        return None
    if value < 0 or value > 2:
        return None
    return round(value, 2)


def _format_temperature(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _groqtemp_usage() -> str:
    return "Uso: /groqtemp [chat:<chat_id>] <0-2 | status | reset>"


def _retrain_usage() -> str:
    return "Uso: /retrain [chat:<chat_id>] [export_path]"


def _importlive_usage() -> str:
    return "Uso: /importlive [chat:<chat_id>] [reset|append] [export_path]"


def _parse_groqtemp_action(raw_value: str | None) -> tuple[str, float | None] | None:
    if raw_value is None or not raw_value.strip():
        return "status", None
    action = raw_value.strip().lower()
    if action == "status":
        return "status", None
    if action == "reset":
        return "set", config.GROQ_REFINER_TEMPERATURE
    temperature = _parse_temperature_arg(action)
    if temperature is None:
        return None
    return "set", temperature


def _make_groqtemp_chat_keyboard(chats) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"{chat.title or chat.chat_id} ({chat.chat_type})",
                    callback_data=f"groqtemp:select:{chat.chat_id}",
                )
            ]
            for chat in chats
        ]
    )


async def _send_groqtemp_chat_picker(
    target,
    *,
    chats,
    requested_action: str,
) -> None:
    if not chats:
        text = "Nessuna chat nota. Aggiungi il bot a un gruppo prima."
        keyboard = None
    else:
        text = (
            "Seleziona la chat su cui applicare `/groqtemp "
            f"{requested_action}`:"
        )
        keyboard = _make_groqtemp_chat_keyboard(chats)

    if hasattr(target, "edit_message_text"):
        await target.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await target.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def _apply_groq_temperature_action(
    *,
    message,
    chat_id: int,
    requested_action: str,
) -> None:
    settings = await get_chat_settings(chat_id)
    if settings is None:
        await message.reply_text("Non conosco ancora quella chat target.")
        return

    parsed_action = _parse_groqtemp_action(requested_action)
    if parsed_action is None:
        await message.reply_text(_groqtemp_usage())
        return

    action_type, value = parsed_action
    if action_type == "status":
        await message.reply_text(
            "Temperatura Groq refiner per "
            f"`{chat_id}`: {_format_temperature(settings.groq_temperature)} "
            f"(default {_format_temperature(config.GROQ_REFINER_TEMPERATURE)})",
            parse_mode="Markdown",
        )
        return

    assert value is not None
    await set_groq_temperature(chat_id, value)
    await message.reply_text(
        "Temperatura Groq refiner aggiornata per "
        f"`{chat_id}`: {_format_temperature(value)}",
        parse_mode="Markdown",
    )


@admin_only
async def handle_persona(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if chat is not None:
        await register_chat(chat.id, chat.type, chat.title)
    chat_id, args, error = await _resolve_target_chat(update, list(context.args))
    if message is None:
        return
    if error:
        await message.reply_text(error)
        return
    if chat_id is None or not args:
        await message.reply_text("Uso: /persona [chat_id] <user_id,user_id... | reset>")
        return

    if args[0].lower() == "reset":
        await clear_active_persona_ids(chat_id)
        await message.reply_text(f"Persona resettata per la chat `{chat_id}`.", parse_mode="Markdown")
        return

    persona_ids = _parse_persona_ids(args)
    if not persona_ids:
        await message.reply_text("Passami uno o piu user_id Telegram validi.")
        return

    target_settings = await get_chat_settings(chat_id)
    if target_settings is None:
        await message.reply_text("Non conosco ancora quella chat target.")
        return

    await set_active_persona_ids(chat_id, persona_ids)
    await message.reply_text(
        f"Persona attiva per `{chat_id}`: {', '.join(persona_ids)}",
        parse_mode="Markdown",
    )


@admin_only
async def handle_cooldown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if chat is not None:
        await register_chat(chat.id, chat.type, chat.title)
    chat_id, args, error = await _resolve_target_chat(update, list(context.args))
    if message is None:
        return
    if error:
        await message.reply_text(error)
        return
    if chat_id is None or not args or not all(arg.isdigit() for arg in args[:2]):
        await message.reply_text("Uso: /cooldown [chat:<chat_id>] <min_messaggi> [max_messaggi]")
        return

    target_settings = await get_chat_settings(chat_id)
    if target_settings is None:
        await message.reply_text("Non conosco ancora quella chat target.")
        return

    lower = max(1, int(args[0]))
    upper = max(lower, int(args[1])) if len(args) > 1 else lower
    await set_message_cooldown(chat_id, lower, upper)
    await message.reply_text(
        f"Cooldown aggiornato per `{chat_id}`: {lower}-{upper} messaggi.",
        parse_mode="Markdown",
    )


@admin_only
async def handle_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_cooldown(update, context)


@admin_only
async def handle_retrain(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None:
        return
    if chat is not None:
        await register_chat(chat.id, chat.type, chat.title)

    chat_id, args, error = await _resolve_target_chat(update, list(context.args))
    if error:
        await message.reply_text(error)
        return
    if chat_id is None:
        await message.reply_text(_retrain_usage())
        return
    if len(args) > 1:
        await message.reply_text(_retrain_usage())
        return
    export_path = args[0] if args else config.EXPORT_PATH

    lock: asyncio.Lock = context.application.bot_data.setdefault("retrain_lock", asyncio.Lock())
    if lock.locked():
        await message.reply_text("Sto gia facendo un retrain, aspetta che finisca.")
        return

    async with lock:
        try:
            training_state = await get_chat_training_state(chat_id)
            pending_live_rows = await get_live_corpus_rows_for_training_corpus(
                chat_id,
                after_id=training_state.last_live_corpus_id if training_state else None,
            )
            consolidated_live = await insert_training_corpus_rows(chat_id, pending_live_rows)
            await trim_training_corpus(chat_id, config.TRAINING_CORPUS_MAX_PER_CHAT)
            training_corpus_count = await count_training_corpus_rows(chat_id)
            base_messages = None
            source_label = None
            if training_corpus_count > 0:
                base_messages = await get_training_corpus_for_training(chat_id)
                source_label = f"training_corpus:{chat_id}"
            stats = await asyncio.to_thread(
                train_all,
                export_path,
                None,
                chat_id,
                base_messages,
                source_label,
            )
            load_models(chat_id=chat_id)
        except FileNotFoundError as exc:
            await message.reply_text(str(exc))
            return
        except Exception as exc:
            await message.reply_text(f"Retrain fallito: {exc}")
            return

        latest_live_corpus_id = await get_latest_live_corpus_id(chat_id)
        training_corpus_size = await count_training_corpus_rows(chat_id)
        update_kwargs = {
            "last_retrain_at": datetime.now(timezone.utc).isoformat(),
            "last_live_corpus_id": latest_live_corpus_id,
            "training_corpus_size": training_corpus_size,
            "models_path": str(config.resolve_models_dir(chat_id)),
        }
        if base_messages is None:
            update_kwargs["last_export_path"] = str(export_path)
        await update_chat_training_state(chat_id, **update_kwargs)

    consolidated_line = f"\nLive consolidati nel training_corpus: +{consolidated_live}"
    base_count = stats.get("base_messages_used")
    source_line = (
        f"\nBase training: {base_count} righe da training_corpus"
        if base_count is not None
        else f"\nBase training: export {export_path}"
    )
    await message.reply_text(
        "Retrain completato.\n"
        f"Chat target: {chat_id}\n"
        f"Export: {export_path}\n"
        f"Messaggi usati: {stats['total_messages']}{source_line}{consolidated_line}\n"
        f"Personas addestrate: {stats['users_trained']}\n"
        f"Skippate: {len(stats['skipped'])}"
    )


@admin_only
async def handle_importlive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None:
        return
    if chat is not None:
        await register_chat(chat.id, chat.type, chat.title)

    chat_id, args, error = await _resolve_target_chat(update, list(context.args))
    if error:
        await message.reply_text(error)
        return
    if chat_id is None:
        await message.reply_text(_importlive_usage())
        return

    mode = "reset"
    export_path = config.EXPORT_PATH
    remaining = list(args)
    if remaining and remaining[0].lower() in {"reset", "append"}:
        mode = remaining[0].lower()
        remaining = remaining[1:]
    if remaining:
        export_path = remaining[0]
        remaining = remaining[1:]
    if remaining:
        await message.reply_text(_importlive_usage())
        return

    try:
        rows = await asyncio.to_thread(build_training_corpus_import_rows, export_path)
    except FileNotFoundError as exc:
        await message.reply_text(str(exc))
        return
    except Exception as exc:
        await message.reply_text(f"Import live fallito: {exc}")
        return

    if mode == "append":
        imported = await insert_training_corpus_rows(chat_id, rows)
    else:
        imported = await replace_training_corpus_source(chat_id, "export", rows)

    await trim_training_corpus(chat_id, config.TRAINING_CORPUS_MAX_PER_CHAT)
    training_corpus_size = await count_training_corpus_rows(chat_id)
    await update_chat_training_state(
        chat_id,
        last_export_path=str(export_path),
        training_corpus_size=training_corpus_size,
    )

    await message.reply_text(
        "Import corpus freddo completato.\n"
        f"Chat target: {chat_id}\n"
        f"Modalita: {mode}\n"
        f"Export: {export_path}\n"
        f"Righe consolidate: {imported}\n"
        f"Training corpus totale: {training_corpus_size}\n"
        "Nota: questo aggiorna il training_corpus (source_kind=export); per i modelli esegui /retrain sulla stessa chat."
    )


async def _handle_llm_toggle(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    command_name: str,
    provider_label: str,
) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None:
        return
    if chat is not None:
        await register_chat(chat.id, chat.type, chat.title)

    chat_id, args, error = await _resolve_target_chat(update, list(context.args))
    if error:
        await message.reply_text(error)
        return
    if chat_id is None:
        await message.reply_text(f"Uso: /{command_name} [chat:<chat_id>] <on|off|status>")
        return

    settings = await get_chat_settings(chat_id)
    if settings is None:
        await message.reply_text("Non conosco ancora quella chat target.")
        return

    if not args or args[0].lower() == "status":
        state_label = "on" if settings.groq_enabled else "off"
        await message.reply_text(
            f"{provider_label} per `{chat_id}`: {state_label}",
            parse_mode="Markdown",
        )
        return

    action = args[0].lower()
    if action not in {"on", "off"}:
        await message.reply_text(f"Uso: /{command_name} [chat:<chat_id>] <on|off|status>")
        return

    enabled = action == "on"
    await set_groq_enabled(chat_id, enabled)
    await message.reply_text(
        f"{provider_label} {'attivato' if enabled else 'disattivato'} per `{chat_id}`.",
        parse_mode="Markdown",
    )


@admin_only
async def handle_groq_temperature(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None:
        return
    if chat is not None:
        await register_chat(chat.id, chat.type, chat.title)

    args = list(context.args)
    if chat is not None and chat.type == "private":
        requested_action = args[0] if args else "status"
        explicit_chat_id = None
        remaining_args = args
        if args:
            parsed_chat_id = _parse_explicit_chat_token(args[0])
            if parsed_chat_id is not None:
                explicit_chat_id = parsed_chat_id
                remaining_args = args[1:]
            elif _looks_like_chat_id(args[0]):
                explicit_chat_id = int(args[0])
                remaining_args = args[1:]

        if explicit_chat_id is None:
            if len(args) > 1:
                await message.reply_text(_groqtemp_usage())
                return
            if _parse_groqtemp_action(requested_action) is None:
                await message.reply_text(_groqtemp_usage())
                return
            context.user_data[GROQTEMP_PENDING_KEY] = requested_action
            await _send_groqtemp_chat_picker(
                message,
                chats=await get_all_chats(),
                requested_action=requested_action,
            )
            return

        if not remaining_args:
            requested_action = "status"
        elif len(remaining_args) == 1:
            requested_action = remaining_args[0]
        else:
            await message.reply_text(_groqtemp_usage())
            return
        await _apply_groq_temperature_action(
            message=message,
            chat_id=explicit_chat_id,
            requested_action=requested_action,
        )
        return

    chat_id, remaining_args, error = await _resolve_target_chat(update, args)
    if error:
        await message.reply_text(error)
        return
    if chat_id is None:
        await message.reply_text(_groqtemp_usage())
        return

    requested_action = remaining_args[0] if remaining_args else "status"
    if len(remaining_args) > 1:
        await message.reply_text(_groqtemp_usage())
        return
    await _apply_groq_temperature_action(
        message=message,
        chat_id=chat_id,
        requested_action=requested_action,
    )


@admin_only
async def handle_groq_temperature_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query: CallbackQuery | None = update.callback_query
    if query is None:
        return
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[0] != "groqtemp" or parts[1] != "select":
        await query.answer()
        return

    await query.answer()
    requested_action = context.user_data.pop(GROQTEMP_PENDING_KEY, "status")
    if _parse_groqtemp_action(requested_action) is None:
        requested_action = "status"
    chat_id = int(parts[2])
    settings = await get_chat_settings(chat_id)
    if settings is None:
        await query.edit_message_text("Chat non trovata.")
        return

    parsed_action = _parse_groqtemp_action(requested_action)
    assert parsed_action is not None
    action_type, value = parsed_action
    if action_type == "status":
        await query.edit_message_text(
            "Temperatura Groq refiner per "
            f"`{chat_id}`: {_format_temperature(settings.groq_temperature)} "
            f"(default {_format_temperature(config.GROQ_REFINER_TEMPERATURE)})",
            parse_mode="Markdown",
        )
        return

    assert value is not None
    await set_groq_temperature(chat_id, value)
    await query.edit_message_text(
        "Temperatura Groq refiner aggiornata per "
        f"`{chat_id}`: {_format_temperature(value)}",
        parse_mode="Markdown",
    )


@admin_only
async def handle_groq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_llm_toggle(
        update,
        context,
        command_name="groq",
        provider_label="Groq",
    )


@admin_only
async def handle_outputs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None:
        return
    if chat is not None:
        await register_chat(chat.id, chat.type, chat.title)

    chat_id, args, error = await _resolve_target_chat(update, list(context.args))
    if error:
        await message.reply_text(error)
        return
    if chat_id is None:
        await message.reply_text("Uso: /outputs [chat:<chat_id>] [limit]")
        return

    limit = 5
    if args:
        if not args[0].isdigit():
            await message.reply_text("Uso: /outputs [chat:<chat_id>] [limit]")
            return
        limit = int(args[0])

    records = await get_recent_generated_messages(chat_id=chat_id, limit=limit)
    if not records:
        await message.reply_text("Nessun output monitorato per questa chat.")
        return

    lines = [f"Ultimi output per {chat_id}:"]
    for record in records:
        preview = (record.output_text or "").replace("\n", " ").strip()
        if len(preview) > 80:
            preview = preview[:77].rstrip() + "..."
        personas = ",".join(record.persona_ids) if record.persona_ids else "global"
        lines.append(
            f"#{record.id} | {record.trigger_type} | llm={'on' if record.used_groq else 'off'} | react={record.reaction_count} | persona={personas}"
        )
        lines.append(preview or "(vuoto)")

    await message.reply_text("\n".join(lines))


@admin_only
async def handle_draft(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None:
        return
    if chat is not None:
        await register_chat(chat.id, chat.type, chat.title)

    chat_id, args, error = await _resolve_target_chat(update, list(context.args))
    if error:
        await message.reply_text(error)
        return
    if chat_id is None:
        await message.reply_text("Uso: /draft [chat:<chat_id>] [limit]")
        return

    limit = 5
    if args:
        if not args[0].isdigit():
            await message.reply_text("Uso: /draft [chat:<chat_id>] [limit]")
            return
        limit = int(args[0])

    records = await get_recent_generated_messages(chat_id=chat_id, limit=limit)
    if not records:
        await message.reply_text("Nessun output monitorato per questa chat.")
        return

    lines = [f"Draft vs output per {chat_id}:"]
    for record in records:
        draft = (record.draft_text or "").replace("\n", " ").strip()
        output = (record.output_text or "").replace("\n", " ").strip()
        modified = draft.lower().strip() != output.lower().strip()
        flag = " ✏️" if modified else ""
        lines.append(f"#{record.id} [{record.trigger_type}] llm={'on' if record.used_groq else 'off'}{flag}")
        lines.append(f"  D: {draft[:100] or '(vuoto)'}")
        if modified:
            lines.append(f"  O: {output[:100] or '(vuoto)'}")

    await message.reply_text("\n".join(lines))


@admin_only
async def handle_reactions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None:
        return
    if chat is not None:
        await register_chat(chat.id, chat.type, chat.title)

    chat_id, args, error = await _resolve_target_chat(update, list(context.args))
    if error:
        await message.reply_text(error)
        return
    if chat_id is None:
        await message.reply_text("Uso: /reactions [chat:<chat_id>] [limit]")
        return

    limit = 5
    if args:
        if not args[0].isdigit():
            await message.reply_text("Uso: /reactions [chat:<chat_id>] [limit]")
            return
        limit = int(args[0])

    records = await get_top_reacted_messages(chat_id=chat_id, limit=limit)
    if not records:
        await message.reply_text("Nessun output con reaction per questa chat.")
        return

    lines = [f"Top reaction per {chat_id}:"]
    for record in records:
        preview = (record.output_text or "").replace("\n", " ").strip()
        if len(preview) > 80:
            preview = preview[:77].rstrip() + "..."
        lines.append(f"#{record.id} | react={record.reaction_count} | {record.trigger_type}")
        lines.append(preview or "(vuoto)")

    await message.reply_text("\n".join(lines))


@admin_only
async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None:
        return
    if chat is not None:
        await register_chat(chat.id, chat.type, chat.title)

    start_time: datetime | None = context.application.bot_data.get("start_time")

    chat_id, args, error = await _resolve_target_chat(update, list(context.args))
    if update.effective_chat and update.effective_chat.type == "private" and not context.args:
        model_summary = get_model_summary()
        chats = await get_all_chats()
        lines = [
            "Stato globale:",
            f"Uptime: {_format_uptime(start_time)}",
            f"Modelli caricati: {model_summary['loaded_total']}",
            f"Chat note: {len(chats)}",
        ]
        for chat in chats[:10]:
            personas = ", ".join(chat.active_persona_ids) if chat.active_persona_ids else "globale"
            lines.append(
                f"{chat.chat_id} | {chat.chat_type} | cooldown={chat.messages_since_bot}/{chat.next_autopost_after} ({chat.cooldown_min_messages}-{chat.cooldown_max_messages}) | groq={'on' if chat.groq_enabled else 'off'} | temp={_format_temperature(chat.groq_temperature)} | persona={personas}"
            )
        await message.reply_text("\n".join(lines))
        return

    if error:
        await message.reply_text(error)
        return

    settings = await get_chat_settings(chat_id) if chat_id is not None else None
    if settings is None:
        await message.reply_text("Non conosco ancora quella chat.")
        return

    model_summary = get_model_summary(chat_id=chat_id)
    training_state = await get_chat_training_state(chat_id)
    personas = ", ".join(settings.active_persona_ids) if settings.active_persona_ids else "globale"
    lines = [
        "Stato chat:",
        f"chat_id: {settings.chat_id}",
        f"tipo: {settings.chat_type}",
        f"persona: {personas}",
        f"cooldown: {settings.messages_since_bot}/{settings.next_autopost_after}",
        f"range cooldown: {settings.cooldown_min_messages}-{settings.cooldown_max_messages} messaggi",
        f"groq: {'on' if settings.groq_enabled else 'off'}",
        f"groq temp: {_format_temperature(settings.groq_temperature)}",
        f"modelli caricati: {model_summary['loaded_total']}",
        f"namespace modelli: {model_summary['models_dir']}",
    ]
    if training_state is not None:
        lines.append(f"ultimo retrain: {training_state.last_retrain_at or 'mai'}")
        lines.append(f"ultimo export: {training_state.last_export_path or 'n/d'}")
    lines.append(f"uptime: {_format_uptime(start_time)}")
    await message.reply_text("\n".join(lines))


def get_admin_handlers() -> list[Any]:
    return [
        CommandHandler("persona", handle_persona),
        CommandHandler("cooldown", handle_cooldown),
        CommandHandler("interval", handle_interval),
        CommandHandler("groq", handle_groq),
        CommandHandler("groqtemp", handle_groq_temperature),
        CommandHandler("outputs", handle_outputs),
        CommandHandler("draft", handle_draft),
        CommandHandler("reactions", handle_reactions),
        CommandHandler("importlive", handle_importlive),
        CommandHandler("retrain", handle_retrain),
        CommandHandler("status", handle_status),
        CallbackQueryHandler(handle_groq_temperature_callback, pattern=r"^groqtemp:"),
    ]
