from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from cumbot import config


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_UNSET = object()


@dataclass(slots=True)
class ChatSettings:
    chat_id: int
    chat_type: str
    title: str | None
    active_persona_ids: list[str] = field(default_factory=list)
    autopost_enabled: bool = False
    groq_enabled: bool = True
    groq_temperature: float = config.GROQ_REFINER_TEMPERATURE
    cooldown_min_messages: int = config.AUTOPOST_MIN_MESSAGES
    cooldown_max_messages: int = config.AUTOPOST_MAX_MESSAGES
    messages_since_bot: int = 0
    next_autopost_after: int = config.AUTOPOST_MIN_MESSAGES
    created_at: str | None = None
    last_seen_at: str | None = None


@dataclass(slots=True)
class Announcement:
    id: int
    chat_id: int
    text: str
    hour: int
    minute: int
    enabled: bool
    created_at: str


@dataclass(slots=True)
class GeneratedMessageRecord:
    id: int
    created_at: str
    chat_id: int
    trigger_type: str
    groq_enabled: bool
    used_groq: bool
    persona_ids: list[str] = field(default_factory=list)
    input_text: str | None = None
    draft_text: str | None = None
    output_text: str | None = None
    recent_context: list[dict] = field(default_factory=list)
    request_message_id: int | None = None
    response_message_id: int | None = None
    reaction_count: int = 0
    reaction_breakdown: dict[str, int] = field(default_factory=dict)
    last_reaction_at: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class TrainingCorpusRecord:
    id: int
    chat_id: int
    source_kind: str
    source_key: str
    user_id: int | None
    username: str
    text: str
    created_at: str
    inserted_at: str


@dataclass(slots=True)
class ChatTrainingState:
    chat_id: int
    last_retrain_at: str | None = None
    last_live_corpus_id: int | None = None
    last_export_fingerprint: str | None = None
    last_export_path: str | None = None
    training_corpus_size: int = 0
    models_path: str | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class BirthdayEntry:
    id: int
    chat_id: int
    user_id: int
    username: str
    display_name: str
    day: int
    month: int
    birth_year: int
    created_at: str
    updated_at: str


def _pick_autopost_threshold(
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    lower = max(1, minimum if minimum is not None else config.AUTOPOST_MIN_MESSAGES)
    upper = max(lower, maximum if maximum is not None else config.AUTOPOST_MAX_MESSAGES)
    return random.randint(lower, upper)


def _deserialize_chat(row: aiosqlite.Row | None) -> ChatSettings | None:
    if row is None:
        return None
    raw_personas = row["active_persona_ids"] or "[]"
    try:
        persona_ids = json.loads(raw_personas)
    except json.JSONDecodeError:
        persona_ids = []
    return ChatSettings(
        chat_id=row["chat_id"],
        chat_type=row["chat_type"],
        title=row["title"],
        active_persona_ids=[str(value) for value in persona_ids],
        autopost_enabled=bool(row["autopost_enabled"]),
        groq_enabled=bool(row["groq_enabled"]) if "groq_enabled" in row.keys() else True,
        groq_temperature=(
            float(row["groq_temperature"])
            if "groq_temperature" in row.keys()
            else config.GROQ_REFINER_TEMPERATURE
        ),
        cooldown_min_messages=(
            int(row["cooldown_min_messages"])
            if "cooldown_min_messages" in row.keys()
            else config.AUTOPOST_MIN_MESSAGES
        ),
        cooldown_max_messages=(
            int(row["cooldown_max_messages"])
            if "cooldown_max_messages" in row.keys()
            else config.AUTOPOST_MAX_MESSAGES
        ),
        messages_since_bot=(
            int(row["messages_since_bot"])
            if "messages_since_bot" in row.keys()
            else 0
        ),
        next_autopost_after=(
            int(row["next_autopost_after"])
            if "next_autopost_after" in row.keys()
            else _pick_autopost_threshold()
        ),
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
    )


def _deserialize_generated_message(row: aiosqlite.Row | None) -> GeneratedMessageRecord | None:
    if row is None:
        return None

    try:
        persona_ids = json.loads(row["persona_ids"] or "[]")
    except json.JSONDecodeError:
        persona_ids = []

    try:
        recent_context = json.loads(row["recent_context"] or "[]")
    except json.JSONDecodeError:
        recent_context = []
    raw_breakdown = row["reaction_breakdown"] if "reaction_breakdown" in row.keys() else "{}"
    try:
        reaction_breakdown = json.loads(raw_breakdown or "{}")
    except json.JSONDecodeError:
        reaction_breakdown = {}
    if not isinstance(reaction_breakdown, dict):
        reaction_breakdown = {}

    return GeneratedMessageRecord(
        id=row["id"],
        created_at=row["created_at"],
        chat_id=row["chat_id"],
        trigger_type=row["trigger_type"],
        groq_enabled=bool(row["groq_enabled"]),
        used_groq=bool(row["used_groq"]),
        persona_ids=[str(value) for value in persona_ids],
        input_text=row["input_text"],
        draft_text=row["draft_text"],
        output_text=row["output_text"],
        recent_context=recent_context,
        request_message_id=row["request_message_id"],
        response_message_id=row["response_message_id"],
        reaction_count=int(row["reaction_count"]) if "reaction_count" in row.keys() else 0,
        reaction_breakdown={
            str(key): int(value)
            for key, value in reaction_breakdown.items()
            if isinstance(key, str)
            and isinstance(value, (int, float))
        },
        last_reaction_at=row["last_reaction_at"] if "last_reaction_at" in row.keys() else None,
        notes=row["notes"],
    )


def _deserialize_training_corpus(row: aiosqlite.Row | None) -> TrainingCorpusRecord | None:
    if row is None:
        return None
    return TrainingCorpusRecord(
        id=int(row["id"]),
        chat_id=int(row["chat_id"]),
        source_kind=row["source_kind"],
        source_key=row["source_key"],
        user_id=int(row["user_id"]) if row["user_id"] is not None else None,
        username=row["username"] or "",
        text=row["text"],
        created_at=row["created_at"],
        inserted_at=row["inserted_at"],
    )


def _deserialize_chat_training_state(row: aiosqlite.Row | None) -> ChatTrainingState | None:
    if row is None:
        return None
    return ChatTrainingState(
        chat_id=int(row["chat_id"]),
        last_retrain_at=row["last_retrain_at"],
        last_live_corpus_id=(
            int(row["last_live_corpus_id"])
            if row["last_live_corpus_id"] is not None
            else None
        ),
        last_export_fingerprint=row["last_export_fingerprint"],
        last_export_path=row["last_export_path"],
        training_corpus_size=int(row["training_corpus_size"] or 0),
        models_path=row["models_path"],
        updated_at=row["updated_at"],
    )


def _deserialize_birthday(row: aiosqlite.Row | None) -> BirthdayEntry | None:
    if row is None:
        return None
    return BirthdayEntry(
        id=int(row["id"]),
        chat_id=int(row["chat_id"]),
        user_id=int(row["user_id"]),
        username=row["username"] or "",
        display_name=row["display_name"] or "",
        day=int(row["day"]),
        month=int(row["month"]),
        birth_year=int(row["birth_year"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _normalize_message_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


async def init_db() -> None:
    config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    default_groq_temperature = float(config.GROQ_REFINER_TEMPERATURE)
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT NOT NULL,
                title TEXT,
                active_persona_ids TEXT NOT NULL DEFAULT '[]',
                autopost_enabled INTEGER NOT NULL DEFAULT 0,
                groq_enabled INTEGER NOT NULL DEFAULT 1,
                groq_temperature REAL NOT NULL DEFAULT 0.76,
                cooldown_min_messages INTEGER NOT NULL DEFAULT 20,
                cooldown_max_messages INTEGER NOT NULL DEFAULT 30,
                messages_since_bot INTEGER NOT NULL DEFAULT 0,
                next_autopost_after INTEGER NOT NULL DEFAULT 25,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        # Rinomina gemini_enabled → groq_enabled (colonna storicamente mal nominata).
        try:
            await db.execute(
                "ALTER TABLE chats RENAME COLUMN gemini_enabled TO groq_enabled"
            )
        except aiosqlite.OperationalError:
            pass  # già rinominata o colonna non presente
        # Aggiunge groq_enabled se il DB è vergine (non ha né gemini_enabled né groq_enabled)
        try:
            await db.execute(
                "ALTER TABLE chats ADD COLUMN groq_enabled INTEGER NOT NULL DEFAULT 1"
            )
        except aiosqlite.OperationalError:
            pass  # già presente
        for statement in (
            "ALTER TABLE chats ADD COLUMN cooldown_min_messages INTEGER NOT NULL DEFAULT 20",
            "ALTER TABLE chats ADD COLUMN cooldown_max_messages INTEGER NOT NULL DEFAULT 30",
            "ALTER TABLE chats ADD COLUMN messages_since_bot INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE chats ADD COLUMN next_autopost_after INTEGER NOT NULL DEFAULT 25",
            f"ALTER TABLE chats ADD COLUMN groq_temperature REAL NOT NULL DEFAULT {default_groq_temperature}",
        ):
            try:
                await db.execute(statement)
            except aiosqlite.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS generated_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                trigger_type TEXT NOT NULL,
                groq_enabled INTEGER NOT NULL,
                used_groq INTEGER NOT NULL,
                persona_ids TEXT NOT NULL DEFAULT '[]',
                input_text TEXT,
                draft_text TEXT,
                output_text TEXT,
                recent_context TEXT NOT NULL DEFAULT '[]',
                request_message_id INTEGER,
                response_message_id INTEGER,
                reaction_count INTEGER NOT NULL DEFAULT 0,
                reaction_breakdown TEXT NOT NULL DEFAULT '{}',
                last_reaction_at TEXT,
                notes TEXT
            )
            """
        )
        for statement in (
            "ALTER TABLE generated_messages ADD COLUMN reaction_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE generated_messages ADD COLUMN reaction_breakdown TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE generated_messages ADD COLUMN last_reaction_at TEXT",
        ):
            try:
                await db.execute(statement)
            except aiosqlite.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        # Rinomina colonne Gemini → Groq in generated_messages
        for old_col, new_col in (
            ("gemini_enabled", "groq_enabled"),
            ("used_gemini", "used_groq"),
        ):
            try:
                await db.execute(
                    f"ALTER TABLE generated_messages RENAME COLUMN {old_col} TO {new_col}"
                )
            except aiosqlite.OperationalError:
                pass  # già rinominata o non presente

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS live_corpus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER,
                username TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_live_corpus_chat ON live_corpus (chat_id, id DESC)"
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS training_corpus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                source_kind TEXT NOT NULL,
                source_key TEXT NOT NULL,
                user_id INTEGER,
                username TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                inserted_at TEXT NOT NULL,
                UNIQUE(chat_id, source_key)
            )
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_training_corpus_chat
            ON training_corpus (chat_id, id ASC)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_training_corpus_source
            ON training_corpus (chat_id, source_kind, id ASC)
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_training_state (
                chat_id INTEGER PRIMARY KEY,
                last_retrain_at TEXT,
                last_live_corpus_id INTEGER,
                last_export_fingerprint TEXT,
                last_export_path TEXT,
                training_corpus_size INTEGER NOT NULL DEFAULT 0,
                models_path TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS gif_corpus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                file_unique_id TEXT NOT NULL,
                file_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(chat_id, file_unique_id)
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_gif_corpus_chat ON gif_corpus (chat_id, id DESC)"
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS sticker_corpus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                file_unique_id TEXT NOT NULL,
                file_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(chat_id, file_unique_id)
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sticker_corpus_chat ON sticker_corpus (chat_id, id DESC)"
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                hour INTEGER NOT NULL,
                minute INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_announcements_chat ON announcements (chat_id, id ASC)"
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS birthdays (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                display_name TEXT NOT NULL DEFAULT '',
                day INTEGER NOT NULL,
                month INTEGER NOT NULL,
                birth_year INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(chat_id, user_id)
            )
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_birthdays_chat_date
            ON birthdays (chat_id, month, day, user_id)
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_birthdays_chat_username
            ON birthdays (chat_id, username)
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS birthday_delivery_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                birthday_id INTEGER NOT NULL,
                celebration_year INTEGER NOT NULL,
                delivered_at TEXT NOT NULL,
                UNIQUE(birthday_id, celebration_year)
            )
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_birthday_delivery_lookup
            ON birthday_delivery_log (birthday_id, celebration_year)
            """
        )
        await db.commit()


async def register_chat(chat_id: int, chat_type: str, title: str | None) -> None:
    timestamp = _utc_now()
    autopost_enabled = 1 if chat_type in {"group", "supergroup"} else 0
    next_autopost_after = _pick_autopost_threshold()
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT INTO chats (
                chat_id, chat_type, title, active_persona_ids, autopost_enabled,
                groq_enabled, groq_temperature, cooldown_min_messages, cooldown_max_messages,
                messages_since_bot, next_autopost_after, created_at, last_seen_at
            )
            VALUES (?, ?, ?, '[]', ?, 1, ?, ?, ?, 0, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                chat_type = excluded.chat_type,
                title = excluded.title,
                last_seen_at = excluded.last_seen_at
            """,
            (
                chat_id,
                chat_type,
                title,
                autopost_enabled,
                config.GROQ_REFINER_TEMPERATURE,
                config.AUTOPOST_MIN_MESSAGES,
                config.AUTOPOST_MAX_MESSAGES,
                next_autopost_after,
                timestamp,
                timestamp,
            ),
        )
        await db.commit()


async def get_chat_settings(chat_id: int) -> ChatSettings | None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM chats WHERE chat_id = ?", (chat_id,))
        row = await cursor.fetchone()
    return _deserialize_chat(row)


async def get_all_chats() -> list[ChatSettings]:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM chats ORDER BY created_at ASC")
        rows = await cursor.fetchall()
    return [_deserialize_chat(row) for row in rows if row is not None]


async def get_schedulable_chats() -> list[ChatSettings]:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT *
            FROM chats
            WHERE autopost_enabled = 1
              AND chat_type IN ('group', 'supergroup')
            ORDER BY created_at ASC
            """
        )
        rows = await cursor.fetchall()
    return [_deserialize_chat(row) for row in rows if row is not None]


async def set_message_cooldown(chat_id: int, min_messages: int, max_messages: int) -> None:
    lower = max(1, min(min_messages, max_messages))
    upper = max(lower, max(min_messages, max_messages))
    next_autopost_after = _pick_autopost_threshold(lower, upper)
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            """
            UPDATE chats
            SET cooldown_min_messages = ?,
                cooldown_max_messages = ?,
                messages_since_bot = 0,
                next_autopost_after = ?,
                last_seen_at = ?
            WHERE chat_id = ?
            """,
            (lower, upper, next_autopost_after, _utc_now(), chat_id),
        )
        await db.commit()


async def set_active_persona_ids(chat_id: int, persona_ids: list[str]) -> None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE chats SET active_persona_ids = ?, last_seen_at = ? WHERE chat_id = ?",
            (json.dumps(persona_ids), _utc_now(), chat_id),
        )
        await db.commit()


async def clear_active_persona_ids(chat_id: int) -> None:
    await set_active_persona_ids(chat_id, [])


async def set_groq_enabled(chat_id: int, enabled: bool) -> None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE chats SET groq_enabled = ?, last_seen_at = ? WHERE chat_id = ?",
            (1 if enabled else 0, _utc_now(), chat_id),
        )
        await db.commit()


async def set_groq_temperature(chat_id: int, temperature: float) -> None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE chats SET groq_temperature = ?, last_seen_at = ? WHERE chat_id = ?",
            (float(temperature), _utc_now(), chat_id),
        )
        await db.commit()


async def log_generated_message(
    *,
    chat_id: int,
    trigger_type: str,
    groq_enabled: bool,
    used_groq: bool,
    persona_ids: list[str] | None = None,
    input_text: str | None = None,
    draft_text: str | None = None,
    output_text: str | None = None,
    recent_context: list[dict] | None = None,
    request_message_id: int | None = None,
    response_message_id: int | None = None,
    notes: str | None = None,
) -> int:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO generated_messages (
                created_at, chat_id, trigger_type, groq_enabled, used_groq,
                persona_ids, input_text, draft_text, output_text, recent_context,
                request_message_id, response_message_id, reaction_count,
                reaction_breakdown, last_reaction_at, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '{}', NULL, ?)
            """,
            (
                _utc_now(),
                chat_id,
                trigger_type,
                1 if groq_enabled else 0,
                1 if used_groq else 0,
                json.dumps(persona_ids or []),
                input_text,
                draft_text,
                output_text,
                json.dumps(recent_context or []),
                request_message_id,
                response_message_id,
                notes,
            ),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def get_recent_generated_messages(
    *,
    chat_id: int | None = None,
    limit: int = 10,
) -> list[GeneratedMessageRecord]:
    query = """
        SELECT *
        FROM generated_messages
    """
    params: tuple[int, ...] | tuple[int] | tuple[()] = ()

    if chat_id is not None:
        query += " WHERE chat_id = ?"
        params = (chat_id,)

    query += " ORDER BY id DESC LIMIT ?"
    params = (*params, max(1, min(limit, 50)))

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
    return [
        record
        for row in rows
        if (record := _deserialize_generated_message(row)) is not None
    ]


async def advance_autopost_cooldown(chat_id: int) -> tuple[bool, int, int]:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT autopost_enabled, cooldown_min_messages, cooldown_max_messages,
                   messages_since_bot, next_autopost_after
            FROM chats
            WHERE chat_id = ?
            """,
            (chat_id,),
        )
        row = await cursor.fetchone()
        if row is None or not bool(row["autopost_enabled"]):
            await db.commit()
            return False, 0, 0

        next_count = int(row["messages_since_bot"]) + 1
        threshold = int(row["next_autopost_after"])
        triggered = next_count >= threshold

        if triggered:
            stored_count = 0
            next_threshold = _pick_autopost_threshold(
                int(row["cooldown_min_messages"]),
                int(row["cooldown_max_messages"]),
            )
        else:
            stored_count = next_count
            next_threshold = threshold

        await db.execute(
            """
            UPDATE chats
            SET messages_since_bot = ?,
                next_autopost_after = ?,
                last_seen_at = ?
            WHERE chat_id = ?
            """,
            (stored_count, next_threshold, _utc_now(), chat_id),
        )
        await db.commit()
    return triggered, next_count, threshold


async def reset_autopost_cooldown(chat_id: int) -> int:
    settings = await get_chat_settings(chat_id)
    if settings is None:
        return _pick_autopost_threshold()

    next_threshold = _pick_autopost_threshold(
        settings.cooldown_min_messages,
        settings.cooldown_max_messages,
    )
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            """
            UPDATE chats
            SET messages_since_bot = 0,
                next_autopost_after = ?,
                last_seen_at = ?
            WHERE chat_id = ?
            """,
            (next_threshold, _utc_now(), chat_id),
        )
        await db.commit()
    return next_threshold


async def add_reaction_delta(
    *,
    chat_id: int,
    response_message_id: int,
    delta: int,
    reaction_breakdown: dict[str, int] | None = None,
    reacted_at: str | None = None,
) -> bool:
    if delta == 0:
        return False

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, reaction_count, reaction_breakdown
            FROM generated_messages
            WHERE chat_id = ? AND response_message_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (chat_id, response_message_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return False

        try:
            current_breakdown = json.loads(row["reaction_breakdown"] or "{}")
        except json.JSONDecodeError:
            current_breakdown = {}
        if not isinstance(current_breakdown, dict):
            current_breakdown = {}

        for key, value in (reaction_breakdown or {}).items():
            current_value = int(current_breakdown.get(key, 0))
            current_breakdown[key] = max(0, current_value + int(value))

        await db.execute(
            """
            UPDATE generated_messages
            SET reaction_count = ?,
                reaction_breakdown = ?,
                last_reaction_at = COALESCE(?, last_reaction_at)
            WHERE id = ?
            """,
            (
                max(0, int(row["reaction_count"]) + delta),
                json.dumps(current_breakdown, ensure_ascii=True, sort_keys=True),
                reacted_at,
                int(row["id"]),
            ),
        )
        await db.commit()
    return True


async def overwrite_reaction_count(
    *,
    chat_id: int,
    response_message_id: int,
    reaction_count: int,
    reaction_breakdown: dict[str, int] | None = None,
    reacted_at: str | None = None,
) -> bool:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            SELECT id
            FROM generated_messages
            WHERE chat_id = ? AND response_message_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (chat_id, response_message_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return False

        await db.execute(
            """
            UPDATE generated_messages
            SET reaction_count = ?,
                reaction_breakdown = ?,
                last_reaction_at = COALESCE(?, last_reaction_at)
            WHERE id = ?
            """,
            (
                max(0, reaction_count),
                json.dumps(reaction_breakdown or {}, ensure_ascii=True, sort_keys=True),
                reacted_at,
                int(row[0]),
            ),
        )
        await db.commit()
    return True


async def log_live_message(
    chat_id: int,
    user_id: int | None,
    username: str,
    text: str,
) -> None:
    cleaned = _normalize_message_text(text)
    if not cleaned:
        return
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT INTO live_corpus (chat_id, user_id, username, text, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, user_id, username or "", cleaned, _utc_now()),
        )
        await db.commit()


async def replace_live_corpus(chat_id: int, messages: list[dict[str, Any]]) -> int:
    rows = [
        (
            chat_id,
            item.get("user_id"),
            (item.get("username") or "").strip(),
            _normalize_message_text(item.get("text")),
            item.get("created_at") or _utc_now(),
        )
        for item in messages
        if _normalize_message_text(item.get("text"))
    ]
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute("DELETE FROM live_corpus WHERE chat_id = ?", (chat_id,))
        if rows:
            await db.executemany(
                """
                INSERT INTO live_corpus (chat_id, user_id, username, text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
        await db.commit()
    return len(rows)


async def append_live_corpus(chat_id: int, messages: list[dict[str, Any]]) -> int:
    rows = [
        (
            chat_id,
            item.get("user_id"),
            (item.get("username") or "").strip(),
            _normalize_message_text(item.get("text")),
            item.get("created_at") or _utc_now(),
        )
        for item in messages
        if _normalize_message_text(item.get("text"))
    ]
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        if rows:
            await db.executemany(
                """
                INSERT INTO live_corpus (chat_id, user_id, username, text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
        await db.commit()
    return len(rows)


async def log_gif(chat_id: int, file_unique_id: str, file_id: str) -> None:
    if not file_unique_id or not file_id:
        return
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            """
            DELETE FROM gif_corpus
            WHERE chat_id = ?
              AND id NOT IN (
                  SELECT id
                  FROM gif_corpus
                  WHERE chat_id = ?
                  ORDER BY id DESC
                  LIMIT ?
              )
            """,
            (chat_id, chat_id, max(1, config.GIF_CORPUS_MAX - 1)),
        )
        await db.execute(
            """
            INSERT INTO gif_corpus (chat_id, file_unique_id, file_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, file_unique_id) DO UPDATE SET
                file_id = excluded.file_id,
                created_at = excluded.created_at
            """,
            (chat_id, file_unique_id, file_id, _utc_now()),
        )
        await db.commit()


async def count_recent_gifs(chat_id: int, minutes: int) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM gif_corpus WHERE chat_id = ? AND created_at >= ?",
            (chat_id, cutoff),
        )
        row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def get_random_gif(chat_id: int) -> str | None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT file_id FROM gif_corpus WHERE chat_id = ? ORDER BY RANDOM() LIMIT 1",
            (chat_id,),
        )
        row = await cursor.fetchone()
    return row[0] if row else None


async def log_sticker(chat_id: int, file_unique_id: str, file_id: str) -> None:
    if not file_unique_id or not file_id:
        return
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            """
            DELETE FROM sticker_corpus
            WHERE chat_id = ?
              AND id NOT IN (
                  SELECT id
                  FROM sticker_corpus
                  WHERE chat_id = ?
                  ORDER BY id DESC
                  LIMIT ?
              )
            """,
            (chat_id, chat_id, max(1, config.STICKER_CORPUS_MAX - 1)),
        )
        await db.execute(
            """
            INSERT INTO sticker_corpus (chat_id, file_unique_id, file_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, file_unique_id) DO UPDATE SET
                file_id = excluded.file_id,
                created_at = excluded.created_at
            """,
            (chat_id, file_unique_id, file_id, _utc_now()),
        )
        await db.commit()


async def get_random_sticker(chat_id: int) -> str | None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT file_id FROM sticker_corpus WHERE chat_id = ? ORDER BY RANDOM() LIMIT 1",
            (chat_id,),
        )
        row = await cursor.fetchone()
    return row[0] if row else None


async def get_all_live_messages_for_training(chat_id: int | None = None) -> list[dict]:
    """Ritorna i messaggi del live_corpus in formato compatibile con il trainer.

    Ogni elemento è un dict con i campi `from_id`, `from`, `type`, `text`,
    identico al formato dei messaggi dell'export Telegram. Usato per incorporare
    i messaggi live nel retrain del modello base.

    Se `chat_id` è specificato filtra per quella chat, altrimenti restituisce
    tutti i messaggi del corpus live (utile per bot privati in un solo gruppo).
    """
    query = "SELECT user_id, username, text FROM live_corpus WHERE user_id IS NOT NULL"
    params: tuple[int, ...] = ()
    if chat_id is not None:
        query += " AND chat_id = ?"
        params = (chat_id,)
    query += " ORDER BY id ASC"

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

    return [
        {
            "from_id": f"user{row[0]}",
            "from": row[1] or f"user{row[0]}",
            "type": "message",
            "text": row[2],
        }
        for row in rows
        if row[2]
    ]


async def get_latest_live_corpus_id(chat_id: int) -> int | None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT MAX(id) FROM live_corpus WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


async def get_live_corpus_rows_for_training_corpus(
    chat_id: int,
    *,
    after_id: int | None = None,
) -> list[dict[str, Any]]:
    query = """
        SELECT id, user_id, username, text, created_at
        FROM live_corpus
        WHERE chat_id = ?
          AND user_id IS NOT NULL
    """
    params: list[Any] = [chat_id]
    if after_id is not None:
        query += " AND id > ?"
        params.append(after_id)
    query += " ORDER BY id ASC"

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cursor = await db.execute(query, tuple(params))
        rows = await cursor.fetchall()

    return [
        {
            "source_kind": "live",
            "source_key": f"live:{int(row[0])}",
            "user_id": int(row[1]) if row[1] is not None else None,
            "username": row[2] or "",
            "text": row[3],
            "created_at": row[4],
        }
        for row in rows
        if row[3]
    ]


async def insert_training_corpus_rows(chat_id: int, rows: list[dict[str, Any]]) -> int:
    inserted_at = _utc_now()
    prepared_rows: list[tuple[Any, ...]] = []
    for item in rows:
        source_kind = str(item.get("source_kind") or "").strip().lower()
        source_key = str(item.get("source_key") or "").strip()
        text = _normalize_message_text(item.get("text"))
        if not source_kind or not source_key or not text:
            continue
        prepared_rows.append(
            (
                chat_id,
                source_kind,
                source_key,
                item.get("user_id"),
                (item.get("username") or "").strip(),
                text,
                item.get("created_at") or _utc_now(),
                item.get("inserted_at") or inserted_at,
            )
        )

    if not prepared_rows:
        return 0

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        before_changes = db.total_changes
        await db.executemany(
            """
            INSERT OR IGNORE INTO training_corpus (
                chat_id, source_kind, source_key, user_id, username,
                text, created_at, inserted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            prepared_rows,
        )
        await db.commit()
        inserted = db.total_changes - before_changes
    return int(inserted)


async def replace_training_corpus_source(
    chat_id: int,
    source_kind: str,
    rows: list[dict[str, Any]],
) -> int:
    normalized_source_kind = source_kind.strip().lower()
    if not normalized_source_kind:
        return 0

    inserted_at = _utc_now()
    prepared_rows: list[tuple[Any, ...]] = []
    for item in rows:
        source_key = str(item.get("source_key") or "").strip()
        text = _normalize_message_text(item.get("text"))
        if not source_key or not text:
            continue
        prepared_rows.append(
            (
                chat_id,
                normalized_source_kind,
                source_key,
                item.get("user_id"),
                (item.get("username") or "").strip(),
                text,
                item.get("created_at") or _utc_now(),
                item.get("inserted_at") or inserted_at,
            )
        )

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            "DELETE FROM training_corpus WHERE chat_id = ? AND source_kind = ?",
            (chat_id, normalized_source_kind),
        )
        inserted = 0
        if prepared_rows:
            before_changes = db.total_changes
            await db.executemany(
                """
                INSERT OR IGNORE INTO training_corpus (
                    chat_id, source_kind, source_key, user_id, username,
                    text, created_at, inserted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                prepared_rows,
            )
            inserted = db.total_changes - before_changes
        await db.commit()
    return int(inserted)


async def get_training_corpus_rows(
    chat_id: int,
    *,
    source_kind: str | None = None,
    limit: int | None = None,
) -> list[TrainingCorpusRecord]:
    query = """
        SELECT *
        FROM training_corpus
        WHERE chat_id = ?
    """
    params: list[Any] = [chat_id]

    if source_kind is not None:
        query += " AND source_kind = ?"
        params.append(source_kind.strip().lower())

    query += " ORDER BY created_at ASC, id ASC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(max(1, int(limit)))

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, tuple(params))
        rows = await cursor.fetchall()

    return [
        record
        for row in rows
        if (record := _deserialize_training_corpus(row)) is not None
    ]


async def count_training_corpus_rows(chat_id: int, source_kind: str | None = None) -> int:
    query = "SELECT COUNT(*) FROM training_corpus WHERE chat_id = ?"
    params: list[Any] = [chat_id]
    if source_kind is not None:
        query += " AND source_kind = ?"
        params.append(source_kind.strip().lower())

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cursor = await db.execute(query, tuple(params))
        row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def trim_training_corpus(chat_id: int, max_rows: int) -> int:
    """Elimina le righe più vecchie del training_corpus per chat se supera max_rows.

    Ritorna il numero di righe eliminate (0 se non era necessario).
    Il trim è FIFO: vengono eliminate le righe con id più basso.
    """
    if max_rows <= 0:
        return 0
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM training_corpus WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        total = int(row[0]) if row else 0
        excess = total - max_rows
        if excess <= 0:
            return 0
        await db.execute(
            """
            DELETE FROM training_corpus
            WHERE chat_id = ? AND id IN (
                SELECT id FROM training_corpus
                WHERE chat_id = ?
                ORDER BY id ASC
                LIMIT ?
            )
            """,
            (chat_id, chat_id, excess),
        )
        deleted = db.total_changes
        await db.commit()
    return int(deleted)


async def get_training_corpus_for_training(chat_id: int) -> list[dict[str, Any]]:
    rows = await get_training_corpus_rows(chat_id)
    return [
        {
            "from_id": f"user{row.user_id}",
            "from": row.username or f"user{row.user_id}",
            "type": "message",
            "text": row.text,
        }
        for row in rows
        if row.user_id is not None and row.text
    ]


async def get_chat_training_state(chat_id: int) -> ChatTrainingState | None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM chat_training_state WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
    return _deserialize_chat_training_state(row)


async def update_chat_training_state(
    chat_id: int,
    *,
    last_retrain_at: str | None | object = _UNSET,
    last_live_corpus_id: int | None | object = _UNSET,
    last_export_fingerprint: str | None | object = _UNSET,
    last_export_path: str | None | object = _UNSET,
    training_corpus_size: int | object = _UNSET,
    models_path: str | None | object = _UNSET,
) -> ChatTrainingState:
    current = await get_chat_training_state(chat_id)
    payload = {
        "last_retrain_at": (
            current.last_retrain_at if last_retrain_at is _UNSET and current else last_retrain_at
        ),
        "last_live_corpus_id": (
            current.last_live_corpus_id
            if last_live_corpus_id is _UNSET and current
            else last_live_corpus_id
        ),
        "last_export_fingerprint": (
            current.last_export_fingerprint
            if last_export_fingerprint is _UNSET and current
            else last_export_fingerprint
        ),
        "last_export_path": (
            current.last_export_path
            if last_export_path is _UNSET and current
            else last_export_path
        ),
        "training_corpus_size": (
            current.training_corpus_size
            if training_corpus_size is _UNSET and current
            else training_corpus_size
        ),
        "models_path": current.models_path if models_path is _UNSET and current else models_path,
    }
    resolved_training_corpus_size = payload["training_corpus_size"]
    if resolved_training_corpus_size is _UNSET or resolved_training_corpus_size is None:
        resolved_training_corpus_size = 0
    updated_at = _utc_now()

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT INTO chat_training_state (
                chat_id, last_retrain_at, last_live_corpus_id, last_export_fingerprint,
                last_export_path, training_corpus_size, models_path, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                last_retrain_at = excluded.last_retrain_at,
                last_live_corpus_id = excluded.last_live_corpus_id,
                last_export_fingerprint = excluded.last_export_fingerprint,
                last_export_path = excluded.last_export_path,
                training_corpus_size = excluded.training_corpus_size,
                models_path = excluded.models_path,
                updated_at = excluded.updated_at
            """,
            (
                chat_id,
                None if payload["last_retrain_at"] is _UNSET else payload["last_retrain_at"],
                None
                if payload["last_live_corpus_id"] is _UNSET
                else payload["last_live_corpus_id"],
                None
                if payload["last_export_fingerprint"] is _UNSET
                else payload["last_export_fingerprint"],
                None if payload["last_export_path"] is _UNSET else payload["last_export_path"],
                int(resolved_training_corpus_size),
                None if payload["models_path"] is _UNSET else payload["models_path"],
                updated_at,
            ),
        )
        await db.commit()
    state = await get_chat_training_state(chat_id)
    assert state is not None
    return state


async def get_live_messages(chat_id: int, limit: int = 100) -> list[str]:
    """Ritorna gli ultimi `limit` testi del corpus live per chat_id, in ordine cronologico."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            SELECT text FROM (
                SELECT text, id FROM live_corpus
                WHERE chat_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC
            """,
            (chat_id, max(1, limit)),
        )
        rows = await cursor.fetchall()
    return [row[0] for row in rows if row[0]]


async def upsert_birthday(
    *,
    chat_id: int,
    user_id: int,
    username: str,
    display_name: str,
    day: int,
    month: int,
    birth_year: int,
) -> BirthdayEntry:
    timestamp = _utc_now()
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """
            INSERT INTO birthdays (
                chat_id, user_id, username, display_name,
                day, month, birth_year, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                username = excluded.username,
                display_name = excluded.display_name,
                day = excluded.day,
                month = excluded.month,
                birth_year = excluded.birth_year,
                updated_at = excluded.updated_at
            """,
            (
                chat_id,
                user_id,
                username.strip(),
                display_name.strip(),
                day,
                month,
                birth_year,
                timestamp,
                timestamp,
            ),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM birthdays WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        row = await cursor.fetchone()
    birthday = _deserialize_birthday(row)
    assert birthday is not None
    return birthday


async def get_birthday(chat_id: int, user_id: int) -> BirthdayEntry | None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM birthdays WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        row = await cursor.fetchone()
    return _deserialize_birthday(row)


async def get_birthday_by_username(chat_id: int, username: str) -> BirthdayEntry | None:
    normalized = username.strip().lstrip("@").lower()
    if not normalized:
        return None
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT *
            FROM birthdays
            WHERE chat_id = ?
              AND LOWER(username) = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (chat_id, normalized),
        )
        row = await cursor.fetchone()
    return _deserialize_birthday(row)


async def resolve_known_chat_user(
    chat_id: int,
    username: str,
) -> tuple[int, str, str] | None:
    normalized = username.strip().lstrip("@").lower()
    if not normalized:
        return None

    birthday = await get_birthday_by_username(chat_id, normalized)
    if birthday is not None:
        return birthday.user_id, birthday.username, birthday.display_name

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            SELECT user_id, username
            FROM live_corpus
            WHERE chat_id = ?
              AND user_id IS NOT NULL
              AND LOWER(username) = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (chat_id, normalized),
        )
        row = await cursor.fetchone()
    if row is None or row[0] is None:
        return None
    canonical_username = (row[1] or normalized).strip()
    display_name = f"@{canonical_username}" if canonical_username else f"utente {row[0]}"
    return int(row[0]), canonical_username, display_name


async def delete_birthday(chat_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM birthdays WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        await db.commit()
    return (cursor.rowcount or 0) > 0


async def get_pending_birthdays_for_date(
    *,
    month: int,
    day: int,
    celebration_year: int,
    include_feb29_fallback: bool = False,
) -> list[BirthdayEntry]:
    conditions = ["(month = ? AND day = ?)"]
    params: list[Any] = [month, day]
    if include_feb29_fallback:
        conditions.append("(month = 2 AND day = 29)")

    query = f"""
        SELECT *
        FROM birthdays
        WHERE ({' OR '.join(conditions)})
          AND NOT EXISTS (
              SELECT 1
              FROM birthday_delivery_log
              WHERE birthday_id = birthdays.id
                AND celebration_year = ?
          )
        ORDER BY chat_id ASC, id ASC
    """
    params.append(celebration_year)

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, tuple(params))
        rows = await cursor.fetchall()
    return [
        birthday
        for row in rows
        if (birthday := _deserialize_birthday(row)) is not None
    ]


async def mark_birthday_delivered(
    *,
    birthday_id: int,
    celebration_year: int,
    delivered_at: str | None = None,
) -> bool:
    timestamp = delivered_at or _utc_now()
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        before_changes = db.total_changes
        await db.execute(
            """
            INSERT OR IGNORE INTO birthday_delivery_log (
                birthday_id, celebration_year, delivered_at
            )
            VALUES (?, ?, ?)
            """,
            (birthday_id, celebration_year, timestamp),
        )
        await db.commit()
        inserted = db.total_changes - before_changes
    return bool(inserted)


def _deserialize_announcement(row: aiosqlite.Row | None) -> Announcement | None:
    if row is None:
        return None
    return Announcement(
        id=int(row["id"]),
        chat_id=int(row["chat_id"]),
        text=row["text"],
        hour=int(row["hour"]),
        minute=int(row["minute"]),
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
    )


async def create_announcement(chat_id: int, text: str, hour: int, minute: int) -> Announcement:
    timestamp = _utc_now()
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            INSERT INTO announcements (chat_id, text, hour, minute, enabled, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (chat_id, text, hour, minute, timestamp),
        )
        await db.commit()
        row_id = cursor.lastrowid
        cursor = await db.execute("SELECT * FROM announcements WHERE id = ?", (row_id,))
        row = await cursor.fetchone()
    return _deserialize_announcement(row)


async def get_announcements(chat_id: int) -> list[Announcement]:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM announcements WHERE chat_id = ? ORDER BY hour ASC, minute ASC, id ASC",
            (chat_id,),
        )
        rows = await cursor.fetchall()
    return [a for row in rows if (a := _deserialize_announcement(row)) is not None]


async def get_announcement(announcement_id: int) -> Announcement | None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM announcements WHERE id = ?", (announcement_id,)
        )
        row = await cursor.fetchone()
    return _deserialize_announcement(row)


async def get_due_announcements(hour: int, minute: int) -> list[Announcement]:
    """Restituisce gli annunci abilitati che devono scattare a quest'ora e minuto."""
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM announcements
            WHERE enabled = 1 AND hour = ? AND minute = ?
            ORDER BY chat_id ASC, id ASC
            """,
            (hour, minute),
        )
        rows = await cursor.fetchall()
    return [a for row in rows if (a := _deserialize_announcement(row)) is not None]


async def toggle_announcement(announcement_id: int) -> Announcement | None:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "UPDATE announcements SET enabled = NOT enabled WHERE id = ?",
            (announcement_id,),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM announcements WHERE id = ?", (announcement_id,)
        )
        row = await cursor.fetchone()
    return _deserialize_announcement(row)


async def update_announcement(
    announcement_id: int,
    *,
    text: str | None = None,
    hour: int | None = None,
    minute: int | None = None,
) -> Announcement | None:
    updates: list[str] = []
    params: list = []
    if text is not None:
        updates.append("text = ?")
        params.append(text)
    if hour is not None:
        updates.append("hour = ?")
        params.append(hour)
    if minute is not None:
        updates.append("minute = ?")
        params.append(minute)
    if not updates:
        return await get_announcement(announcement_id)
    params.append(announcement_id)
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            f"UPDATE announcements SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM announcements WHERE id = ?", (announcement_id,)
        )
        row = await cursor.fetchone()
    return _deserialize_announcement(row)


async def delete_announcement(announcement_id: int) -> bool:
    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM announcements WHERE id = ?", (announcement_id,)
        )
        await db.commit()
    return (cursor.rowcount or 0) > 0


async def get_top_reacted_messages(
    *,
    chat_id: int | None = None,
    limit: int = 5,
) -> list[GeneratedMessageRecord]:
    query = """
        SELECT *
        FROM generated_messages
        WHERE reaction_count > 0
    """
    params: tuple[int, ...] | tuple[int] | tuple[()] = ()

    if chat_id is not None:
        query += " AND chat_id = ?"
        params = (chat_id,)

    query += " ORDER BY reaction_count DESC, id DESC LIMIT ?"
    params = (*params, max(1, min(limit, 20)))

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

    return [
        record
        for row in rows
        if (record := _deserialize_generated_message(row)) is not None
    ]
