from __future__ import annotations

from telegram import MessageReactionCountUpdated, MessageReactionUpdated, ReactionType
from telegram.ext import ContextTypes, MessageReactionHandler

from cumbot.db.state import add_reaction_delta, overwrite_reaction_count


def _reaction_key(reaction: ReactionType) -> str:
    reaction_type = getattr(reaction, "type", "")
    if reaction_type == ReactionType.EMOJI:
        return getattr(reaction, "emoji", "emoji")
    if reaction_type == ReactionType.CUSTOM_EMOJI:
        return f"custom:{getattr(reaction, 'custom_emoji_id', 'unknown')}"
    if reaction_type == ReactionType.PAID:
        return "paid"
    return reaction_type or "unknown"


def _reaction_delta_map(
    previous: tuple[ReactionType, ...],
    current: tuple[ReactionType, ...],
) -> dict[str, int]:
    delta: dict[str, int] = {}
    for reaction in previous:
        key = _reaction_key(reaction)
        delta[key] = delta.get(key, 0) - 1
    for reaction in current:
        key = _reaction_key(reaction)
        delta[key] = delta.get(key, 0) + 1
    return {key: value for key, value in delta.items() if value != 0}


def _reaction_total_breakdown(update: MessageReactionCountUpdated) -> dict[str, int]:
    return {
        _reaction_key(item.type): int(item.total_count)
        for item in update.reactions
    }


async def handle_reaction_update(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message_reaction:
        reaction_update: MessageReactionUpdated = update.message_reaction
        delta_map = _reaction_delta_map(
            reaction_update.old_reaction,
            reaction_update.new_reaction,
        )
        delta = sum(delta_map.values())
        if delta == 0:
            return
        await add_reaction_delta(
            chat_id=reaction_update.chat.id,
            response_message_id=reaction_update.message_id,
            delta=delta,
            reaction_breakdown=delta_map,
            reacted_at=reaction_update.date.isoformat(),
        )
        return

    if update.message_reaction_count:
        reaction_count_update: MessageReactionCountUpdated = update.message_reaction_count
        breakdown = _reaction_total_breakdown(reaction_count_update)
        await overwrite_reaction_count(
            chat_id=reaction_count_update.chat.id,
            response_message_id=reaction_count_update.message_id,
            reaction_count=sum(breakdown.values()),
            reaction_breakdown=breakdown,
            reacted_at=reaction_count_update.date.isoformat(),
        )


def get_reaction_handler() -> MessageReactionHandler:
    return MessageReactionHandler(
        handle_reaction_update,
        message_reaction_types=MessageReactionHandler.MESSAGE_REACTION,
    )
