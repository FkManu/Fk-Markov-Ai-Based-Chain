# Chat-Scoped Training Plan

## Obiettivo

Rendere il bot realmente separato per gruppo sul piano del training, dei modelli e
dei retrain periodici, senza rompere le feature gia operative di contesto live.

Il risultato desiderato e:

- ogni chat ha i suoi modelli Markov;
- ogni chat ha il suo corpus storico consolidato;
- il retrain periodico riparte da dove era arrivato;
- il contesto live recente continua a funzionare come oggi;
- non si duplicano inutilmente i dati e non si contamina una chat con un'altra.

## Principi

1. `live_corpus` resta un **corpus caldo**.
   Serve per contesto recente, seed extraction e live mixing a runtime.
   Non deve diventare il dataset storico principale.

2. `training_corpus` diventa il **corpus freddo canonico**.
   E la fonte di verita per il rebuild dei modelli di una chat.

3. I modelli in `models/` diventano **namespaced per chat**.
   Finche questo non succede, qualsiasi retrain resta potenzialmente contaminante.

4. Il retrain resta un **full rebuild del modello per chat**.
   `markovify` non supporta update incrementali veri del JSON del modello.
   L'incremental tracking ci fa risparmiare ingest e dedup, non la CPU del rebuild.

## Stato attuale

Oggi il sistema e in una fase intermedia:

- `live_corpus` esiste gia e salva i messaggi testuali live;
- `/importlive` e `/retrain` sono gia stati resi chat-scoped sul dataset live;
- i modelli runtime, pero, sono ancora caricati da `models/state_1`, `models/state_2`
  e `models/metadata.json`, quindi restano globali;
- GIF e sticker hanno gia una loro persistenza separata e gia capata per chat.

Conclusione: la direzione e giusta, ma la separazione per chat non e ancora completa.

## Decisioni chiave

### 1. Namespace modelli per chat

Nuova struttura:

```text
models/
  chats/
    -1002026712691/
      state_1/
        global.json
        <persona_id>.json
      state_2/
        global.json
        <persona_id>.json
      metadata.json
    -1002097316223/
      ...
```

Il runtime deve caricare i modelli in base al `chat_id` corrente, con cache in memoria
per chat. L'assenza di modelli per una chat deve essere gestita in modo esplicito
e leggibile nei log.

### 2. `training_corpus` come fonte di verita

Nuova tabella concettuale:

- `chat_id`
- `source_kind` (`export`, `live`)
- `source_key`
- `user_id`
- `username`
- `text`
- `created_at`
- `inserted_at`

Vincoli:

- `UNIQUE(chat_id, source_key)`

Questo evita duplicati e rende possibile riimportare export o consolidare live message
senza sporcare il dataset.

### 3. `chat_training_state`

Nuova tabella concettuale:

- `chat_id`
- `last_retrain_at`
- `last_live_corpus_id`
- `last_export_fingerprint`
- `last_export_path`
- `training_corpus_size`
- `models_path`

Serve a sapere:

- da dove riprendere;
- quale export e stato consolidato;
- quanti dati sono gia stati assorbiti;
- quale namespace modelli e attivo per quella chat.

### 4. Dedup robusto

Per `source_key`:

- export:
  - preferenza a `export:<message_id>` se il message id e presente nell'export;
  - fallback a hash stabile di `sender_id|created_at|text` se manca.
- live:
  - `live:<row_id_live_corpus>`

Questa strategia evita collisioni banali e consente import ripetuti senza duplicare.

### 5. Cap sul corpus freddo

Il cap va su `training_corpus`, non su `live_corpus`.

Nuova env:

```env
TRAINING_CORPUS_MAX_PER_CHAT=1000000
```

Policy:

- trim FIFO per chat;
- il piu vecchio viene eliminato quando entra il nuovo oltre soglia;
- applicato sia in consolidamento live sia in import export.

### 6. `live_corpus` resta piccolo e operativo

`live_corpus` mantiene il ruolo attuale:

- hot context;
- recent topic seeding;
- live model per derive tematiche locali;
- persistenza dei messaggi appena arrivati.

Non deve essere il luogo dove accumuliamo all'infinito lo storico della chat.

## Roadmap di implementazione

## Step 1 — Namespace modelli per chat

Scopo:

- separare davvero il runtime per gruppo.

Interventi:

- introdurre un path resolver per i modelli dato `chat_id`;
- salvare i modelli sotto `models/chats/<chat_id>/...`;
- cambiare `load_models()` e il generatore per lavorare per chat;
- aggiornare `/retrain` per scrivere i modelli nel namespace giusto.

Accettazione:

- fare retrain della chat A non cambia i modelli della chat B;
- `/status` o log mostrano quale namespace modelli e attivo per la chat.

Stato:

- completato il namespace base `models/chats/<chat_id>/...`;
- `train_all(..., chat_id=...)` scrive nel namespace della chat;
- runtime e generazione (`mention`, `reply`, `autopost`) usano `chat_id` per caricare i modelli corretti;
- `/status` mostra il path del namespace modelli attivo per la chat.

## Step 2 — Introdurre `training_corpus` e `chat_training_state`

Scopo:

- separare corpus caldo e corpus freddo;
- avere una base canonica per il training di ogni chat.

Interventi:

- aggiungere le nuove tabelle;
- aggiungere helper DB per inserimento, dedup e lettura per chat;
- iniziare a salvare lo stato del training per chat.

Accettazione:

- per ogni chat esiste un corpus consolidato leggibile e deduplicato;
- esiste uno stato che dice dove il retrain e arrivato.

Stato:

- aggiunte le tabelle `training_corpus` e `chat_training_state` in SQLite;
- aggiunti helper DB per inserimento deduplicato, replace per `source_kind`,
  lettura del corpus freddo e lettura/scrittura dello stato per chat;
- `/retrain` salva ora anche un primo checkpoint per chat
  (`last_retrain_at`, `last_live_corpus_id`, `last_export_path`, `models_path`);
- il corpus freddo esiste gia a livello architetturale, ma non e ancora alimentato
  da `/importlive`: quello arriva nello Step 3.

## Step 3 — Reindirizzare `/importlive`

Scopo:

- usare l'export manuale per popolare il corpus freddo giusto.

Interventi:

- far scrivere `/importlive` in `training_corpus` invece che in `live_corpus`;
- `reset` sostituisce solo la parte `source_kind='export'` della chat target;
- `append` aggiunge mantenendo dedup;
- opzionalmente lasciare `live_corpus` intatto.

Accettazione:

- un nuovo export aggiorna il dataset storico senza cancellare i live gia raccolti;
- reimportare lo stesso export non duplica.

Stato:

- `/importlive` scrive ora nel `training_corpus` invece che nel `live_corpus`;
- `reset` sostituisce solo la parte `source_kind='export'` della chat target;
- `append` aggiunge righe export con dedup su `(chat_id, source_key)`;
- `/retrain` usa `training_corpus` come base se presente, e somma sopra il `live_corpus`
  recente come layer caldo transitorio;
- se il `training_corpus` della chat e ancora vuoto, `/retrain` resta retrocompatibile
  e cade sull'export file diretto.

## Step 4 — Consolidamento incrementale del live

Scopo:

- non rileggere tutto il `live_corpus` a ogni retrain.

Interventi:

- prendere solo i record con `id > last_live_corpus_id`;
- inserirli in `training_corpus` con `source_kind='live'`;
- aggiornare `last_live_corpus_id` dopo il rebuild riuscito.

Accettazione:

- il job periodico riparte da dove si era fermato;
- se non trova stato precedente, parte da zero.

Stato:

- `/retrain` consolida ora nel `training_corpus` solo i messaggi del `live_corpus`
  con `id > last_live_corpus_id`;
- i messaggi live consolidati usano `source_kind='live'` e `source_key='live:<row_id>'`;
- se non esiste ancora uno stato precedente per la chat, il consolidamento parte
  dall'inizio del `live_corpus`;
- il checkpoint `last_live_corpus_id` viene avanzato solo dopo un retrain riuscito;
- se il retrain fallisce dopo l'insert, il dedup per `source_key` evita duplicati
  al tentativo successivo;
- se esiste gia un corpus freddo sufficiente, il retrain puo partire anche senza
  export file manuale disponibile.

## Step 5 — FIFO cap su `training_corpus`

Scopo:

- impedire che il corpus freddo cresca senza controllo.

Interventi:

- aggiungere `TRAINING_CORPUS_MAX_PER_CHAT`;
- trim automatico FIFO per chat in ogni punto di insert massivo o incrementale.

Accettazione:

- il corpus di una chat non supera mai il limite configurato;
- il trim elimina sempre le righe piu vecchie.

Stato:

- `trim_training_corpus(chat_id, max_rows)` in `db/state.py`: DELETE FIFO sulle righe
  con id piu basso fino a rientrare nel limite.
- `TRAINING_CORPUS_MAX_PER_CHAT=1000000` in `config.py` (configurabile via env).
- trim chiamato in `/retrain` dopo il consolidamento live e in `/importlive` dopo l'insert.

## Step 6 — Scheduler retrain per chat

Scopo:

- mantenere la chat allineata senza interventi manuali continui.

Interventi:

- job giornaliero per chat;
- consolidamento solo dei nuovi live message;
- rebuild completo dei modelli della chat;
- guardrail minimi:
  - lock per chat;
  - soglia minima di nuovi messaggi;
  - finestra oraria configurabile;
  - log e stato aggiornati solo su successo.

Accettazione:

- il retrain automatico non rilancia rebuild inutili;
- un errore su una chat non blocca le altre.

Stato:

- `cumbot/jobs/retrain.py`: `scheduled_retrain(context)` — job PTB.
  - Gira ogni ora, entra nella logica solo se l'ora locale rientra in `RETRAIN_SCHEDULE_HOUR`.
  - Per ogni chat di gruppo: consolida live rows con `id > last_live_corpus_id`, trim FIFO,
    rebuild modelli, aggiorna `chat_training_state`.
  - Skip silenzioso se nuovi messaggi < `RETRAIN_MIN_NEW_MESSAGES`.
  - Errori per singola chat loggati, non bloccano le altre.
- `main.py`: `job_queue.run_repeating(scheduled_retrain, interval=3600, first=60)`.
- Nuove env: `RETRAIN_SCHEDULE_HOUR=3` (ora o range "2-4"), `RETRAIN_MIN_NEW_MESSAGES=50`.

## Comandi e UX da riallineare

Durante questa roadmap andranno riallineati:

- `/retrain`
- `/importlive`
- `/status`
- `/setup` se vogliamo mostrare stato training e ultimo retrain
- eventuale futuro `/syncchat`

## Limiti noti e tradeoff

1. Il rebuild Markov per una chat resta costoso in funzione della dimensione del corpus.
   L'incremental tracking riduce ingest e dedup, non elimina il rebuild completo.

2. `training_corpus` duplica il testo rispetto a `live_corpus` e rispetto ai JSON dei modelli.
   Questa duplicazione e accettabile se consideriamo i JSON come cache rigenerabile
   e `training_corpus` come storage canonico.

3. Finche non completiamo almeno Step 1 e Step 2, l'automazione del retrain va evitata.

## Ordine operativo consigliato

1. Step 1 — namespace modelli per chat
2. Step 2 — `training_corpus` + `chat_training_state`
3. Step 3 — `/importlive` sul corpus freddo
4. Step 4 — consolidamento incrementale del live
5. Step 5 — cap FIFO
6. Step 6 — scheduler retrain

## Decisione finale

Le prossime patch seguiranno questo piano.

Prima chiudiamo l'isolamento architetturale per chat.
Solo dopo introduciamo il retrain periodico.
