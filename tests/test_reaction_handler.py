from telegram import ReactionCount, ReactionTypeEmoji

from cumbot.handlers.reaction_handler import _reaction_delta_map, _reaction_total_breakdown


class DummyReactionCountUpdate:
    def __init__(self, reactions):
        self.reactions = reactions


def test_reaction_delta_map_tracks_added_and_removed_reactions() -> None:
    old = (ReactionTypeEmoji("🔥"),)
    new = (ReactionTypeEmoji("🔥"), ReactionTypeEmoji("😂"))
    assert _reaction_delta_map(old, new) == {"😂": 1}


def test_reaction_total_breakdown_builds_aggregate_count() -> None:
    update = DummyReactionCountUpdate(
        (
            ReactionCount(ReactionTypeEmoji("🔥"), 3),
            ReactionCount(ReactionTypeEmoji("😂"), 2),
        )
    )
    assert _reaction_total_breakdown(update) == {"🔥": 3, "😂": 2}
