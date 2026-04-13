from __future__ import annotations

from collections.abc import Iterable
from html import escape
import re

from telegram.constants import ParseMode


PLACEHOLDER = "@user"
SOFT_RESTARTERS = {
    "ah",
    "ahah",
    "ahah",
    "ahahah",
    "allora",
    "anche",
    "boh",
    "bro",
    "capito",
    "che",
    "chi",
    "cioe",
    "cioè",
    "come",
    "comunque",
    "cosa",
    "dai",
    "dove",
    "era",
    "eri",
    "ha",
    "hai",
    "ho",
    "io",
    "lei",
    "loro",
    "lui",
    "ma",
    "mi",
    "noi",
    "non",
    "perche",
    "perché",
    "pero",
    "però",
    "poi",
    "quindi",
    "raga",
    "sei",
    "si",
    "sono",
    "sta",
    "stai",
    "sto",
    "ti",
    "tu",
    "vabbe",
    "vabbè",
    "voi",
}
_PUNCTUATION_RE = re.compile(r"\s+([,.;:!?])")
_DOUBLE_WORD_RE = re.compile(r"\b([\w@#']+)\b(?:\s+\1\b)+", re.IGNORECASE)
_SPACE_AFTER_PUNCT_RE = re.compile(r"([,;:!?])(?!\s|$)")
_DOUBLE_PUNCT_RE = re.compile(r"([?!])\1+")
_EDGE_PUNCT_RE = re.compile(r"^[^\w@#']+|[^\w@#']+$", re.UNICODE)


def _candidate_label(candidate: dict) -> str:
    username = (candidate.get("username") or "").strip()
    if username:
        if username.startswith("@"):
            return username
        return f"@{username}"

    display_name = (candidate.get("display_name") or "").strip()
    if display_name:
        return display_name

    user_id = candidate.get("user_id")
    return str(user_id) if user_id is not None else "qualcuno"


def build_mention_candidates(
    *,
    trigger_user: dict | None = None,
    recent_context: Iterable[dict] | None = None,
    exclude_user_ids: set[int] | None = None,
) -> list[dict]:
    exclude_user_ids = exclude_user_ids or set()
    candidates: list[dict] = []
    seen: set[int | str] = set()

    def add_candidate(raw_candidate: dict | None) -> None:
        if not raw_candidate:
            return

        user_id = raw_candidate.get("user_id")
        username = (raw_candidate.get("username") or "").strip()
        display_name = (raw_candidate.get("display_name") or "").strip()

        if user_id is not None and user_id in exclude_user_ids:
            return

        dedupe_key = user_id if user_id is not None else username or display_name
        if dedupe_key in seen or not dedupe_key:
            return
        seen.add(dedupe_key)

        candidates.append(
            {
                "user_id": user_id,
                "username": username,
                "display_name": display_name,
            }
        )

    add_candidate(trigger_user)
    for item in recent_context or []:
        add_candidate(item)

    return candidates


def _lowercase_leading_alpha(token: str) -> str:
    for index, char in enumerate(token):
        if char.isalpha():
            return f"{token[:index]}{char.lower()}{token[index + 1:]}"
    return token


def polish_generated_text(text: str) -> str:
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return ""

    cleaned = _PUNCTUATION_RE.sub(r"\1", cleaned)
    cleaned = _DOUBLE_PUNCT_RE.sub(r"\1", cleaned)
    cleaned = _SPACE_AFTER_PUNCT_RE.sub(r"\1 ", cleaned)
    cleaned = _DOUBLE_WORD_RE.sub(lambda match: match.group(1), cleaned)

    tokens = cleaned.split()
    if not tokens:
        return ""

    polished = [tokens[0]]
    for token in tokens[1:]:
        previous = polished[-1]
        normalized = _EDGE_PUNCT_RE.sub("", token).lower()
        if (
            token[:1].isupper()
            and normalized in SOFT_RESTARTERS
            and previous[-1:] not in ".!?;:,("
        ):
            polished[-1] = polished[-1].rstrip(",") + ","
            polished.append(_lowercase_leading_alpha(token))
            continue
        polished.append(token)

    cleaned = " ".join(polished).strip()
    if cleaned and cleaned[-1] not in ".!?":
        cleaned += "?" if "?" in cleaned else "."
    return cleaned


def resolve_placeholder_mentions(
    text: str,
    candidates: list[dict] | None,
) -> tuple[str, str | None]:
    if PLACEHOLDER not in text or not candidates:
        return text, None

    parts = text.split(PLACEHOLDER)
    rendered_parts = [escape(parts[0])]

    fallback_candidate = candidates[0]
    for index, tail in enumerate(parts[1:]):
        candidate = candidates[index] if index < len(candidates) else fallback_candidate
        username = (candidate.get("username") or "").strip()
        user_id = candidate.get("user_id")
        label = _candidate_label(candidate)

        if username:
            rendered_parts.append(escape(label))
        elif user_id is not None:
            rendered_parts.append(
                f'<a href="tg://user?id={int(user_id)}">{escape(label)}</a>'
            )
        else:
            rendered_parts.append(escape(label))

        rendered_parts.append(escape(tail))

    return "".join(rendered_parts), ParseMode.HTML


def materialize_placeholder_labels(text: str, candidates: list[dict] | None) -> str:
    if PLACEHOLDER not in text or not candidates:
        return text

    fallback_candidate = candidates[0]
    rendered = text
    for index in range(text.count(PLACEHOLDER)):
        candidate = candidates[index] if index < len(candidates) else fallback_candidate
        rendered = rendered.replace(PLACEHOLDER, _candidate_label(candidate), 1)
    return rendered
