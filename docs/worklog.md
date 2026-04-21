# Worklog

## 2026-04-21 — sessione 29

- Aggiunto comando pubblico `/cumpleanno` per gestione compleanni per gruppo Telegram.
  - Sintassi supportata:
    - `/cumpleanno <data>` per impostare o aggiornare il proprio compleanno;
    - `/cumpleanno @tag <data>` per impostare o aggiornare il compleanno di un utente noto nel gruppo;
    - `/cumpleanno show [@tag]`;
    - `/cumpleanno remove [@tag]`.
  - Parser data tollerante su `gg/mm/aaaa`, `gg/mm/aa`, `gg-mm-aaaa`, `gg-mm-aa`.
  - Giorno e mese accettano anche una sola cifra (`4/5/94` → `04/05/1994` a livello logico).
  - Regola anni a due cifre:
    - `00-25` → `2000-2025`
    - `26-99` → `1926-1999`
  - Input errati o incompleti restituiscono help sintetico con gli esempi piu comuni.
  - Conferma salvataggio compatta: `Compleanno aggiunto per @tag il giorno dd/mm/yyyy.`
- Aggiunte tabelle SQLite dedicate in `db/state.py`:
  - `birthdays` per il salvataggio per-`chat_id` dei compleanni;
  - `birthday_delivery_log` per dedup annuale degli invii.
- Nuovo job `jobs/birthdays.py`:
  - controlla la data locale italiana con `ANNOUNCEMENT_TIMEZONE`;
  - invia il messaggio di auguri a mezzanotte;
  - evita doppi invii dopo restart grazie a `birthday_delivery_log`.
- Gestito caso `29/02`:
  - negli anni bisestili gli auguri partono il 29;
  - negli anni non bisestili partono il 28 con nota esplicita che il compleanno vero sarebbe il 29 e battuta leggera.
- `main.py` aggiornato:
  - registrato il comando bot `/cumpleanno`;
  - registrato l'handler pubblico;
  - registrato il job scheduler compleanni.
- Test aggiunti:
  - parser e help comando;
  - storage DB compleanni;
  - dedup invio annuale;
  - fallback `29/02`.

## 2026-04-17 — sessione 28

- Fix `/annuncio`: i reply agli annunci programmati non triggerano piu il bot come se fosse stato interpellato.
  - Nuovo store in-memory `announcement_store` con TTL per ricordare i `message_id` inviati dal job annunci.
  - `jobs/announcements.py` marca il messaggio appena inviato come annuncio non interattivo.
  - `mention_handler.py` ignora i reply a quei messaggi quando il trigger e solo "reply al bot".
  - `cooldown_handler.py` allineato: reply a un annuncio non vengono trattati come direct bot trigger per il reset cooldown.
  - Eccezione voluta: se nel reply all'annuncio compare un `@bot`, il trigger esplicito continua a funzionare.

## 2026-04-12 — sessione 27

### Tuning seeding e refiner

- **`refiner.py`**: aggiunta regola anti-traduzione slang nel system prompt — "Non tradurre mai termini inglesi usati come slang o gergo nel testo italiano. Lasciali esattamente come appaiono nella bozza (es. 'bro', 'fra', 'cringe', 'vibe', 'hype', 'lol', 'mid', 'goat', 'based', 'sus', 'bruh', 'fr', 'crush', ecc.)". Prima Groq rimuoveva o italianizzava slang come "fra", "bro", "cringe" nei draft Markov.
- **`mention_handler.py`**: seeding contestuale esteso agli input ≥4 parole anche senza `question_type`. Il branch `else` ora chiama `extract_seeds_from_input` + `extract_topic_seeds(immediate_context, "generic")`; i ctx_seeds hanno priorità sui tone_seeds nel merge finale. Prima il seeding era attivo solo sulle domande riconosciute (chi/cosa/come/…).
- **`config.py`**: `IMMEDIATE_CONTEXT_SIZE` alzato da 3 a 5. Il contesto immediato per la topic extraction include ora più messaggi precedenti.

### Fix visualizzazione `/draft`

`admin_handler.py` — `/draft` mostra ora la riga `IN: ...` per i record di tipo `mention` e `ask` con `input_text` presente. Prima l'input trigger non appariva nell'output del comando, rendendo impossibile capire cosa aveva scatenato la risposta.

### Fix punteggiatura doppia `? ?`

`rendering.py` — aggiunto `_DOUBLE_PUNCT_RE = re.compile(r"([?!])\1+")` applicato subito dopo `_PUNCTUATION_RE`. Prima `" ? ?"` veniva collassato in `"??"` da `_PUNCTUATION_RE` ma nulla riduceva il doppio `??` → `?`. Il bug era visibile nel record #464 (`profcant lo fa lui adesso? ? Come cazzo si riconosce?`).

### Miglioramenti intent mention

- **`detect_action` — estrazione nome proprio** (`intent.py`): l'azione `insulta` ora estrae il soggetto con priorità: `@username` → parola capitalizzata (nome proprio, es. "Rocco" da "insulta quel coglione di Rocco") → fallback prime 3 parole. Prima prendeva sempre le prime 3 parole generiche ("quel coglione di"), rendendo il seeding inutile.
- **Reaction/agreement breve** (`mention_handler.py`): quando `intent_label in ("reaction", "agreement")` e l'input è ≤2 parole, il bot bypassa completamente Markov e Groq. Con probabilità 35% invia uno sticker dal corpus; altrimenti risponde con una frase breve ironica da un pool fisso di 24 risposte ("ok", "ci sta", "sei un grande", "diglielo", "vabbè", "maddai", ecc.). Loggato con `notes="reaction_short"`. Fix specifico: "ci sta" viene classificato come `agreement` (non `reaction`) da Groq — la condizione copre entrambi i label.
- **Roast — contrattacco diretto** (`refiner.py`): aggiunto parametro `trigger_input` a `refine_draft`. Quando `tone="aggressive"` e `trigger_input` è presente (solo per `intent_label == "roast"`), Groq riceve l'insulto originale dell'utente e la istruzione di formulare un contrattacco diretto in prima persona invece di limitarsi ad amplificare la bozza.

### `/ask` — web search + conversazione multi-turn

**Web search e fallback chain:**
- `config.py`: aggiunto `GROQ_ASK_API_KEY` (chiave Groq dedicata per `/ask`, separata da `GROQ_API_KEY` usata da refiner e classifier) e `GROQ_COMPOUND_MINI_MODEL=compound-beta-mini`.
- `groq/service.py`: `GroqService.__init__` accetta ora `api_key` opzionale; se fornita sovrascrive `config.GROQ_API_KEY`. Backward-compatible (`groq_service = GroqService()` continua a funzionare).
- `groq/service.py`: aggiunto metodo `generate_conversation(messages, ...)` per chiamate multi-turn con lista completa `{role, content}`.
- `groq/chat.py`: il client `_ask_service` usa `GROQ_ASK_API_KEY` se configurata, altrimenti `GROQ_API_KEY`. Catena di fallback: `compound-beta` (800 tok, web search) → `compound-beta-mini` (600 tok) → `llama-3.3-70b-versatile` (800 tok, no search). Qualsiasi eccezione su un modello passa al successivo; errori loggati con `LOGGER.warning`.
- `groq/chat.py`: system prompt `/ask` riformulato — conciso, no markdown pesante, no frasi di chiusura. Pulizia automatica citazioni inline `[1]`, `[source]` e URL isolati prodotti da compound-beta.
- `ask_handler.py`: aggiunta `TYPING` action durante la generazione; risposte lunghe splittate con `split_message()`.

**Conversazione multi-turn:**
- `groq/conversation_store.py` (nuovo): store in-memory `(chat_id, bot_message_id) → [messages]` con TTL 2 ore. Cleanup automatico ad ogni `set()`. Istanza singleton `ask_store`.
- `telegram_utils.py` (nuovo): `split_message(text)` — divide testo > 4000 char su newline/spazio, condiviso da `ask_handler` e `mention_handler`.
- `ask_handler.py`: dopo ogni risposta salva la conversazione in `ask_store` con `[system, user, assistant]`.
- `mention_handler.py`: all'inizio di `handle_mention`, se il messaggio è un reply a un bot message e `ask_store.get()` restituisce una storia, continua la conversazione con `ask_groq_conversation()` invece di passare al Markov. La storia aggiornata viene salvata sotto il nuovo `message_id` del bot. Loggato con `notes="ask_continuation"`. Il `@mention` del bot viene strippato dal messaggio utente prima di aggiungerlo alla storia.

---

## 2026-04-12 — sessione 26

- Preparazione repository GitHub sicura:
  - creato `README.md` con scopo del progetto, stack, deploy e note privacy;
  - esteso `.gitignore` per coprire anche log, `.coverage`, `.DS_Store` e `runtime/.gitkeep`;
  - aggiunte note operative in `docs/runbook.md` per pubblicazione GitHub senza dataset o dati sensibili;
  - verificato che `gh` sulla VPS era autenticato con account `mmmadme-wq`, quindi serve logout/login prima della creazione repo sotto l'account corretto.

## 2026-04-12 — sessione 25

### Pulizia Gemini

Rimosso tutto il codice Gemini residuo dal repo.

- Eliminata la directory `cumbot/gemini/` (service, refiner, chat, `__init__`).
- `config.py`: rimossi `GEMINI_API_KEY`, `GEMINI_REFINER_MODEL`, `GEMINI_ASK_MODEL`.
- `db/state.py`:
  - Rinominata colonna `gemini_enabled` → `groq_enabled` (tabella `chats`).
  - Rinominate colonne `gemini_enabled` → `groq_enabled`, `used_gemini` → `used_groq` (tabella `generated_messages`).
  - Aggiunta migrazione `ALTER TABLE ... RENAME COLUMN` in `init_db()` per DB esistenti.
  - `set_gemini_enabled()` → `set_groq_enabled()`.
- `admin_handler.py`: rimosso `handle_gemini()` e `CommandHandler("gemini", ...)`, aggiornato tutto a `groq_enabled`/`used_groq`.
- `mention_handler.py`, `scheduler.py`, `ask_handler.py`, `setup_handler.py`: stesse rinominazioni.
- `markov/report.py`: SQL query e chiavi output rinominati (`gemini_usage_rate` → `groq_usage_rate`, `draft_changed_by_gemini_rate` → `draft_changed_by_groq_rate`).
- Test aggiornati: `test_setup_handler.py`, `test_state.py`.
- 54 test passano.

### Filtro messaggi inoltrati

In `trainer.py` / `classify_skip_reason()`: aggiunto controllo `forwarded_from_id != from_id` → skip con reason `forwarded_external`. Messaggi che un utente ha inoltrato da una fonte esterna non vengono più attribuiti alla sua persona nel corpus di training.

### Root cause `?` bias — bigrammi cross-messaggio

**Scoperta**: `split_into_sentences()` di markovify divide solo su `.?!` seguiti da carattere non-minuscolo. Messaggi senza punteggiatura finale o seguiti da minuscola vengono **fusi in un'unica frase** → bigrammi cross-messaggio indesiderati.

Esempio reale: due messaggi consecutivi dello stesso utente del 2025-11-06:
```
"Sei depressa rav"      (nessuna punteggiatura, 20:25:17)
"Facciamo sex chat?"    (messaggio successivo, 20:25:42)
```
Markovify li trattava come un'unica frase → bigramma `(depressa, rav) → Facciamo` → draft "merda dai sei depressa rav facciamo sex chat?" che causava refusal Llama.

**Fix**: sostituito `"\n".join(corpus)` con `parsed_sentences=[msg.split() for msg in corpus]` in:
- `trainer.py` / `_build_model()` — modelli training principali.
- `generator.py` / `build_live_model()` — modello live.

`parsed_sentences` bypassa completamente il sentence splitter di markovify, garantendo che ogni messaggio sia un'unità indipendente a prescindere da punteggiatura e capitalizzazione. Verificato: 0 catene cross-messaggio su 50 tentativi con corpus contenente i messaggi incriminati.

**Nota operativa**: serve un `/retrain` per ricostruire i modelli con i nuovi `parsed_sentences`. I modelli esistenti restano funzionali ma contengono i vecchi bigrammi cross-messaggio.

### Fix `?` bias — livello scoring e generation

- **`mention_handler.py`**: `avoid_question_ending` cambiato da `bool(question_type)` a `True` sempre. Prima era attivo solo quando l'input era rilevato come domanda; per input come "Scemo", "Gay", "ahahahah" il filtro non scattava mai. Ora il pool 36 + filtro `?` sono sempre attivi sulle mention/reply.
- **`generator.py`**: penalty `?` in `_score_candidate()` alzata da `-0.5` a `-2.0`. Con `-0.5` i candidati `?` (70-80% del corpus) vincevano quasi sempre sugli altri a parità di qualità.
- **`refiner.py`**: aggiunta regola nel system prompt — "Se la bozza non termina con '?', l'output non deve MAI terminare con '?'." Previene i casi (#438, #391) in cui Groq aggiungeva `?` su draft che non ce l'avevano.

### Fix refusal Llama in `refiner.py`

Aggiunto `_REFUSAL_RE` regex che rileva le risposte di rifiuto del modello LLM (Llama safety guardrail). Llama restituisce il rifiuto come testo normale invece di sollevare un'eccezione, quindi il controllo precedente (`response is None`) non bastava. Se il pattern matcha, `refine_draft()` fa fallback al draft Markov invece di inviare il rifiuto in chat.

Pattern riconosciuti: "Mi dispiace", "non posso", "Sorry", "I cannot", "I can't", "non sono in grado", "come assistente", "as an AI/assistant".

---

## 2026-04-12 — sessione 24

- Analisi output: il corpus di training conteneva messaggi di bot non filtrati
  (russo/cirillico, Lastfm+ Bot in inglese, canali forwardati con "Source ✤ Via @",
  comandi game-bot `/tstart`/`/premium`). Questi generavano candidati Markov ad alto
  score ma incoerenti.
- **Fix scoring** (`generator.py` — `_score_candidate()`):
  - Penalty Cirillico/Arabo: fino a -12 punti (sotto threshold) per ≥3 char stranieri.
  - Penalty testo inglese: -1.5/hit per ogni EN stopword oltre la prima (≤15 parole).
  - Penalty pattern bot noti: -8.0 per "Source ✤ Via @", `/tstart`, "meow vpn", ecc.
- **Fix training filter** (`trainer.py` — `should_keep_training_text()`):
  - Filtra testo con Cirillico/Arabo pesante (≥3 char contigui).
  - Filtra messaggi forwardati da canali ("Source ✤ Via @").
  - Filtra comandi game/subscription bot (`/tstart`, `/premium`, "non-premium users").
  - Filtra testo prevalentemente inglese (≥3 EN stopwords in ≤12 parole).
- **Risultati misurati** sul modello chat-scoped `-1002026712691`:
  - `?` su `generate_draft` normale: **20%** (da 61.7% del modello globale).
  - `?` con `avoid_question_ending=True`: **0%** su 30 campioni.
- Allineamento training con `ChatExport_2026-04-11` (1.001.443 messaggi):
  - 959.855 righe importate in `training_corpus` (source_kind=export).
  - +555 live consolidati → totale 960.410 righe.
  - Retrain chat-scoped: 618.863 messaggi usati, 101 personas, modelli in
    `models/chats/-1002026712691/` (~167MB state_2).
  - `chat_training_state` aggiornato con `last_live_corpus_id=796`.

## 2026-04-12 — sessione 23

- Preparato deploy persistente via `systemd`.
  - Aggiornato `deploy/cumbot.service` con:
    - `network-online.target`;
    - esecuzione come utente/gruppo `ubuntu`;
    - `PYTHONUNBUFFERED=1`;
    - `EnvironmentFile` dal progetto;
    - restart automatico sempre attivo.
  - Aggiornati `docs/setup.md` e `docs/runbook.md` con la procedura di installazione e gestione del servizio su VPS Ubuntu.

## 2026-04-11 — sessione 22

Review implementazione Step 1–4 del `chat_scoped_training_plan.md`. Implementati Step 5 e Step 6.

- **Step 5 — FIFO cap `training_corpus`**
  - Nuova funzione `trim_training_corpus(chat_id, max_rows)` in `db/state.py`: DELETE FIFO sulle righe con `id` piu basso; ritorna il numero di righe eliminate.
  - `TRAINING_CORPUS_MAX_PER_CHAT=1000000` in `config.py` (configurabile via env).
  - Trim chiamato in `/retrain` dopo il consolidamento live e in `/importlive` dopo l'insert.
- **Step 6 — Scheduler retrain giornaliero**
  - Nuovo file `cumbot/jobs/retrain.py` con `scheduled_retrain(context)`:
    - Gira ogni ora (PTB `run_repeating(interval=3600)`).
    - Entra nella logica solo se l'ora locale rientra in `RETRAIN_SCHEDULE_HOUR` (default `"3"`, supporta range `"2-4"`).
    - Per ogni chat di gruppo: consolida live rows con `id > last_live_corpus_id`, trim FIFO, full rebuild modelli, aggiorna `chat_training_state`.
    - Skip silenzioso se nuovi messaggi < `RETRAIN_MIN_NEW_MESSAGES` (default 50).
    - Usa il lock `retrain_lock` condiviso con `/retrain` manuale.
    - Errori per singola chat loggati, non bloccano le altre.
  - `main.py`: registrato `scheduled_retrain` in `job_queue`.
  - Nuove env: `RETRAIN_SCHEDULE_HOUR=3`, `RETRAIN_MIN_NEW_MESSAGES=50`.
  - 54 test passano.

## 2026-04-11 — sessione 21

- Step 4 del piano `chat_scoped_training_plan` implementato.
  - `/retrain` non rilegge piu tutto il `live_corpus` a ogni giro.
  - Nuovo helper `get_live_corpus_rows_for_training_corpus()` in `db/state.py`:
    restituisce solo i live message oltre un certo `after_id`, gia pronti per il
    consolidamento con `source_kind='live'` e `source_key='live:<row_id>'`.
  - Flusso nuovo di `/retrain`:
    1. legge `last_live_corpus_id` da `chat_training_state`;
    2. consolida nel `training_corpus` solo i nuovi live;
    3. rebuilda il modello dalla base consolidata;
    4. aggiorna `last_live_corpus_id` solo su successo.
  - Se non esiste ancora uno stato precedente, il consolidamento live parte da zero.
  - `train_all()` e stato reso compatibile con `base_messages` anche senza export file presente: questo consente retrain da `training_corpus` puro quando l'export manuale non e ancora disponibile.

## 2026-04-11 — sessione 20

- Step 3 del piano `chat_scoped_training_plan` implementato.
  - `/importlive` e stato reindirizzato dal `live_corpus` al `training_corpus`.
  - Nuovo helper `build_training_corpus_import_rows()` in `markov/trainer.py`:
    - usa `export:<message_id>` come `source_key` quando l'ID Telegram e presente;
    - fallback a hash stabile `exporthash:<sha1>` quando l'ID manca.
  - `reset` sostituisce solo la parte `source_kind='export'` della chat target;
    `append` aggiunge con dedup.
  - `/retrain` ora usa `training_corpus` come base se presente e ci somma sopra
    il `live_corpus` recente; se il corpus freddo e vuoto, resta compatibile con
    l'export file diretto come bootstrap.
  - Lo stato training per chat viene aggiornato anche dopo `/importlive`
    con `last_export_path` e `training_corpus_size`.

## 2026-04-11 — sessione 19

- Step 2 del piano `chat_scoped_training_plan` implementato.
  - Nuove tabelle SQLite:
    - `training_corpus` come corpus freddo canonico per chat, con `UNIQUE(chat_id, source_key)`;
    - `chat_training_state` per checkpoint del retrain (`last_retrain_at`, `last_live_corpus_id`, `last_export_path`, `models_path`, ecc.).
  - Nuovi helper in `db/state.py`:
    - inserimento deduplicato nel corpus freddo;
    - replace scoped per `source_kind`;
    - lettura/count del corpus freddo per chat;
    - lettura/scrittura dello stato training per chat;
    - lettura dell'high-water mark `live_corpus` (`get_latest_live_corpus_id`).
  - `/retrain` salva ora anche lo stato base del retrain riuscito per la chat target, cosi i prossimi step hanno gia un checkpoint reale da cui ripartire.
  - `/status` espone anche ultimo retrain e ultimo export della chat quando esiste il relativo stato.
  - Importante: in questa fase `training_corpus` e pronto ma non e ancora popolato da `/importlive`; il passaggio operativo al corpus freddo resta lo Step 3.

## 2026-04-11 — sessione 18

- Step 1 del piano `chat_scoped_training_plan` implementato.
  - Nuovo resolver `resolve_models_dir(chat_id)` in `config.py`.
  - `train_all(..., chat_id=...)` scrive ora in `models/chats/<chat_id>/state_1`, `state_2`, `metadata.json`.
  - `generator.py` mantiene cache modelli separata per chat e la generazione riceve `chat_id`.
  - `mention_handler.py` e `scheduler.py` passano il `chat_id` alla Markov, quindi reply/autopost usano il namespace corretto.
  - `/retrain` ricarica il namespace della chat target dopo il rebuild.
  - `/status` mostra anche `models_dir` della chat per debug operativo.
  - `markov.report` supporta `--chat-id` per `summary` e `sample`.

## 2026-04-11 — sessione 17

- Formalizzato un nuovo piano strutturato in `docs/chat_scoped_training_plan.md` per arrivare a:
  - modelli separati per chat;
  - `training_corpus` come corpus freddo canonico;
  - `chat_training_state` per ripartenza incrementale;
  - cap FIFO su corpus freddo;
  - retrain schedulato per chat solo dopo isolamento completo.
- Decisione esplicita: `live_corpus` non verra usato come dataset storico infinito. Resta corpus caldo per contesto e live mixing.
- Decisione esplicita: il retrain periodico verra pianificato solo dopo namespace modelli + corpus freddo + stato per chat.

## 2026-04-11 — sessione 16

- `/retrain` reso chat-scoped sul `live_corpus`: il comando ora usa i messaggi live della sola chat target invece di aggregare sempre tutte le chat. Supporta anche export path opzionale come argomento finale.
- Aggiunto comando admin `/importlive [chat:<chat_id>] [reset|append] [export_path]`.
  - Importa un export Telegram manuale dentro `live_corpus` per una chat specifica.
  - `reset` (default) rimpiazza il corpus live di quella chat con l'export; `append` lo accoda.
  - Pensato per riallineare rapidamente una chat a uno storico manuale aggiornato prima del retrain.
- Nuove utility:
  - `build_live_corpus_import_rows()` in `markov/trainer.py` per convertire l'export in righe importabili con timestamp originale;
  - `replace_live_corpus()` e `append_live_corpus()` in `db/state.py`.
- Nota operativa importante: i modelli in `models/` restano ancora un set unico condiviso. Quindi il dataset usato da `/retrain` può essere selezionato per chat, ma l'ultimo retrain resta il set attivo per tutte le chat finché non verrà introdotto un namespacing dei modelli per gruppo.

## 2026-04-11 — sessione 15

- Fix `?` residuo nelle reply a domande: in `markov/generator.py`, quando `avoid_question_ending=True`, il fallback generico usa ora un pool candidati doppio (`MARKOV_CANDIDATE_COUNT * 2`) prima di filtrare i finali con `?`. Riduce i casi in cui tutti i candidati validi restano interrogativi e il bot "cede" al punto interrogativo finale.
- Feature opzionale: classifier intent Groq calibrato sul gruppo.
  - Nuovo file `cumbot/groq/classifier.py` con label `roast`, `reaction`, `agreement`, `generic`.
  - Flag `GROQ_CLASSIFY_ENABLED=false` di default in `config.py` / `.env.example`.
  - In `mention_handler.py`, se non c'e un'azione esplicita e non c'e una domanda specifica, il bot puo classificare la mention/reply via Groq mentre prepara il resto del contesto.
  - `roast` aggiunge seed aggressivi e puo spostare il tone verso `aggressive`; `reaction` e `agreement` aggiungono seed leggeri coerenti col vocabolario del gruppo.
  - Fallback completamente silenzioso a `generic` su feature disabilitata, assenza API key o errore Groq.
  - Test aggiunti per pool doubling e classifier.

## 2026-04-11 — sessione 14

- Fix refiner: duplicazione sistematica di parolacce (es. bozza con 1 "cazzo" → output con 3). Causa: regola "non aggiungere duplicati" era qualitativa e Groq la aggirava aggiungendo "del cazzo"/"di merda" come qualificatori generici.
  - Regola resa **quantitativa**: "ogni parola volgare nell'output non può apparire più volte di quante ne appaiono nella bozza."
  - Aggiunta blacklist filler volgari abusati: `del cazzo / di merda` come aggettivi generici → sostituire con aggettivi specifici (assurdo, marcio, squallido, orrendo, ecc.).

## 2026-04-11 — sessione 13

- Feature: seeding migliorato su mention/reply — i seed vengono ora estratti anche dalla domanda stessa (input_text), non solo dal contesto dei messaggi precedenti.
  - Nuova funzione `extract_seeds_from_input(input_text, question_type, bot_username)` in `intent.py`: rimuove il @mention del bot, poi applica la stessa logica di tokenizzazione/filtraggio di `extract_topic_seeds` direttamente sul testo del trigger.
  - I seed dall'input hanno priorità su quelli del contesto (merged con dedup, input prima). Esempio: "@bot dimmi di Marco" → "Marco" diventa seed anche se non compariva nei messaggi precedenti.
- Feature: rilevamento comandi d'azione espliciti su mention/reply.
  - Nuova funzione `detect_action(text, bot_username)` in `intent.py`, ritorna `BotAction(type, target)` o `None`.
  - Azioni supportate:
    - `gif`: "manda una gif", "mandami gif", "gif" → invia GIF casuale dal corpus; fallback a testo se corpus vuoto.
    - `sticker`: "manda uno sticker", "mandami sticker", "sticker" → invia sticker casuale dal corpus; fallback a testo.
    - `insulta [nome]`: "insulta Marco", "insultalo", "insulta quel tizio" → genera testo Markov con seed aggressivi + nome del target, raffina con Groq in modalità `tone="aggressive"`.
  - Dispatch in `mention_handler.py` tramite `_handle_action()` — se l'azione viene eseguita, l'handler fa return senza generare testo Markov normale.
  - 40 test passano.

## 2026-04-11 — sessione 12

- Fix refiner Groq: rimosso il vincolo di parole esplicito (`"circa {N} parole"`) dal `user_prompt`. Era la causa principale dei troncamenti: Groq aggiungeva testo a metà bozza per "amplificare", poi tagliava la parte finale per rispettare il conteggio, producendo frasi incomplete (es. "mi dai?" senza complemento).
- System prompt: aggiunte tre regole anti-troncamento:
  1. "Non inserire testo a metà frase se costringe a tagliare la parte finale — preferisci sostituzione lessicale puntuale."
  2. "Non troncare la parte finale. Se la bozza termina con domanda/richiesta diretta ('mi dai X'), mantienila intatta."
  3. "Se la bozza è già grammaticalmente corretta e di senso compiuto, apporta solo modifiche minime."
- 40 test passano.

## 2026-04-11 — sessione 11

- Feature: comando admin `/groqtemp [chat:<chat_id>] <0-2 | status | reset>` per regolare la temperatura Groq direttamente da Telegram, per singola chat.
  - Persistenza in SQLite: nuova colonna `groq_temperature` nella tabella `chats`, con migrazione automatica per DB esistenti.
  - `ChatSettings` ora espone `groq_temperature`; aggiunto setter `set_groq_temperature()` in `db/state.py`.
  - La temperatura per-chat viene usata sia dal refiner Groq (`mention`, `reply`, `autopost`) sia da `/ask`.
  - `admin_handler.py`: parsing con supporto a decimali `.` e `,`, range valido `0-2`, output `status/reset`, e visibilita della temperatura anche in `/status`.
  - UX privata migliorata: in DM `/groqtemp` puo aprire una selezione chat via inline buttons, come `/setup` e `/annuncio`, invece di richiedere per forza `chat_id`.
  - `setup_handler.py`: il pannello `/setup` mostra anche la temperatura Groq attiva della chat.
  - `config.py` / `.env.example`: aggiunti `GROQ_REFINER_TEMPERATURE` e `GROQ_ASK_TEMPERATURE` come default globali.
  - Runbook aggiornato con nuovo comando e note operative.
- Fix whitelist chat: `access.py` ora tratta come equivalenti gli ID canonici dei supergruppi (`-100...`) e lo shorthand positivo senza prefisso `-100`. Sistemato anche il `.env` reale con i due `ALLOWED_CHAT_IDS` completi, per evitare il caso in cui il bot risponda solo all'admin ma non agli altri membri del gruppo.

## 2026-04-11 — sessione 10

- Feature: `/annuncio` — comando admin per annunci programmati, completamente separato da Markov/Groq.
  - Tabella `announcements` in SQLite: `id`, `chat_id`, `text`, `hour`, `minute`, `enabled`, `created_at`.
  - CRUD in `db/state.py`: `create_announcement`, `get_announcements`, `get_announcement`, `get_due_announcements(hour, minute)`, `toggle_announcement`, `update_announcement`, `delete_announcement`. `Announcement` dataclass.
  - `cumbot/handlers/annuncio_handler.py`: pannello inline completo. In gruppo → lista annunci della chat corrente. In privato → selezione chat. Flusso: chat → lista annunci → nuovo (preset orario) → testo libero → salva. Ogni annuncio ha: toggle on/off, modifica testo, modifica orario, elimina (con conferma).
  - `cumbot/jobs/announcements.py`: `send_due_announcements()` — job ripetuto ogni 60s, confronta ora locale (timezone `ANNOUNCEMENT_TIMEZONE`, default `Europe/Rome`) con `hour`/`minute` degli annunci abilitati e invia. Errori di send loggati ma non bloccanti.
  - `cumbot/jobs/__init__.py`: nuovo package `jobs/`.
  - `config.py`: aggiunto `ANNOUNCEMENT_TIMEZONE = os.getenv("ANNOUNCEMENT_TIMEZONE", "Europe/Rome")`.
  - `main.py`: import handler annuncio + job; registrazione handler in group=3; `job_queue.run_repeating(send_due_announcements, interval=60, first=5)`.
  - `handlers/__init__.py`: esportato `get_annuncio_handlers`.
  - `/annuncio` aggiunto a `_BOT_COMMANDS`.
  - Preset orari aggiornati dall'utente: aggiunti 00:00 e 01:00 (lista finale: 00:00, 01:00, 07:00, 08:00, 12:00, 18:00, 20:00, 21:00, 22:00, 23:00).
  - UI `/annuncio` allineata esplicitamente al timezone italiano: testi e conferme mostrano `ANNOUNCEMENT_TIMEZONE`/`Europe-Rome` come riferimento orario.
  - 32 test passano.

## 2026-04-11 — sessione 9

- Fix tone hints in `tone.py`: gli hint erano troppo direttivi e facevano aggiungere a Groq parolacce anche se non presenti nel draft. Riformulati: "se la bozza contiene già insulti, mantienili o intensificali; non aggiungere parolacce nuove se non presenti."
- Fix refiner `@user`: aggiunta regola esplicita nel system prompt ("mantieni @user esattamente"). Aggiunto fallback post-processing: se `@user` era nel draft ma Groq lo ha rimosso, viene riappeso in coda all'output.
- Fix GIF su mention: `send_animation(chat_id=...)` → `message.reply_animation(...)` — ora la GIF è un reply al messaggio trigger invece di un messaggio standalone.
- Feature: sticker corpus. Tabella `sticker_corpus` (dedup UNIQUE su chat+file_unique_id). Salvataggio automatico nel middleware (`log_sticker()`). Resend su mention (prob `STICKER_RESEND_PROBABILITY=8%`, come branch `elif` dopo GIF) e su autopost. Config: `STICKER_RESEND_PROBABILITY`, `STICKER_CORPUS_MAX`.
- 32 test passano.

## 2026-04-11 — sessione 8

- Aggiunto comando admin `/draft [chat:<chat_id>] [limit]`: mostra gli ultimi N output con draft Markov e output Groq a confronto, evidenziando con ✏️ i messaggi in cui Groq ha modificato la bozza.
- Registrato `/draft` in `_BOT_COMMANDS` (main.py) e `get_admin_handlers()`.
- Fix refiner Groq: temperature abbassata da 1.15 a 0.9 (meno divergenza creativa). System prompt rafforzato con regole ferree: mantieni verbo e sostantivi chiave, non aggiungere contenuto sessuale/violento non presente nella bozza, non addolcire insulti già presenti.

## 2026-04-11 — sessione 7

- Analisi corpus: 1M messaggi analizzati per vocabolario aggressivo/playful reale. Trovate 40+ parole aggressive con >100 occorrenze (inclusi frocio, negro, finocchio, mongo, down, bestia, animale). Verificato che Markolino non fa mirroring esplicito degli insulti (1.1% reply aggressivi su insulti ricevuti — baseline casuale).
- Feature E — riconoscimento tono: nuovo modulo `cumbot/markov/tone.py` con `detect_tone()` basato su regex corpus-driven. Toni rilevati: "aggressive" (1 hit basta), "playful" (≥2 hit ahah/lol in 5 msg, soglia alta perché ahah è ubiquo nel corpus con 45k occorrenze). Modifiche a `refiner.py` (parametro `tone=`), `mention_handler.py` e `scheduler.py`. Zero chiamate Groq extra — il tone hint è iniettato nel system prompt esistente.
- Review e fix post-patch: `generate_draft` in `generator.py` usava i seed solo se `question_type` era presente — allentata la condizione a `if seed_words:` per attivare `generate_question_candidates` anche su seed di tono puri. Aggiunta propagazione dei `TONE_SEEDS` al `generate_draft` dell'autopost in `scheduler.py`. Il tono ora influenza la catena Markov (non solo Groq) anche per la generazione casuale.
- 32 test passano.

## 2026-04-10 — sessione 5

- Applicata la migrazione operativa da Gemini a Groq per i task LLM del bot.
- Aggiunto package `cumbot/groq/` con service async `AsyncGroq`, refiner e chat provider.
- `mention_handler` ora usa `cumbot.groq.refiner.refine_draft()`.
- `ask_handler` ora usa `cumbot.groq.chat.ask_groq()`.
- Aggiunto comando admin `/groq on|off|status`, lasciando `/gemini` come alias legacy.
- Allineato anche l'autopost: `scheduler.py` usa ora il refiner Groq invece del vecchio import Gemini.
- Config aggiunta: `GROQ_API_KEY`, `GROQ_REFINER_MODEL`, `GROQ_ASK_MODEL`.
- Aggiornati `requirements.txt`, `.env.example` e `.env` con placeholder Groq.
- I file Gemini restano nel repo ma non sono piu sul path principale di esecuzione.

## 2026-04-10 — sessione 4

- Trainer: aggiunto filtro bot sender. Nuova `is_bot_sender(sender_id, display_name)`: controlla EXCLUDE_USER_IDS in config e nome che termina per "bot". Aggiunto a config `EXCLUDE_USER_IDS` (env var, default vuoto). Il loop di train_all ora skippa i messaggi da bot con reason "bot_sender".
- Trainer: aggiunto parametro `extra_messages` a `train_all()`. Permette di passare messaggi aggiuntivi (da live_corpus) in formato export-compatibile.
- DB: aggiunta `get_all_live_messages_for_training()` in state.py: esporta il live_corpus in formato `{from_id, from, type, text}` compatibile con il trainer.
- Retrain handler: ora chiama `get_all_live_messages_for_training()` e passa il risultato a `train_all()`. Il live corpus viene incorporato nei modelli base a ogni `/retrain`. Messaggio di risposta mostra i messaggi live aggiunti.
- register_chat: rimosso `autopost_enabled = excluded.autopost_enabled` dall'ON CONFLICT UPDATE. Previene reset involontari del toggle autopost su ogni messaggio in arrivo.
- Scoring: penalità `?` aumentata da -0.2 a -0.5. Differenziale `?` vs `.` ora 0.8 (era 0.5).
- Config: `MARKOV_CANDIDATE_COUNT` default aumentato da 8 a 12. Più candidati nel pool → maggiore probabilità di trovare alternative non-`?`.
- Nota operativa: il nuovo gruppo "La storia CUMtinua" (2026712691) è una registrazione vergine — le settings non sono perse ma mai configurate. Deve essere configurato separatamente con `/persona`, `/cooldown` ecc.

## 2026-04-10 — sessione 3

- Diagnostica fallback Gemini: qualsiasi eccezione (quota 429, safety block, network) era silente. Aggiunto LOGGER.warning in refiner.py con tipo errore e motivo; separato il caso `response=None` (safety block) dal caso eccezione. I log ora mostrano chiaramente perché cade il fallback. Limite noto: gemini-2.5-flash-lite free tier → 30 RPM / 1500 RPD.
- Post-processing maiuscole a metà frase: aggiunta `_lowercase_restart_capitals()` in generator.py, applicata a tutti i candidati prima dello scoring. Regola: abbassa la prima lettera di token capitalizzati mid-sentence (non preceduti da `.!?`) a meno che il token sia tutto-maiuscolo (acronimo) o abbia uppercase non in posizione 0 (nomi composti tipo "FkManu"). Nomi semplici tipo "Polina" vengono abbassati — tradeoff accettabile dato che quei candidati sono già 1-restart.
- Intent detection resa elastica: `detect_question_type()` usa ora `re.search` con word boundary invece di `startswith`. Funziona su "ma chi sei?", "dimmi quando arriva", "non so come fare" e frasi senza "?". La prima keyword trovata (left-to-right) determina il tipo.

## 2026-04-10 — sessione 2

- Review degli output post-tuning: question bias al 87% (corpus artifact), 1-restart ancora al 53% (penalità insufficiente).
- Scoring: `punctuation_bonus` diviso: `?` → -0.2, `.`/`!` → +0.3. Differenziale 0.5 sufficiente a preferire affermazioni a parità di qualità.
- Scoring: `restart_penalty` primo restart alzato da 1.0 a 2.0. Candidati 1-restart ora perdono quasi sempre contro 0-restart equivalenti; i collage peggiori ('dicendo Perché...', score 2.49) escono sotto threshold.
- Gemini refiner riscritto: da "riscrivere" a "amplificare". Nuovo system prompt esplicita: mantieni parole chiave, stesso numero di parole ± 3, no rewrite, no emoji spam, no doppia punteggiatura. Aggiunto anchor lunghezza nel prompt utente.
- 24 test passati senza regressioni.

## 2026-04-10

- Analisi statistica del corpus Markolino (bot di riferimento, user5448250840, 15518 messaggi utili):
  - Mediana 9 parole, media 11.6, p90 23; 27% output ≤5 parole.
  - Distribuzione restart: 87% zero restart, 8.8% un restart, 2.3% due restart. Molto più pulito del nostro (28% zero restart su ultimi 100 draft).
  - Overlap contestuale medio 11.5%; 60% dei messaggi hanno zero overlap con le 5 righe precedenti. Conferma: Markolino NON fa context seeding esplicito — la sua precisione è un effetto del corpus ampio e degli output brevi e coerenti.
  - Risposte alle domande (298 campioni): non mostrano pattern di risposta strutturata per tipo; la "pertinenza" è effetto della brevità e del corpus ricco, non di logiche question-aware.
- Identificati due problemi nel nostro scoring che causano output troppo lunghi e troppi collage:
  1. `target_chars=90` / `target_words=14` spingono verso frasi lunghe; aggiornati a 55/9.
  2. I candidati a 2 restart ancora passavano la threshold 2.5 (score medio ~3.3); nuova penalità li porta a -1.76 di media.
- Modificato `_score_candidate()` in `generator.py`: nuova formula restart_penalty, target_chars=55, target_words=9.
- Abbassato `MARKOV_DRAFT_MAX_CHARS` default da 180 a 120 in `config.py`.
- 24 test passati senza regressioni.

## 2026-04-07

- Letto e reinterpretato `docs/project.md` nel contesto del repo reale.
- Decisa una struttura per-chat invece del semplice config key/value globale.
- Scelto stack Gemini moderno con `google-genai`.
- Creato scaffold completo del progetto con runtime Telegram async, DB SQLite, scheduler e handlers.
- Implementato trainer/generatore Markov con supporto persona multipla basata su Telegram user ID.
- Aggiunti documenti operativi permanenti in `docs/`.
- Creata `.venv` locale e verificato il progetto con `pytest`: 6 test passati.
- Validato il primo export reale Telegram e completato il training iniziale con 652048 messaggi utili e 96 personas addestrate.
- Aggiunto toggle admin `/gemini` per troubleshooting per-chat e accorciate le bozze Markov di default.

## 2026-04-09 — sessione 3

- Analizzato il DB in profondità con scoring numerico sui draft reali. Trovata la causa principale dei collage: `restart_penalty` era `max(0, r-1)*0.35`, permetteva a messaggi con 2 frasi incollate di fare score 5.8-6.5 e passare il filtro.
- Deciso di alzare il moltiplicatore da `0.35` a `4.0` (1 restart è ancora gratuito — stile chat italiano; il 2° costa 4 punti — quasi tutti i collage crollano sotto threshold 2.5).
- Riprogettato la gestione del contesto su due livelli:
  - **Contesto immediato** (`IMMEDIATE_CONTEXT_SIZE=3`, ultimi 3 msg): usato per topic extraction e seed delle domande, non mixato nel modello.
  - **Live corpus** ridotto da 100 a `LIVE_CORPUS_LIMIT=30` messaggi, peso abbassato da 0.4 a `LIVE_CORPUS_WEIGHT=0.2`; threshold abbassata a `LIVE_CORPUS_MIN_MESSAGES=15`.
- Riprogettata la logica dei seed per domande: invece di parole fisse per tipo, si estraggono topic words dal contesto immediato dei 2-3 messaggi precedenti.
  - Nuovo `extract_topic_seeds(immediate_context, question_type)` in `intent.py` con stopwords italiane (~70 parole) e name-from-text extraction per "chi?".
  - I `QUESTION_SEEDS` fissi diventano fallback se il contesto non produce seed utili.
  - Per "chi?": combina nomi propri estratti dal testo (parole capitalizzate non inizio frase) + speaker names dai metadati.
- Aggiunto `IMMEDIATE_CONTEXT_SIZE` e `LIVE_CORPUS_LIMIT` a config.py.
- Fixato bug Gemini: aggiunta istruzione esplicita nel system prompt per vietare formato "username: testo" e trascrizioni chat.
- 24 test passati senza regressioni.

## 2026-04-09 — sessione 2

- Analizzato il DB degli output generati per capire lo stato della pipeline.
- Introdotto riconoscimento domande (puro Markov, senza Gemini):
  - nuovo modulo `cumbot/markov/intent.py` con `detect_question_type()`, `get_context_names()` e `QUESTION_SEEDS`;
  - tipi gestiti: chi / cosa / come / quando / perché / dove / quale / quanto + fallback "generic";
  - per "chi?" usa i nomi reali degli speaker dal contesto recente come semi;
  - per gli altri tipi usa una lista di parole-seme plausibili per risposta;
  - generazione tramite `make_sentence_with_start()` di markovify con fallback alla generazione normale se non trova candidati validi;
  - la logica di intent detection e gestione seed e integrata nel `mention_handler`.
- Introdotto corpus live per contestualizzazione dinamica della generazione:
  - nuova tabella `live_corpus` in SQLite: ogni messaggio testuale in arrivo viene persistito;
  - il middleware `context_middleware` scrive in `live_corpus` in modo fire-and-forget (`asyncio.ensure_future`);
  - nuovo `build_live_model()` nel generator: costruisce un modello markovify temporaneo dai messaggi recenti;
  - i modelli live vengono combinati con il modello base tramite `markovify.combine()` con peso configurabile (`LIVE_CORPUS_WEIGHT=0.4`);
  - threshold minima: 30 messaggi per state_size=1, 60 per state_size=2;
  - anche il scheduler (autopost cooldown) usa il live corpus;
  - due nuovi parametri in config: `LIVE_CORPUS_WEIGHT` e `LIVE_CORPUS_MIN_MESSAGES`.
- Aggiunto subcommand `db-stats` al tool CLI `report.py`:
  - statistiche aggregate sugli output generati (totale, per trigger type, reaction rate, gemini usage, lunghezza media, messaggi live corpus);
  - lista dei top 10 messaggi piu reazionati con emoji breakdown;
  - utilizzo: `python -m cumbot.markov.report db-stats [--chat-id ID] [--limit N]`.
- 24 test passati senza regressioni.

## 2026-04-09

- Letto `docs/markov_best_practices.md` e confrontato con la pipeline attuale basata su `markovify`.
- Creato un piano dedicato di modernizzazione in `docs/markov_modernization_plan.md`.
- Aggiunto monitoring persistente dei messaggi generati e comando admin `/outputs`.
- Avviato il primo incremento di modernizzazione Markov: normalizzazione selettiva, metadata piu ricchi, candidate generation con ranking e CLI locale di sampling.
- Rafforzati i filtri del corpus reale e aggiunto report locale `analyze` per misurare rumore, keep rate e motivi di scarto.
- Aggiunta la risoluzione di `@user` in mention reali e un ranking piu severo contro i collage di frammenti troppo slegati.
- Aggiunto un fine tuning leggero di superficie sugli output finali Markov: compressione di duplicati banali, ammorbidimento dei restart a meta frase e punteggiatura finale minima.
- Deciso che il futuro feedback tramite reaction considerera tutte le reaction come positive e verra usato solo come segnale leggero di ranking.
- Sostituito l'autopost a timer con un cooldown per chat basato sul numero di messaggi umani, con range configurabile.
- Implementato il tracking delle reaction direttamente sui messaggi generati monitorati e aggiunto comando admin `/reactions`.
