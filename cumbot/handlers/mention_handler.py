from __future__ import annotations

import asyncio
import random

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from cumbot.announcement_store import announcement_store
from cumbot.access import is_chat_allowed
from cumbot.db.state import (
    count_recent_gifs,
    get_chat_settings,
    get_random_gif,
    get_random_sticker,
    get_live_messages,
    log_generated_message,
    register_chat,
    reset_autopost_cooldown,
)
from telegram.constants import ChatAction

from cumbot.groq.chat import ask_groq_conversation
from cumbot.groq.classifier import classify_intent
from cumbot.groq.conversation_store import ask_store
from cumbot.groq.refiner import refine_draft
from cumbot.markov.generator import generate_draft
from cumbot import config
from cumbot.telegram_utils import split_message
from cumbot.markov.intent import (
    BotAction,
    QUESTION_SEEDS,
    detect_action,
    detect_question_type,
    extract_seeds_from_input,
    extract_topic_seeds,
    get_context_names,
)
from cumbot.markov.tone import TONE_SEEDS, detect_tone
from cumbot.markov.rendering import (
    build_mention_candidates,
    materialize_placeholder_labels,
    polish_generated_text,
    resolve_placeholder_mentions,
)
from cumbot.telegram_context.collector import collector


INTENT_SEEDS: dict[str, list[str]] = {
    "roast": ["coglione", "cazzo", "idiota", "inutile", "basta", "stronzo"],
    "reaction": ["godo", "minchia", "porcodio", "crazy", "assurdo", "wow"],
    "agreement": ["esatto", "giusto", "vero", "certo", "ci", "sta"],
}

INTENT_TONES: dict[str, str] = {
    "roast": "aggressive",
}

# Risposte brevi fisse per reazioni emotive (≤2 parole, bypassa Markov)
REACTION_SHORT_RESPONSES: list[str] = [
    "ok",
    "ci sta",
    "sei un grande",
    "bravo",
    "giusto",
    "diglielo",
    "vabbè",
    "eh sì",
    "esatto",
    "ah beh",
    "certo",
    "ovvio",
    "chiaro",
    "maddai",
    "ma va",
    "dai su",
    "tranquillo",
    "ok dai",
    "ma certo",
    "chiaro che sì",
    "non ci sono dubbi",
    "hai ragione",
    "dici bene",
    "confermo",
]


async def _handle_action(
    action: BotAction,
    message,
    chat_id: int,
    recent_context: list[dict],
    persona_ids: list[str],
    settings,
    groq_enabled: bool,
    live_texts: list[str],
    bot,
) -> bool:
    """Gestisce un comando d'azione esplicito.

    Ritorna True se l'azione è stata eseguita (il chiamante deve fare return),
    False se non c'è corpus disponibile e si deve fallback alla generazione normale.
    """
    if action.type == "gif":
        gif_file_id = await get_random_gif(chat_id)
        if gif_file_id:
            try:
                await message.reply_animation(animation=gif_file_id)
            except Exception:
                pass
            return True
        # Nessuna GIF in corpus: fallback a testo
        return False

    if action.type == "sticker":
        sticker_file_id = await get_random_sticker(chat_id)
        if sticker_file_id:
            try:
                await message.reply_sticker(sticker=sticker_file_id)
            except Exception:
                pass
            return True
        return False

    if action.type == "insulta":
        # Seed: nome del target + parole aggressive
        insult_seeds = ["coglione", "idiota", "scemo", "sfigato", "pezzo", "merda"]
        target_words = action.target.split() if action.target else []
        seed_words = target_words + insult_seeds

        draft = generate_draft(
            persona_ids=persona_ids,
            live_texts=live_texts or None,
            seed_words=seed_words,
            chat_id=chat_id,
        )
        if groq_enabled:
            output = await refine_draft(
                draft=draft,
                recent_context=recent_context,
                persona_ids=persona_ids,
                tone="aggressive",
                temperature=settings.groq_temperature if settings is not None else None,
            )
        else:
            output = draft
        output = polish_generated_text(output)

        trigger_user = None
        if message.from_user and not message.from_user.is_bot:
            trigger_user = {
                "user_id": message.from_user.id,
                "username": message.from_user.username or "",
                "display_name": message.from_user.full_name or message.from_user.username or str(message.from_user.id),
            }
        mention_candidates = build_mention_candidates(
            trigger_user=trigger_user,
            recent_context=recent_context,
            exclude_user_ids={bot.id} if bot.id is not None else set(),
        )
        rendered_output, parse_mode = resolve_placeholder_mentions(output, mention_candidates)
        await message.reply_text(rendered_output, parse_mode=parse_mode)
        return True

    return False


def _is_triggered(update: Update, bot_username: str | None, bot_id: int | None) -> bool:
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
    if (
        is_reply_to_bot
        and reply is not None
        and announcement_store.is_announcement(update.effective_chat.id, reply.message_id)
    ):
        return has_mention
    return has_mention or is_reply_to_bot


async def handle_mention(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    bot = context.bot
    if message is None or chat is None:
        return
    user_id = update.effective_user.id if update.effective_user else None
    if not is_chat_allowed(chat.id, user_id):
        return

    if not _is_triggered(update, bot.username, bot.id):
        return

    await register_chat(chat.id, chat.type, chat.title)
    settings = await get_chat_settings(chat.id)
    persona_ids = settings.active_persona_ids if settings else []
    groq_enabled = settings.groq_enabled if settings else True

    recent_context = collector.get_recent(chat.id)
    live_texts = await get_live_messages(chat.id, limit=config.LIVE_CORPUS_LIMIT)

    input_text = (message.text or message.caption or "").strip()

    # Continuazione conversazione /ask: se è un reply ad un messaggio bot
    # che faceva parte di una sessione /ask, continua con Groq multi-turn.
    reply_to = message.reply_to_message
    if (
        reply_to is not None
        and reply_to.from_user is not None
        and reply_to.from_user.id == bot.id
    ):
        history = ask_store.get(chat.id, reply_to.message_id)
        if history is not None:
            # Rimuovi @mention dal testo utente prima di aggiungerlo alla storia
            import re as _re
            clean_input = _re.sub(
                rf"@{_re.escape(bot.username or '')}\b", "", input_text, flags=_re.IGNORECASE
            ).strip() or input_text
            try:
                await chat.send_action(ChatAction.TYPING)
            except Exception:
                pass
            temp = settings.groq_temperature if settings is not None else None
            answer, updated_history = await ask_groq_conversation(
                history=history,
                new_user_message=clean_input,
                temperature=temp,
            )
            chunks = split_message(answer)
            first_reply = await message.reply_text(chunks[0])
            for chunk in chunks[1:]:
                await message.reply_text(chunk)
            # Salva la storia aggiornata sotto il nuovo message_id del bot
            ask_store.set(chat.id, first_reply.message_id, updated_history)
            await log_generated_message(
                chat_id=chat.id,
                trigger_type="ask",
                groq_enabled=groq_enabled,
                used_groq=groq_enabled,
                input_text=input_text,
                draft_text=None,
                output_text=answer,
                recent_context=recent_context,
                request_message_id=message.message_id,
                response_message_id=first_reply.message_id,
                notes="ask_continuation",
            )
            await reset_autopost_cooldown(chat.id)
            return

    # Rilevamento azione esplicita (gif / sticker / insulta)
    action = detect_action(input_text, bot_username=bot.username or "")
    if action is not None:
        handled = await _handle_action(
            action=action,
            message=message,
            chat_id=chat.id,
            recent_context=recent_context,
            persona_ids=persona_ids,
            settings=settings,
            groq_enabled=groq_enabled,
            live_texts=live_texts,
            bot=bot,
        )
        if handled:
            await reset_autopost_cooldown(chat.id)
            return
        # Se l'azione non ha trovato corpus (es. gif corpus vuoto) → continua con testo normale

    # Contesto immediato: ultimi N messaggi per topic extraction
    immediate_context = recent_context[-config.IMMEDIATE_CONTEXT_SIZE:]

    question_type = detect_question_type(input_text)
    tone = detect_tone(recent_context, input_text=input_text)
    classify_task: asyncio.Task[str] | None = None
    if (
        action is None
        and question_type in (None, "generic")
        and config.GROQ_CLASSIFY_ENABLED
    ):
        classify_task = asyncio.create_task(
            classify_intent(input_text, bot_username=bot.username or "")
        )

    if question_type and question_type != "generic":
        # Seed dalla domanda stessa (priorità alta: è il testo che l'utente ha scritto)
        input_seeds = extract_seeds_from_input(input_text, question_type, bot_username=bot.username or "")
        # Seed dal contesto immediato (ultimi messaggi prima della domanda)
        topic_seeds = extract_topic_seeds(immediate_context, question_type)
        if question_type == "chi":
            speaker_seeds = get_context_names(recent_context)
            seen: set[str] = {s.lower() for s in input_seeds + topic_seeds}
            for name in speaker_seeds:
                if name.lower() not in seen:
                    topic_seeds.append(name)
                    seen.add(name.lower())
        # Merge: seed dall'input prima, poi dal contesto (dedup preservando ordine)
        seen_lower: set[str] = set()
        merged: list[str] = []
        for s in input_seeds + topic_seeds:
            key = s.lower()
            if key not in seen_lower:
                seen_lower.add(key)
                merged.append(s)
        seed_words = merged or QUESTION_SEEDS.get(question_type, [])
    else:
        # Per input sostanziali (≥4 parole), estrai seeds dal contesto anche senza question_type
        input_words = input_text.split()
        if len(input_words) >= 4:
            input_seeds = extract_seeds_from_input(input_text, None, bot_username=bot.username or "")
            topic_seeds = extract_topic_seeds(immediate_context, "generic")
            seen_ctx: set[str] = set()
            ctx_seeds: list[str] = []
            for s in input_seeds + topic_seeds:
                key = s.lower()
                if key not in seen_ctx:
                    seen_ctx.add(key)
                    ctx_seeds.append(s)
        else:
            ctx_seeds = []
        tone_seeds = TONE_SEEDS.get(tone, []) if tone != "neutral" else []
        # ctx_seeds hanno priorità sui tone_seeds
        seen_merged: set[str] = {s.lower() for s in ctx_seeds}
        seed_words = ctx_seeds + [s for s in tone_seeds if s.lower() not in seen_merged]

    intent_label = "generic"
    if classify_task is not None:
        intent_label = await classify_task
        if intent_label != "generic":
            extra_seeds = INTENT_SEEDS.get(intent_label, [])
            if extra_seeds:
                seen_lower = {seed.lower() for seed in (seed_words or [])}
                merged_seeds = list(seed_words or [])
                for seed in extra_seeds:
                    if seed.lower() not in seen_lower:
                        merged_seeds.append(seed)
                        seen_lower.add(seed.lower())
                seed_words = merged_seeds
            if tone == "neutral":
                tone = INTENT_TONES.get(intent_label, tone)

    # Reazione o accordo breve (≤2 parole): sticker o risposta fissa ironica
    if intent_label in ("reaction", "agreement") and len(input_text.split()) <= 2:
        reaction_trigger_user = None
        if message.from_user and not message.from_user.is_bot:
            reaction_trigger_user = {
                "user_id": message.from_user.id,
                "username": message.from_user.username or "",
                "display_name": message.from_user.full_name or message.from_user.username or str(message.from_user.id),
            }
        reaction_candidates = build_mention_candidates(
            trigger_user=reaction_trigger_user,
            recent_context=recent_context,
            exclude_user_ids={bot.id} if bot.id is not None else set(),
        )
        sent_sticker = False
        if random.random() < 0.35:
            sticker_file_id = await get_random_sticker(chat.id)
            if sticker_file_id:
                try:
                    await message.reply_sticker(sticker=sticker_file_id)
                    sent_sticker = True
                except Exception:
                    pass
        if not sent_sticker:
            short_output = random.choice(REACTION_SHORT_RESPONSES)
            rendered, parse_mode = resolve_placeholder_mentions(short_output, reaction_candidates)
            reply = await message.reply_text(rendered, parse_mode=parse_mode)
            await log_generated_message(
                chat_id=chat.id,
                trigger_type="mention",
                groq_enabled=groq_enabled,
                used_groq=False,
                persona_ids=persona_ids,
                input_text=message.text or message.caption,
                draft_text=short_output,
                output_text=short_output,
                recent_context=recent_context,
                request_message_id=message.message_id,
                response_message_id=reply.message_id,
                notes="reaction_short",
            )
        await reset_autopost_cooldown(chat.id)
        return

    draft = generate_draft(
        persona_ids=persona_ids,
        live_texts=live_texts or None,
        question_type=question_type,
        seed_words=seed_words or None,
        avoid_question_ending=True,
        chat_id=chat.id,
    )
    if groq_enabled:
        output = await refine_draft(
            draft=draft,
            recent_context=recent_context,
            persona_ids=persona_ids,
            tone=tone,
            temperature=settings.groq_temperature if settings is not None else None,
            trigger_input=input_text if intent_label == "roast" else None,
        )
    else:
        output = draft
    output = polish_generated_text(output)

    trigger_user = None
    if message.from_user and not message.from_user.is_bot:
        trigger_user = {
            "user_id": message.from_user.id,
            "username": message.from_user.username or "",
            "display_name": message.from_user.full_name or message.from_user.username or str(message.from_user.id),
        }

    mention_candidates = build_mention_candidates(
        trigger_user=trigger_user,
        recent_context=recent_context,
        exclude_user_ids={bot.id} if bot.id is not None else set(),
    )
    rendered_output, parse_mode = resolve_placeholder_mentions(output, mention_candidates)
    reply = await message.reply_text(rendered_output, parse_mode=parse_mode)
    if random.random() < config.GIF_MENTION_PROBABILITY:
        gif_count = await count_recent_gifs(chat.id, config.GIF_CONTEXT_MINUTES)
        if gif_count >= config.GIF_TRIGGER_COUNT:
            gif_file_id = await get_random_gif(chat.id)
            if gif_file_id:
                try:
                    await message.reply_animation(animation=gif_file_id)
                except Exception:
                    pass
    elif random.random() < config.STICKER_RESEND_PROBABILITY:
        sticker_file_id = await get_random_sticker(chat.id)
        if sticker_file_id:
            try:
                await message.reply_sticker(sticker=sticker_file_id)
            except Exception:
                pass
    await log_generated_message(
        chat_id=chat.id,
        trigger_type="mention",
        groq_enabled=groq_enabled,
        used_groq=groq_enabled,
        persona_ids=persona_ids,
        input_text=message.text or message.caption,
        draft_text=draft,
        output_text=materialize_placeholder_labels(output, mention_candidates),
        recent_context=recent_context,
        request_message_id=message.message_id,
        response_message_id=reply.message_id,
        notes="reply_trigger" if message.reply_to_message else "mention_trigger",
    )
    await reset_autopost_cooldown(chat.id)


def get_mention_handler() -> MessageHandler:
    return MessageHandler(filters.ALL & ~filters.COMMAND, handle_mention)
