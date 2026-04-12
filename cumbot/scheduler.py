from __future__ import annotations

import logging
import random

from telegram.ext import Application

from cumbot.access import is_chat_allowed
from cumbot import config
from cumbot.db.state import get_chat_settings, get_live_messages, get_random_sticker, log_generated_message
from cumbot.groq.refiner import refine_draft
from cumbot.markov.generator import generate_draft
from cumbot.markov.rendering import (
    build_mention_candidates,
    materialize_placeholder_labels,
    polish_generated_text,
    resolve_placeholder_mentions,
)
from cumbot.markov.tone import TONE_SEEDS, detect_tone
from cumbot.telegram_context.collector import collector


LOGGER = logging.getLogger(__name__)


async def send_autopost_message(application: Application, chat_id: int) -> bool:
    if not is_chat_allowed(chat_id, None):
        return False
    settings = await get_chat_settings(chat_id)
    if settings is None or not settings.autopost_enabled:
        return False

    recent_context = collector.get_recent(chat_id)
    if not recent_context:
        return False
    tone = detect_tone(recent_context)

    live_texts = await get_live_messages(chat_id, limit=config.LIVE_CORPUS_LIMIT)
    tone_seeds = TONE_SEEDS.get(tone, [])
    draft = generate_draft(
        persona_ids=settings.active_persona_ids,
        live_texts=live_texts or None,
        seed_words=tone_seeds or None,
        chat_id=chat_id,
    )
    if settings.groq_enabled:
        output = await refine_draft(
            draft=draft,
            recent_context=recent_context,
            persona_ids=settings.active_persona_ids,
            tone=tone,
            temperature=settings.groq_temperature,
        )
    else:
        output = draft

    output = polish_generated_text(output)
    mention_candidates = build_mention_candidates(recent_context=recent_context)
    rendered_output, parse_mode = resolve_placeholder_mentions(output, mention_candidates)
    sent_message = await application.bot.send_message(
        chat_id=chat_id,
        text=rendered_output,
        parse_mode=parse_mode,
    )
    await log_generated_message(
        chat_id=chat_id,
        trigger_type="cooldown",
        groq_enabled=settings.groq_enabled,
        used_groq=settings.groq_enabled,
        persona_ids=settings.active_persona_ids,
        draft_text=draft,
        output_text=materialize_placeholder_labels(output, mention_candidates),
        recent_context=recent_context,
        response_message_id=sent_message.message_id,
    )
    if random.random() < config.STICKER_RESEND_PROBABILITY:
        sticker_file_id = await get_random_sticker(chat_id)
        if sticker_file_id:
            try:
                await application.bot.send_sticker(chat_id=chat_id, sticker=sticker_file_id)
            except Exception:
                pass
    LOGGER.info(
        "[COOLDOWN] chat=%s persona=%s llm=%s len=%s",
        chat_id,
        ",".join(settings.active_persona_ids) if settings.active_persona_ids else "global",
        settings.groq_enabled,
        len(output),
    )
    return True
