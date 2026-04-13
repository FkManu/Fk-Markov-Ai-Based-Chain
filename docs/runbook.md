# Runbook

## Comandi admin

- `/persona [chat:<chat_id>] <user_id,user_id,...>`
- `/persona [chat:<chat_id>] reset`
- `/cooldown [chat:<chat_id>] <min_messaggi> [max_messaggi]`
- `/interval [chat:<chat_id>] <min_messaggi> [max_messaggi]` alias legacy
- `/groq [chat:<chat_id>] <on|off|status>`
- `/groqtemp [chat:<chat_id>] <0-2 | status | reset>`
- `/setup` — pannello inline per configurare rapidamente una chat (Groq, persona, cooldown)
- `/annuncio` — gestione annunci programmati (giornalieri, a orario fisso, per chat)
- `/draft [chat:<chat_id>] [limit]` — ultimi N output con draft Markov e output Groq a confronto (✏️ = modificato da Groq)
- `/outputs [chat:<chat_id>] [limit]`
- `/reactions [chat:<chat_id>] [limit]`
- `/importlive [chat:<chat_id>] [reset|append] [export_path]`
- `/retrain [chat:<chat_id>] [export_path]`
- `/status`
- `/status <chat_id>`

## Note operative

- In gruppo, i comandi agiscono sulla chat corrente.
- In privato, i comandi chat-scoped richiedono di norma `chat_id` come primo argomento.
- In qualunque chat puoi anche forzare un target esplicito con il prefisso `chat:<chat_id>`.
- L'autopost automatico lavora solo su chat di tipo gruppo o supergruppo gia note al bot.
- L'autopost non e piu basato sul tempo: scatta quando la chat accumula abbastanza messaggi umani rispetto al cooldown configurato.
- Se il provider LLM non e disponibile per `Simula`, il bot usa il testo Markov grezzo.
- `/ask` usa `compound-beta` (con web search integrata Groq) come modello primario, con catena di fallback automatica: `compound-beta` → `compound-beta-mini` → `llama-3.3-70b-versatile`. Qualsiasi errore su un modello passa al successivo senza interruzione.
- Se tutti i modelli `/ask` falliscono per rate limit, il bot risponde con un messaggio esplicito.
- `GROQ_ASK_API_KEY` è una chiave Groq dedicata per `/ask` (separata da `GROQ_API_KEY` usata da refiner e classifier). Se non impostata, entrambi usano `GROQ_API_KEY`. Tenerla separata isola i rate limit di `/ask` dall'impattare il refiner.
- **Conversazione multi-turn `/ask`**: rispondere a un messaggio del bot generato da `/ask` continua la conversazione con Groq (invece di passare al Markov). La storia è mantenuta in-memory con TTL 2 ore. Ogni turno viene loggato con `notes="ask_continuation"`.
- Il provider LLM attivo per refine e `/ask` e ora Groq; il fallback su bozza Markov resta attivo in caso di errore o rate limit.
- Opzionale: `GROQ_CLASSIFY_ENABLED=true` attiva un classifier intent leggero solo sulle mention/reply non gia coperte dal fast path regex (azioni esplicite e domande specifiche restano locali). Label usati: `roast`, `reaction`, `agreement`, fallback `generic`.
- `/importlive` importa un export Telegram manuale dentro `training_corpus` per una chat specifica. Modalita default `reset` (rimpiazza solo la parte `export` del corpus freddo di quella chat); `append` aggiunge in coda con dedup. Non tocca i modelli finche non lanci `/retrain`.
- Se `EXPORT_PATH` non esiste ma in `data/` c'e un solo `result.json`, il trainer lo usa automaticamente.
- `/retrain` ora usa il `live_corpus` della sola chat target. Se vuoi usare un export diverso da `EXPORT_PATH`, passalo come argomento finale.
- I modelli Markov runtime sono ora separati per chat sotto `models/chats/<chat_id>/...`. Un retrain della chat A non sovrascrive piu i modelli della chat B.
- Il DB contiene ora anche `training_corpus` (corpus freddo canonico per chat) e `chat_training_state` (checkpoint dell'ultimo retrain).
- Se per una chat esiste gia `training_corpus`, `/retrain` lo usa come base canonica e ci somma sopra il `live_corpus` recente. Se il corpus freddo e ancora vuoto, `/retrain` resta retrocompatibile e usa direttamente l'export file.
- `/retrain` consolida nel `training_corpus` solo i nuovi messaggi live della chat rispetto a `last_live_corpus_id`. Se non esiste ancora uno stato precedente, parte da zero e assorbe tutto il live disponibile.
- Se `Groq` e su `off`, mention, reply e autopost usano direttamente la bozza Markov grezza.
- `/groqtemp` regola la temperatura Groq per singola chat e viene usato sia dal refiner (mention/reply/autopost) sia da `/ask`. Accetta anche numeri con virgola, per esempio `0,7`.
- In chat privata, `/groqtemp` puo anche essere lanciato senza `chat_id`: il bot mostra i bottoni con le chat note e applica li `status`, `reset` o il valore richiesto.
- Gli output del bot vengono salvati in `runtime/cumbot.sqlite3`, tabella `generated_messages`, con draft, output finale, contesto recente e conteggio reaction.
- Il bot reagisce randomicamente ai messaggi del gruppo (probabilità `REACTION_PROBABILITY`, default 6%). Richiede che il bot sia admin o che il gruppo abbia le reazioni aperte.
- Le GIF inviate in chat vengono salvate in `gif_corpus` (dedup per file). Se ≥ `GIF_TRIGGER_COUNT` GIF negli ultimi `GIF_CONTEXT_MINUTES` minuti, il bot può reinviarne una su autopost o mention.
- Se `ALLOWED_CHAT_IDS` e configurato nel `.env`, il bot tace completamente nelle chat non in lista. Lasciare vuoto per nessuna restrizione.
- Per `ALLOWED_CHAT_IDS` usa preferibilmente gli ID canonici Telegram (`-100...` per i supergruppi). Il runtime tollera anche lo shorthand positivo senza prefisso `-100`, ma e meglio salvare il valore completo.
- `/setup` apre un pannello inline per configurare rapidamente Groq, persona e cooldown di qualsiasi chat nota al bot.
- `/annuncio` apre un pannello inline per creare/gestire annunci programmati (testo libero, orario fisso giornaliero). In gruppo apre direttamente la lista annunci per quella chat; in privato chiede prima di selezionare la chat. Il bot usa `ANNOUNCEMENT_TIMEZONE` per confrontare l'ora corrente con l'orario dell'annuncio (default `Europe/Rome`) e la UI mostra esplicitamente il timezone italiano.
- Se una bozza contiene `@user`, il bot prova a trasformarlo in una mention reale usando prima l'utente che ha triggerato il messaggio e poi il contesto recente della chat.
- Per ricevere gli update reaction da Telegram, il bot deve essere admin nel gruppo.
- Il bot rileva il tono del contesto recente (ultimi 5 messaggi): se aggressivo (insulti presenti) sia la catena Markov che Groq orientano l'output in direzione nervosa/tagliente; se playful (≥2 "ahah/lol" in 5 msg) verso ironica/divertente. Funziona su mention, reply e autopost. Zero chiamate Groq extra.
- Se `GROQ_CLASSIFY_ENABLED=true`, sulle mention/reply non coperte da action regex o da una domanda specifica parte anche una classificazione intent Groq: `roast` aggiunge seed aggressivi e può spostare il tone verso `aggressive`; `reaction` e `agreement` aggiungono seed lessicali leggeri senza stravolgere la Markov.
- **Reaction/agreement breve**: quando `intent_label in (reaction, agreement)` e l'input è ≤2 parole, il bot bypassa Markov e Groq. Con probabilità 35% invia uno sticker dal corpus; altrimenti risponde con una frase breve fissa ("ok", "ci sta", "sei un grande", "diglielo", ecc.). Loggato con `notes="reaction_short"`.
- **Roast — contrattacco**: quando `intent_label=roast`, il refiner Groq riceve l'insulto originale dell'utente come contesto aggiuntivo e la istruzione di formulare un contrattacco diretto in prima persona, non solo di amplificare la bozza.
- Il refiner Groq non traduce mai termini inglesi usati come slang nel testo italiano (es. "bro", "fra", "cringe", "vibe", "lol", "mid"). La regola è esplicita nel system prompt di `groq/refiner.py`.
- **`insulta [target]`**: il nome del soggetto da insultare viene estratto con priorità: `@username` → parola capitalizzata (es. "Rocco" da "insulta quel coglione di Rocco") → fallback prime 3 parole. Il nome diventa seed primario per la generazione Markov.
- Il tone hint Groq è condizionale: se la bozza contiene già insulti li mantiene/intensifica, ma **non ne aggiunge di nuovi** se la bozza è neutrale. Questo evita il problema di Groq che "settava il tono" su ogni output.
- Gli sticker inviati in chat vengono salvati in `sticker_corpus` (dedup per file). Il bot può reinviarne uno su mention (prob `STICKER_RESEND_PROBABILITY`, default 8%) o su autopost (stessa prob). La GIF su mention ora è un reply al messaggio trigger invece di un messaggio standalone.
- Il refiner Groq usa come default `0.76` (abbassata progressivamente da `1.15`). Leve operative: system prompt in `groq/refiner.py`, default env e override per-chat via `/groqtemp`. `/draft` resta il tool principale per monitorare l'impatto del refiner sugli output.
- Default attuali: `GROQ_REFINER_TEMPERATURE=0.76`, `GROQ_ASK_TEMPERATURE=0.6`. Il comando `/groqtemp` sovrascrive per-chat il comportamento Groq senza dover modificare il `.env`.
- Il bot filtra dal corpus di training i messaggi che un utente ha inoltrato da fonti esterne (`forwarded_from_id != from_id`). Evita che testo di altri venga attribuito alla persona dell'inoltro.
- I modelli Markov usano ora `parsed_sentences` per la costruzione: ogni messaggio è garantito come frase indipendente. Il sentence splitter nativo di markovify fondeva messaggi senza punteggiatura finale o seguiti da minuscola, creando bigrammi cross-messaggio indesiderati. Dopo una modifica ai modelli (es. `/retrain`) questo problema è eliminato alla radice.
- `avoid_question_ending` è ora sempre attivo sulle mention/reply (prima era attivo solo se l'input era rilevato come domanda). Comportamento: pool candidati x2 + filtro su candidati che terminano con `?`.
- Penalty `?` in scoring Markov alzata da -0.5 a -2.0: i candidati senza punto interrogativo emergono molto più facilmente nel ranking anche senza il filtro esplicito.
- Il refiner Groq non aggiunge mai `?` a draft che non termina già con `?` (regola esplicita nel system prompt). Evita i casi in cui Groq trasformava affermazioni in domande.
- Se il modello LLM ritorna un rifiuto testuale (Llama safety guardrail: "Mi dispiace non posso...", "Sorry...", ecc.), il refiner fa automaticamente fallback al draft Markov. Prima il rifiuto veniva inviato in chat.
- Se `@user` è presente nella bozza Markov e Groq lo rimuove, il post-processing lo riappende in coda all'output (`PLACEHOLDER` check in `refiner.py`).
- `/status` mostra anche il namespace modelli attivo della chat corrente, utile per verificare che il retrain stia usando il path giusto.
- `/status` mostra anche l'ultimo retrain noto per la chat e l'ultimo export usato, se esiste gia un checkpoint in `chat_training_state`.

## Tool CLI locali

```bash
# Riepilogo modelli caricati
python -m cumbot.markov.report summary [--chat-id <chat_id>]

# Genera N candidati Markov raw per una persona
python -m cumbot.markov.report sample [--chat-id <chat_id>] --persona <user_id> --count 8

# Analizza corpus export (skip reasons, keep rate, top sender)
python -m cumbot.markov.report analyze [--export path/to/export.json] [--limit N]

# Statistiche DB sugli output generati
python -m cumbot.markov.report db-stats [--chat-id <chat_id>] [--limit 500]
```

`db-stats` mostra: totale messaggi generati, distribuzione per trigger type, reaction rate, groq usage rate, percentuale bozze modificate da Groq, lunghezza media output, dimensione corpus live, top 10 messaggi piu reazionati.

## Gestione VPS con systemd

Il file pronto da usare e [`deploy/cumbot.service`](/home/ubuntu/Desktop/CumBot/deploy/cumbot.service).

Installazione una tantum:

```bash
sudo cp /home/ubuntu/Desktop/CumBot/deploy/cumbot.service /etc/systemd/system/cumbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now cumbot
```

Comandi utili:

```bash
sudo systemctl status cumbot
sudo systemctl restart cumbot
sudo systemctl stop cumbot
sudo systemctl start cumbot
journalctl -u cumbot -f
```

Se cambi `deploy/cumbot.service`, ricarica systemd prima del restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart cumbot
```

## Pubblicazione GitHub sicura

Prima di creare una repo GitHub:

- verifica che `.env`, `data/`, `models/` e `runtime/` restino esclusi da `.gitignore`;
- controlla sempre `git status` prima del primo commit;
- preferisci una repo privata al primo push;
- usa `README.md` come descrizione pubblica del progetto, non i dataset reali.

Se sulla VPS `gh` e autenticato con l'account sbagliato:

```bash
gh auth logout -h github.com -u <account_attuale>
gh auth login
```

Se vuoi riallineare anche l'identita Git usata nei commit:

```bash
git config --global user.name "fkmanu"
git config --global user.email "tua-email@esempio.com"
```

Flusso tipico:

```bash
cd /home/ubuntu/Desktop/CumBot
git init
git add .
git status
git commit -m "Initial commit"
gh repo create fkmanu/cumbot --private --source=. --remote=origin --push
```

## Corpus live

Funziona su due livelli:

- **Contesto immediato** (ultimi `IMMEDIATE_CONTEXT_SIZE=5` messaggi, default): topic words e nomi estratti per guidare la generazione su domande e su input ≥4 parole. Non viene mixato nel modello.
- **Corpus recente** (ultimi `LIVE_CORPUS_LIMIT=30` messaggi, peso `LIVE_CORPUS_WEIGHT=0.2`): mini-modello markovify combinato col base model per deriva tematica. Attivo da `LIVE_CORPUS_MIN_MESSAGES=15` messaggi in poi.

Variabili d'ambiente tunable:
```
LIVE_CORPUS_LIMIT=30          # quanti msg usare per il corpus recente
LIVE_CORPUS_WEIGHT=0.2        # peso live model nella combine
LIVE_CORPUS_MIN_MESSAGES=15   # minimo msg per attivare live model
IMMEDIATE_CONTEXT_SIZE=5      # quanti msg per topic/seed extraction
ALLOWED_CHAT_IDS=             # whitelist chat; vuoto = nessuna restrizione
REACTION_PROBABILITY=0.06     # probabilita che il bot reagisca a un msg in arrivo
REACTION_EMOJI=😂,💀,🔥,...     # set emoji per reactions randomiche
GIF_CONTEXT_MINUTES=15        # finestra temporale per contare GIF recenti
GIF_TRIGGER_COUNT=3           # quante GIF recenti attivano il reinvio
GIF_RESEND_PROBABILITY=0.4    # probabilita GIF resend su autopost
GIF_MENTION_PROBABILITY=0.15  # probabilita GIF resend su mention
GIF_CORPUS_MAX=200            # GIF massime salvate per chat
STICKER_RESEND_PROBABILITY=0.08  # probabilita sticker resend su mention/autopost
STICKER_CORPUS_MAX=100           # sticker massimi salvati per chat
ANNOUNCEMENT_TIMEZONE=Europe/Rome  # timezone per gli orari degli annunci
GROQ_API_KEY=                 # chiave API Groq (refiner + classifier)
GROQ_ASK_API_KEY=             # chiave Groq dedicata per /ask (opzionale, isola rate limit)
GROQ_REFINER_MODEL=llama-3.3-70b-versatile
GROQ_ASK_MODEL=llama-3.3-70b-versatile   # fallback finale /ask (no web search)
GROQ_COMPOUND_MODEL=compound-beta         # modello primario /ask (web search integrata)
GROQ_COMPOUND_MINI_MODEL=compound-beta-mini  # fallback intermedio /ask
GROQ_REFINER_TEMPERATURE=0.76 # default refiner Groq
GROQ_ASK_TEMPERATURE=0.6      # default /ask Groq
GROQ_CLASSIFY_ENABLED=false   # classifier intent Groq opzionale sulle mention/reply
TRAINING_CORPUS_MAX_PER_CHAT=1000000  # cap FIFO corpus freddo per chat
RETRAIN_SCHEDULE_HOUR=3       # ora locale (o range "2-4") per l'auto-retrain giornaliero
RETRAIN_MIN_NEW_MESSAGES=50   # min nuovi msg live per avviare il rebuild automatico
```

## Annunci programmati (`/annuncio`)

Feature completamente separata da Markov/Groq: invia testo statico a orari fissi giornalieri.

**Flusso inline:**
1. `/annuncio` in gruppo → lista annunci di quella chat
2. `/annuncio` in privato → selezione chat → lista annunci
3. "➕ Nuovo annuncio" → preset orario → l'admin invia il testo in chat privata → salvato
4. Ogni annuncio esistente: toggle on/off · modifica testo · modifica orario · elimina (con conferma)

**Orari disponibili (preset):** 00:00, 01:00, 07:00, 08:00, 12:00, 18:00, 20:00, 21:00, 22:00, 23:00

**Come funziona il job:** gira ogni 60s; ottiene l'ora locale in `ANNOUNCEMENT_TIMEZONE`; interroga `get_due_announcements(hour, minute)`; fa `send_message` per ogni annuncio abilitato. Gli errori di invio (es. bot non admin) vengono loggati ma non bloccano gli altri annunci.

**Tabella SQLite:** `announcements(id, chat_id, text, hour, minute, enabled, created_at)`

**Nota:** gli annunci non conoscono il giorno della settimana — scattano ogni giorno all'orario impostato. Per sospendere temporaneamente un annuncio usare il toggle ⏸.

## Riconoscimento domande

- Quando il bot viene triggerato da una domanda riconoscibile, usa `make_sentence_with_start()` per orientare la risposta.
- Tipi supportati: `chi` / `cosa` / `come` / `quando` / `perché` / `dove` / `quale` / `quanto`.
- I seed hanno due livelli di priorità (merge con dedup, input prima):
  1. **Seed dall'input** (`extract_seeds_from_input`): topic words o nomi propri estratti direttamente dal testo della domanda, dopo aver rimosso il @mention del bot.
  2. **Seed dal contesto** (`extract_topic_seeds`): topic words dagli ultimi `IMMEDIATE_CONTEXT_SIZE` messaggi precedenti; per "chi?" include anche i nomi degli speaker.
- Le parole-seme fisse in `QUESTION_SEEDS` sono usate solo come fallback se né input né contesto producono seed validi.
- Per input ≥4 parole **senza** question_type riconosciuto, il seeding contestuale è comunque attivo (topic words estratti da input + contesto immediato), con priorità sui tone_seeds.
- Se la generazione guidata non trova candidati, fallback alla generazione normale.
- Il pool candidati del fallback viene sempre raddoppiato (`MARKOV_CANDIDATE_COUNT * 2`) e i candidati che terminano con `?` vengono filtrati. Questo vale su tutte le mention/reply, non solo sulle domande.
- La feature è puramente Markov, non richiede Groq.

## Comandi azione espliciti su mention/reply

Riconosciuti prima della generazione Markov normale (fast path regex):

| Comando | Esempi | Azione |
|---|---|---|
| `gif` | "manda una gif", "mandami gif", "voglio una gif", "gif" | Invia GIF casuale dal corpus; fallback a testo se corpus vuoto |
| `sticker` | "manda uno sticker", "sticker" | Invia sticker casuale dal corpus; fallback a testo |
| `insulta [target]` | "insulta Marco", "insultalo", "insulta quel tizio" | Genera testo Markov con seed aggressivi + nome target, raffina Groq con `tone=aggressive` |

Il dispatch avviene in `_handle_action()` dentro `mention_handler.py`. Se l'azione viene eseguita, l'handler fa `return` senza generare testo normale. Se il corpus è vuoto (gif/sticker) cade in generazione testo standard.

## Training corpus per chat

Il corpus di training è ora separato per chat. Il flusso è:

```
/importlive [chat:<chat_id>] [reset|append] [export_path]
  → scrive in training_corpus (source_kind=export)
  → trim FIFO se supera TRAINING_CORPUS_MAX_PER_CHAT

/retrain [chat:<chat_id>]
  → consolida live_corpus rows con id > last_live_corpus_id → training_corpus (source_kind=live)
  → trim FIFO
  → full rebuild modelli in models/chats/<chat_id>/
  → aggiorna chat_training_state (last_retrain_at, last_live_corpus_id, training_corpus_size)

scheduler auto-retrain (ogni ora, gira nella finestra RETRAIN_SCHEDULE_HOUR)
  → stessa logica di /retrain ma automatica per ogni chat di gruppo
  → skip se nuovi messaggi < RETRAIN_MIN_NEW_MESSAGES
```

**Separazione corpus caldo/freddo:**
- `live_corpus` = corpus caldo, 30 msg recenti per seeding/topic e live model mix. Rimane invariato.
- `training_corpus` = corpus freddo canonico. Source: import export + live consolidato via retrain.

**Note operative:**
- Fare `/importlive reset` poi `/retrain` su una chat per inizializzarla da un export.
- Il retrain successivo (manuale o schedulato) aggiunge solo i messaggi live arrivati dopo l'ultimo checkpoint.
- Reimportare lo stesso export non duplica (dedup su `source_key`).
- `/status` mostra il namespace modelli attivo per la chat (`models/chats/<chat_id>/`).

**Env tunable:**
```
TRAINING_CORPUS_MAX_PER_CHAT=1000000  # cap FIFO per chat sul corpus freddo
RETRAIN_SCHEDULE_HOUR=3               # ora locale (o range "2-4") per l'auto-retrain
RETRAIN_MIN_NEW_MESSAGES=50           # min nuovi msg live per avviare il rebuild
```

## Filtrare bot noti dal corpus

Aggiungi al `.env`:
```
EXCLUDE_USER_IDS=5448250840,<altri_id>
```

Esegui `/retrain` dopo aver aggiornato `.env`. Il trainer salta automaticamente
i messaggi provenienti da quei sender e da qualunque account il cui display name
termini per "bot" (es. "MarkolinoBot", "Music Bot").

## Dataset live — aggiornamento automatico via `/retrain`

Il comando `/retrain` ora incorpora automaticamente i messaggi del `live_corpus`
della chat target sopra la base canonica di training della chat.

Se per quella chat esiste gia `training_corpus`, quello diventa la base storica.
Se invece il corpus freddo e ancora vuoto, il trainer usa ancora l'export file
diretto come bootstrap iniziale.

Durante `/retrain`, i nuovi messaggi del `live_corpus` vengono prima consolidati
nel `training_corpus` con chiave `live:<row_id>`, poi il modello viene rebuildato
dalla base consolidata. Il checkpoint live viene avanzato solo a retrain riuscito.

Se vuoi riallineare completamente lo storico consolidato a un export manuale
aggiornato, usa prima `/importlive ...` e poi `/retrain ...`.

La risposta di `/retrain` mostra sia la base usata (`training_corpus` oppure export file)
sia il numero di messaggi live aggiunti sopra.

## Primo giro di avvio

1. Avvia il bot con `.env` configurato.
2. Aggiungilo al gruppo.
3. Fai passare qualche messaggio per registrare la chat e popolare il contesto recente.
4. Carica `data/export.json`.
5. Esegui `/retrain`.
6. Verifica con `/status`.
