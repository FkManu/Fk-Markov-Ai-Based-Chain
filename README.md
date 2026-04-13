# Fk-Markov-Ai-Based-Chain

Telegram group bot that mixes chat-scoped Markov generation, live contextual adaptation, and Groq-based refinement / assistant flows.

This project is built for self-hosted use on Ubuntu VPS and is designed to imitate the tone, rhythm, and recurring patterns of a specific Telegram group while keeping each chat isolated at training and runtime level.

## What The Project Does

The bot has two main personalities:

- **Group imitation bot**: generates replies and autoposts in the style of a Telegram group using Markov chains trained on chat exports plus progressively consolidated live messages.
- **AI assistant via `/ask`**: answers direct questions using Groq, with web-enabled compound models, fallback chain, and multi-turn continuation when users reply to a previous `/ask` answer.

The architecture is intentionally split between:

- **hot context**: recent live messages used for immediate topic seeding and runtime adaptation;
- **cold training corpus**: consolidated per-chat dataset used to rebuild Markov models cleanly over time.

## Main Features

- Chat-scoped Markov models under `models/chats/<chat_id>/`
- Per-chat training corpus with incremental consolidation from live traffic
- Scheduled retrain pipeline with FIFO cap on corpus growth
- Mention / reply handling with intent detection and contextual seeding
- Optional Groq classifier for roast / reaction / agreement behavior
- Groq refiner for style cleanup without losing the original draft character
- `/ask` with Groq compound web search fallback chain
- Multi-turn `/ask` conversations by replying to previous bot answers
- GIF and sticker corpus collection / resend behavior
- Reaction logging and generated-output monitoring
- Daily scheduled announcements via `/annuncio`
- Per-chat settings for cooldown, personas, Groq toggle, temperature, and setup flow
- Ubuntu VPS deployment through `systemd`

## High-Level Architecture

### 1. Markov side

- Telegram exports and consolidated live messages feed the Markov trainer
- Models are built per chat, and optionally per persona/user
- Runtime generation uses:
  - base model for the chat
  - recent context for seeds / topic extraction
  - live model mix for current local drift

### 2. Groq side

- **Refiner**: rewrites the raw Markov draft lightly, preserving slang, tone, mentions, and structure
- **Classifier**: optional intent classifier for short mention / reply triggers
- **Ask pipeline**:
  - `compound-beta`
  - `compound-beta-mini`
  - `llama-3.3-70b-versatile`

### 3. Persistence

- SQLite for runtime state
- `live_corpus` for hot recent messages
- `training_corpus` for canonical per-chat training data
- `chat_training_state` for retrain checkpoints
- output monitoring tables for generated messages and reactions

## Repository Layout

```text
cumbot/
  db/                 SQLite state and corpus management
  groq/               refiner, ask pipeline, service, conversation store
  handlers/           Telegram command and message handlers
  jobs/               scheduled announcements and retrain jobs
  markov/             trainer, generator, tone, intent, reporting
  telegram_context/   recent message collector
deploy/
  cumbot.service      systemd unit
docs/
  runbook.md
  worklog.md
  chat_scoped_training_plan.md
tests/
```

## Current `/ask` Behavior

`/ask` is no longer a single-shot plain LLM call. It now supports:

- dedicated optional API key via `GROQ_ASK_API_KEY`
- web-enabled compound models as primary path
- automatic fallback chain if a model fails or rate limits
- concise response formatting
- multi-turn continuation if the user replies to a previous `/ask` bot message
- in-memory conversation store with TTL

This keeps assistant interactions separate from the Markov pipeline while still living inside the same bot.

## Commands

Admin commands currently include:

- `/persona`
- `/cooldown`
- `/groq`
- `/groqtemp`
- `/setup`
- `/annuncio`
- `/draft`
- `/outputs`
- `/reactions`
- `/importlive`
- `/retrain`
- `/status`

User-facing interaction mainly happens through:

- mentions
- replies
- `/ask`

For the full operational command list and behavior, see [`docs/runbook.md`](docs/runbook.md).

## Local Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python main.py
```

Run tests:

```bash
pytest
```

## VPS Deployment

The project includes a ready-to-use `systemd` unit:

```bash
sudo cp deploy/cumbot.service /etc/systemd/system/cumbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now cumbot
```

Useful commands:

```bash
sudo systemctl status cumbot
sudo systemctl restart cumbot
sudo systemctl stop cumbot
sudo systemctl start cumbot
journalctl -u cumbot -f
```

## Privacy And Publishing

This repository intentionally excludes real datasets and sensitive runtime artifacts.

Not published:

- `.env`
- Telegram exports in `data/`
- trained models in `models/`
- runtime database / local state in `runtime/`
- local caches, logs, virtualenvs

Before publishing changes, always check:

```bash
git status
```

## Important Docs

- [`docs/runbook.md`](docs/runbook.md): operational reference
- [`docs/worklog.md`](docs/worklog.md): chronological implementation history
- [`docs/chat_scoped_training_plan.md`](docs/chat_scoped_training_plan.md): training architecture roadmap
- [`docs/testing.md`](docs/testing.md): testing notes

## Project Status

The repository reflects an actively evolving production bot. The documentation in `docs/` is part of the core project, not an afterthought: it tracks design decisions, training evolution, deployment setup, and behavioral tuning over time.
