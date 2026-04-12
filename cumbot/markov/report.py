from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

import aiosqlite

from cumbot import config
from cumbot.markov.generator import generate_candidates, get_model_summary, load_models
from cumbot.markov.trainer import (
    classify_skip_reason,
    extract_display_name,
    extract_sender_id,
    flatten_export_text,
    normalize_training_text,
    resolve_export_path,
)


def _print_summary(chat_id: int | None) -> None:
    summary = get_model_summary(chat_id=chat_id)
    metadata = summary.get("metadata", {})
    payload = {
        "chat_id": chat_id,
        "pipeline_version": metadata.get("pipeline_version"),
        "text_mode": metadata.get("text_mode"),
        "loaded_total": summary.get("loaded_total"),
        "loaded_state_1": summary.get("loaded_state_1"),
        "loaded_state_2": summary.get("loaded_state_2"),
        "persona_count": len(summary.get("available_personas", [])),
        "global_stats": metadata.get("global_stats", {}),
        "models_dir": summary.get("models_dir"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _print_samples(persona_ids: list[str], count: int, chat_id: int | None) -> None:
    candidates = generate_candidates(persona_ids=persona_ids, candidate_count=count, chat_id=chat_id)
    if not candidates:
        print("Nessun candidato generato.")
        return

    for index, candidate in enumerate(candidates, start=1):
        print(f"[{index}] score={candidate['score']:.2f} state={candidate['state_size']}")
        print(candidate["text"])
        print()


def _print_analysis(export_path: str | None, limit: int | None) -> None:
    resolved = resolve_export_path(export_path or config.EXPORT_PATH)
    payload = json.loads(Path(resolved).read_text(encoding="utf-8"))
    messages = payload.get("messages", [])

    skip_reasons: Counter[str] = Counter()
    media_types: Counter[str] = Counter()
    kept_by_sender: Counter[str] = Counter()
    total = 0
    kept = 0
    reply_count = 0
    forwarded = 0
    via_bot = 0

    iterable = messages[:limit] if limit else messages
    for message in iterable:
        if not isinstance(message, dict):
            continue
        if message.get("type") != "message":
            continue

        total += 1
        if message.get("reply_to_message_id") is not None:
            reply_count += 1
        if message.get("forwarded_from"):
            forwarded += 1
        if message.get("via_bot"):
            via_bot += 1
        if message.get("media_type") or message.get("mime_type"):
            media_types[message.get("media_type") or message.get("mime_type")] += 1

        sender_id = extract_sender_id(message)
        if sender_id is None:
            skip_reasons["missing_sender"] += 1
            continue

        raw_text = flatten_export_text(message.get("text"))
        normalized_text = normalize_training_text(raw_text)
        skip_reason = classify_skip_reason(message, raw_text, normalized_text)
        if skip_reason is not None:
            skip_reasons[skip_reason] += 1
            continue

        kept += 1
        sender_name = extract_display_name(message) or sender_id
        kept_by_sender[sender_name] += 1

    analysis = {
        "export_path": str(resolved),
        "sample_limit": limit,
        "messages_seen": total,
        "messages_kept": kept,
        "keep_rate": round((kept / total), 4) if total else 0.0,
        "reply_rate": round((reply_count / total), 4) if total else 0.0,
        "forwarded_rate": round((forwarded / total), 4) if total else 0.0,
        "via_bot_rate": round((via_bot / total), 4) if total else 0.0,
        "skip_reasons": dict(skip_reasons.most_common()),
        "top_media_types": media_types.most_common(15),
        "top_senders_kept": kept_by_sender.most_common(20),
    }
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


async def _fetch_db_stats(chat_id: int | None, limit: int) -> dict:
    query_base = "SELECT trigger_type, groq_enabled, used_groq, draft_text, output_text, reaction_count, reaction_breakdown FROM generated_messages"
    params: tuple = ()
    if chat_id is not None:
        query_base += " WHERE chat_id = ?"
        params = (chat_id,)
    query_base += f" ORDER BY id DESC LIMIT {max(1, limit)}"

    async with aiosqlite.connect(config.DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query_base, params)
        rows = await cursor.fetchall()

        # top reacted (separate query, no LIMIT from above)
        top_query = "SELECT output_text, reaction_count, reaction_breakdown FROM generated_messages WHERE reaction_count > 0"
        top_params: tuple = ()
        if chat_id is not None:
            top_query += " AND chat_id = ?"
            top_params = (chat_id,)
        top_query += " ORDER BY reaction_count DESC LIMIT 10"
        top_cursor = await db.execute(top_query, top_params)
        top_rows = await top_cursor.fetchall()

        # live corpus count
        lc_query = "SELECT COUNT(*) FROM live_corpus"
        lc_params: tuple = ()
        if chat_id is not None:
            lc_query += " WHERE chat_id = ?"
            lc_params = (chat_id,)
        lc_cursor = await db.execute(lc_query, lc_params)
        lc_row = await lc_cursor.fetchone()
        live_corpus_count = lc_row[0] if lc_row else 0

    total = len(rows)
    by_trigger: Counter[str] = Counter()
    groq_used = 0
    draft_changed = 0
    output_lengths: list[int] = []
    with_reaction = 0

    for row in rows:
        by_trigger[row["trigger_type"]] += 1
        if row["used_groq"]:
            groq_used += 1
        draft = row["draft_text"] or ""
        output = row["output_text"] or ""
        if draft and output and draft.strip() != output.strip():
            draft_changed += 1
        if output:
            output_lengths.append(len(output))
        if int(row["reaction_count"]) > 0:
            with_reaction += 1

    top_reacted = []
    for row in top_rows:
        try:
            breakdown = json.loads(row["reaction_breakdown"] or "{}")
        except (json.JSONDecodeError, TypeError):
            breakdown = {}
        top_reacted.append({
            "output_text": row["output_text"],
            "reaction_count": row["reaction_count"],
            "emoji_breakdown": breakdown,
        })

    return {
        "sample_limit": limit,
        "chat_id_filter": chat_id,
        "total_in_sample": total,
        "by_trigger_type": dict(by_trigger.most_common()),
        "reaction_rate": round(with_reaction / total, 4) if total else 0.0,
        "groq_usage_rate": round(groq_used / total, 4) if total else 0.0,
        "draft_changed_by_groq_rate": round(draft_changed / total, 4) if total else 0.0,
        "avg_output_length": round(sum(output_lengths) / len(output_lengths), 1) if output_lengths else 0.0,
        "live_corpus_messages": live_corpus_count,
        "top_reacted": top_reacted,
    }


def _print_db_stats(chat_id: int | None, limit: int) -> None:
    result = asyncio.run(_fetch_db_stats(chat_id=chat_id, limit=limit))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Strumenti locali per ispezionare la pipeline Markov.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary_parser = subparsers.add_parser("summary", help="Stampa il summary dei modelli caricati.")
    summary_parser.add_argument("--chat-id", type=int, default=None, help="Namespace modelli per chat.")

    sample_parser = subparsers.add_parser("sample", help="Genera candidati Markov raw.")
    sample_parser.add_argument("--persona", action="append", default=[], help="Telegram user ID ripetibile.")
    sample_parser.add_argument("--count", type=int, default=config.MARKOV_CANDIDATE_COUNT)
    sample_parser.add_argument("--chat-id", type=int, default=None, help="Namespace modelli per chat.")

    analyze_parser = subparsers.add_parser("analyze", help="Analizza il corpus export e i motivi di scarto.")
    analyze_parser.add_argument("--export", default=None, help="Path export opzionale.")
    analyze_parser.add_argument("--limit", type=int, default=None, help="Limita il numero di messaggi analizzati.")

    db_parser = subparsers.add_parser("db-stats", help="Statistiche degli output generati dal DB.")
    db_parser.add_argument("--chat-id", type=int, default=None, help="Filtra per chat_id.")
    db_parser.add_argument("--limit", type=int, default=500, help="Numero massimo di record da analizzare (default 500).")

    args = parser.parse_args()
    if getattr(args, "chat_id", None) is not None:
        load_models(chat_id=args.chat_id)
    else:
        load_models()

    if args.command == "summary":
        _print_summary(chat_id=args.chat_id)
        return

    if args.command == "sample":
        _print_samples(persona_ids=args.persona, count=args.count, chat_id=args.chat_id)
        return

    if args.command == "analyze":
        _print_analysis(export_path=args.export, limit=args.limit)
        return

    if args.command == "db-stats":
        _print_db_stats(chat_id=args.chat_id, limit=args.limit)


if __name__ == "__main__":
    main()
