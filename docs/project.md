# markov-persona-bot — Project Plan

> Bot Telegram che simula lo stile di un gruppo usando Markov chain + Gemini AI.
> Versione documento: 1.0

---

## Concept

Due modalità distinte e separate:

| Modalità | Trigger | Funzionamento |
|---|---|---|
| **Simula** | Tag bot oppure timer automatico | Markov genera bozza grezza → Gemini raffina con contesto recente |
| **Ask** | Comando `/ask <domanda>` | Gemini puro, chatbot classico, niente Markov |

La **Markov chain** viene addestrata sull'intero export storico della chat: cattura vocabolario, intercalari e combinazioni di parole tipiche del gruppo su migliaia di messaggi. Gemini riceve quella bozza surreale + gli ultimi 10 messaggi recenti del gruppo e produce un output che è sia fedele allo stile storico che vagamente pertinente al topic in corso.

---

## Stack

- **Python 3.11+**
- `python-telegram-bot[job-queue]` v20+ — async, job scheduler integrato
- `markovify` — training e generazione Markov chain
- `google-generativeai` — Gemini 2.0 Flash (free tier, 1500 req/giorno)
- `aiosqlite` — config runtime persistente
- `python-dotenv` — gestione variabili d'ambiente
- **Deployment**: systemd su OCI VM Ubuntu 24.04 (Ampere A1 Flex)

---

## Struttura del progetto

```
markov-persona-bot/
├── main.py                      # Entry point
├── config.py                    # Costanti e env vars
├── handlers/
│   ├── mention_handler.py       # Risposta a tag del bot
│   ├── ask_handler.py           # Comando /ask
│   └── admin_handler.py        # Comandi admin (/persona, /interval, /retrain, /status)
├── markov/
│   ├── trainer.py               # Parsing export JSON + build modelli
│   └── generator.py             # Generazione bozza grezza
├── gemini/
│   ├── refiner.py               # Bozza Markov → output raffinato
│   └── chat.py                  # Gemini puro per /ask
├── telegram_context/
│   └── collector.py             # Buffer in-memory ultimi N messaggi
├── db/
│   └── state.py                 # SQLite async: config runtime
├── data/
│   └── export.json              # Export Telegram Desktop (gitignored)
├── models/                      # Modelli Markov serializzati (.json)
├── .env                         # Segreti (gitignored)
├── .env.example
├── requirements.txt
└── markov-bot.service           # Unit file systemd
```

---

## Variabili d'ambiente

`.env.example`:

```env
TELEGRAM_TOKEN=
GEMINI_API_KEY=
ADMIN_USER_IDS=123456,789012
TARGET_GROUP_ID=
```

---

## Step-by-step implementazione

---

### Step 1 — Setup progetto e dipendenze

Crea la struttura directory sopra. Crea `requirements.txt`:

```
python-telegram-bot[job-queue]
markovify
google-generativeai
python-dotenv
aiosqlite
```

Crea `.env.example` con i placeholder. Crea `.gitignore` che esclude `.env`, `data/`, `models/`, `__pycache__/`.

---

### Step 2 — Parser export Telegram + training Markov

**File**: `markov/trainer.py`

- Legge `data/export.json` (formato Telegram Desktop)
- Estrae messaggi con `type: "message"`, campo `text` che può essere:
  - `str` — usare direttamente
  - `list` di oggetti — concatenare i campi `text` degli oggetti con `type: "plain"`
- Filtra: messaggi < 3 parole, service messages, messaggi che sono solo URL/emoji
- Costruisce due tipi di modello con `markovify.Text(corpus, state_size=2)`:
  - `models/global.json` — corpus di tutti gli utenti concatenato
  - `models/{username}.json` — per singolo utente, **solo se ha ≥ 100 messaggi** (altrimenti skip silenzioso)
- Serializza con `model.to_json()`
- Espone:
  - `train_all(export_path: str) -> dict` — esegue il training, ritorna stats `{total_messages, users_trained, skipped}`
  - `load_model(persona: str | None) -> markovify.Text` — carica da disco, fallback al globale se persona non trovata

---

### Step 3 — Generatore Markov

**File**: `markov/generator.py`

- `generate_draft(persona=None, sentences=2) -> str`
- Tenta con `state_size=2` → fallback a `state_size=1` se `make_sentence()` ritorna `None` dopo 10 tentativi
- Fallback al modello globale se il modello persona non esiste
- **Non pulire il testo**: output rotto è intenzionale, ci pensa Gemini
- I modelli vengono caricati in memoria all'avvio, non a ogni chiamata

---

### Step 4 — Collector contesto recente

**File**: `telegram_context/collector.py`

Buffer in-memory degli ultimi messaggi del gruppo:

- Struttura: `dict[chat_id, deque(maxlen=20)]`
- `add_message(chat_id: int, username: str, text: str)` — aggiunge al buffer
- `get_recent(chat_id: int, n: int = 10) -> list[dict]` — ritorna `[{username, text}, ...]` in ordine cronologico
- **Niente persistenza su disco** — si azzera al riavvio, va bene
- Thread-safe non necessario (async single-thread)

---

### Step 5 — Gemini Refiner

**File**: `gemini/refiner.py`

```python
async def refine_draft(
    draft: str,
    recent_context: list[dict],
    persona: str | None
) -> str
```

**System prompt**:
```
Sei un bot che imita lo stile di una chat di gruppo italiana.
Ricevi una bozza generata da un modello statistico e gli ultimi messaggi della chat.
Il tuo compito: riscrivere la bozza in modo che sembri un messaggio autentico,
informale, con il tono esagerato e colloquiale tipico di quel gruppo.
Usa abbreviazioni, intercalari, tono da chat.
Rendila vagamente pertinente a quello che si stava dicendo.
NON spiegare niente. Rispondi solo con il messaggio riscritto, nient'altro.
```

Se `persona` specificata, aggiungere: `"Imita in particolare lo stile di {persona}."`

**User prompt**:
```
Ultimi messaggi del gruppo:
{username}: {text}
...

Bozza da riscrivere:
{draft}
```

- Modello: `gemini-2.0-flash`
- Gestione `ResourceExhausted` (429): **fallback obbligatorio** → ritorna la bozza Markov grezza
- Gestione risposta vuota: ritorna bozza grezza

---

### Step 6 — Gemini Chat

**File**: `gemini/chat.py`

```python
async def ask_gemini(question: str) -> str
```

- Stateless — nessuna memoria tra chiamate diverse
- System prompt neutro in italiano da assistente generico
- Rate limit hit → messaggio human-friendly, es: *"sono a corto di neuroni, riprova tra poco 🧠"*

---

### Step 7 — Database di stato

**File**: `db/state.py`

Tabella `config (key TEXT PRIMARY KEY, value TEXT)`.

Chiavi gestite:

| Key | Default | Descrizione |
|---|---|---|
| `active_persona` | `null` | Username persona attiva, null = globale |
| `cooldown_min_messages` | `20` | Minimo messaggi umani prima di un autopost |
| `cooldown_max_messages` | `30` | Massimo messaggi umani prima di un autopost |
| `target_chat_id` | da `.env` | Chat ID dove postare automaticamente |

Funzioni async:
- `init_db()` — crea tabella se non esiste, inserisce defaults
- `get_config(key: str) -> str | None`
- `set_config(key: str, value: str)`

---

### Step 8 — Handler: Menzione

**File**: `handlers/mention_handler.py`

- Si attiva su `MessageHandler` quando il bot è menzionato nel testo
- Prima di rispondere: chiama `collector.add_message()` con il messaggio ricevuto
- Flusso: `generate_draft(persona)` → `refine_draft(recent_context, persona)` → `update.message.reply_text()`
- `persona` letta dal DB al momento della risposta

---

### Step 9 — Handler: Ask

**File**: `handlers/ask_handler.py`

- Comando: `/ask <testo>`
- Se testo assente → risponde con usage: `"Uso: /ask <domanda>"`
- Flusso: `ask_gemini(question)` → risponde
- Nessun coinvolgimento della Markov

---

### Step 10 — Handler: Admin

**File**: `handlers/admin_handler.py`

Decorator da applicare a tutti i comandi admin:

```python
def admin_only(func):
    # Controlla che update.effective_user.id sia in ADMIN_USER_IDS
    # Risponde "⛔ Non autorizzato" altrimenti
```

Comandi:

| Comando | Funzione |
|---|---|
| `/persona <username>` | Setta `active_persona` nel DB |
| `/persona reset` | Resetta `active_persona` a null (globale) |
| `/cooldown <min> [max]` | Aggiorna il range del cooldown messaggi per l'autopost |
| `/interval <min> [max]` | Alias legacy di `/cooldown` |
| `/retrain` | Rilancia `train_all()`, ricarica modelli in memoria, conferma con stats |
| `/status` | Risponde con: persona attiva, intervallo, numero modelli caricati, uptime |

---

### Step 11 — Middleware contesto

**In `main.py`**, registrare un handler con priorità alta su tutti i messaggi testuali non-comando:

```python
MessageHandler(filters.TEXT & ~filters.COMMAND, context_middleware)
```

`context_middleware` chiama `collector.add_message()` e poi **non blocca** la propagazione agli altri handler.

---

### Step 12 — Autopost a cooldown

**In `main.py`** con handler dedicato sui messaggi testuali:

```python
async def handle_cooldown(update, context):
    # incrementa il contatore messaggi della chat
    # se supera la soglia random nel range configurato:
    # generate_draft() -> refine_draft(recent_context) -> invia
```

- Non e piu basato sul tempo ma sul traffico reale della chat
- La soglia viene estratta nel range `cooldown_min_messages` - `cooldown_max_messages`
- Un messaggio diretto al bot o una risposta del bot resetta il cooldown
- Log ogni invio: `[COOLDOWN] {chat_id} | persona: {persona} | len: {len(output)}`

---

### Step 13 — Entry point

**File**: `main.py`

Sequenza di avvio:

1. Carica `.env`
2. `await init_db()` — inizializza SQLite
3. `load_model()` — carica modelli Markov in memoria (globale + tutti gli utenti disponibili)
4. Registra middleware contesto
5. Registra handlers (mention, ask, admin)
6. Avvia scheduler
7. `application.run_polling()` — polling (non webhook)

Logging:

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
```

---

### Step 14 — Deployment OCI

**File**: `markov-bot.service`

```ini
[Unit]
Description=Markov Persona Telegram Bot
After=network.target

[Service]
WorkingDirectory=/home/ubuntu/markov-persona-bot
ExecStart=/home/ubuntu/markov-persona-bot/venv/bin/python main.py
Restart=always
RestartSec=10
EnvironmentFile=/home/ubuntu/markov-persona-bot/.env

[Install]
WantedBy=multi-user.target
```

**Comandi setup**:

```bash
# Sul server OCI
git clone <repo> markov-persona-bot
cd markov-persona-bot

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copia export Telegram in data/export.json
# Compila .env con token e API key

# Training iniziale
python -c "from markov.trainer import train_all; train_all('data/export.json')"

# Installa e avvia servizio
sudo cp markov-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now markov-bot

# Verifica log
journalctl -fu markov-bot
```

---

## Note critiche per Codex

- Tutto il codice deve essere **async end-to-end** (`python-telegram-bot` v20+ lo richiede)
- I modelli Markov si caricano in memoria **all'avvio e con `/retrain`**, mai a ogni singola generazione
- Il buffer contesto è **in-memory**: niente persistenza, reset a ogni riavvio, è intenzionale
- L'export JSON Telegram ha `messages[].text` che può essere `str` o `list` — il trainer **deve gestire entrambi**
- Training Markov eseguito **offline** con `/retrain`, non automaticamente all'avvio
- Gemini free tier: modello `gemini-2.0-flash`, ~1500 req/giorno — il **fallback alla bozza grezza è obbligatorio** su ogni chiamata a Gemini
- **Nessun webhook**, solo polling
- I comandi admin sono protetti da `ADMIN_USER_IDS` letto da `.env`, non hardcoded

---

## Flusso dati — Modalità Simula

```
Export JSON (storico completo)
        ↓
   markov/trainer.py
        ↓
  models/*.json (su disco)
        ↓
   markov/generator.py  ←── active_persona (da DB)
        ↓
     draft grezzo
        ↓
   gemini/refiner.py  ←── ultimi 10 msg (collector, in-memory)
        ↓
    output finale
        ↓
   Telegram gruppo
```

---

## Flusso dati — Modalità Ask

```
/ask <domanda>
      ↓
 gemini/chat.py
      ↓
   risposta
      ↓
  reply in chat
```
