# Markov Modernization Plan

## Obiettivo

Rendere la pipeline Markov di CumBot piu:

- precisa nello stile;
- robusta sui casi rari;
- controllabile in fase di debug;
- misurabile tra versioni;
- meno dipendente da Gemini per sembrare coerente.

## Stato attuale

Implementazione corrente:

- training su testo grezzo per utente e globale;
- modelli `markovify.Text` di ordine fisso `state_size=1` e `state_size=2`;
- selezione semplice: prova ordine 2, poi fallback a ordine 1;
- generazione di una singola frase corta;
- nessuna metrica di validazione;
- nessun report sulle transizioni;
- nessun controllo temporale del drift;
- nessuna distinzione tra struttura del messaggio e contenuto lessicale.

File chiave:

- `cumbot/markov/trainer.py`
- `cumbot/markov/generator.py`
- `cumbot/gemini/refiner.py`
- `docs/markov_best_practices.md`

## Gap rispetto alle best practices

Il documento `markov_best_practices.md` spinge su stati interpretabili, variable-order, metriche e analisi di stabilita. La nostra pipeline attuale invece usa direttamente il testo grezzo come stato implicito.

Questo non e necessariamente sbagliato per un bot stilistico, ma crea quattro limiti reali:

1. La catena impara bene il lessico locale ma male la struttura conversazionale.
2. L'ordine fisso `1/2` non usa davvero un backoff probabilistico, ma solo un fallback meccanico.
3. Non abbiamo una misura oggettiva per capire se una nuova versione e davvero migliore.
4. Non possiamo diagnosticare facilmente perche una persona o una chat genera frasi forti o deboli.

## Direzione consigliata

Per questo progetto non conviene abbandonare subito la Markov lessicale. Conviene invece passare a una pipeline a due livelli:

- livello strutturale: capire che tipo di messaggio stiamo generando;
- livello lessicale: generare testo nello stile del gruppo o della persona.

In pratica: non una Markov "piu grossa", ma una Markov piu guidata.

## Roadmap proposta

## Fase 1 — Osservabilita e baseline seria

Scopo: capire cosa stiamo gia facendo davvero.

Interventi:

- salvare statistiche di training piu ricche in `metadata.json`;
- aggiungere report con:
  - messaggi per utente;
  - lunghezza media messaggi;
  - top token;
  - coverage del modello;
  - percentuale di generazioni fallite;
- introdurre un comando admin o script locale per campionare `N` bozze raw per globale/persona;
- versionare esplicitamente la pipeline Markov.

Output atteso:

- possiamo confrontare versioni diverse senza andare solo a sensazione;
- capiamo quali personas funzionano davvero e quali no.

## Fase 2 — Pulizia dati orientata allo stile

Scopo: migliorare la qualita del corpus senza sterilizzarlo.

Interventi:

- distinguere meglio messaggi utili da rumore:
  - sticker placeholder;
  - media-only;
  - forward automatici;
  - bot messages;
  - spam da link;
- mantenere intenzionalmente slang, abbreviazioni e typo frequenti;
- introdurre normalizzazione selettiva:
  - whitespace;
  - unicode problematico;
  - placeholder per URL, mention e numeri lunghi;
- tenere opzionale una modalita `raw` e una `normalized` per confronti.

Output atteso:

- meno stati quasi unici;
- meno frammentazione inutile;
- piu riuso delle transizioni forti.

## Fase 3 — Variable-order reale

Scopo: smettere di usare il solo ordine fisso come scelta rigida.

Interventi:

- costruire un generatore a backoff vero:
  - prova contesto piu lungo;
  - se il contesto e raro o instabile, scende di ordine;
  - se necessario torna a unigrammi o token frequenti;
- introdurre score di confidenza del contesto;
- usare interpolazione tra ordine 1 e ordine 2 invece del solo fallback secco;
- valutare ordine 3 solo per personas molto dense.

Output atteso:

- generazioni meno spezzate;
- meno `None`;
- frasi piu coerenti senza perdere spontaneita.

## Fase 4 — Stato strutturale leggero

Scopo: rendere la catena piu moderna senza snaturare il progetto.

Interventi:

- aggiungere feature leggere per messaggio:
  - bucket di lunghezza;
  - presenza domanda;
  - presenza link;
  - presenza reply;
  - densita emoji;
  - intensita punteggiatura;
- segmentare il corpus in classi di stile, ad esempio:
  - corto/esclamativo;
  - medio/argomentativo;
  - domanda;
  - meme/assurdo;
- prima scegliere la classe, poi generare il testo lessicale dentro quella classe.

Output atteso:

- messaggi piu centrati sul ritmo reale del gruppo;
- maggiore controllo sul "tipo" di frase prodotta.

## Fase 5 — Personalizzazione migliore

Scopo: far funzionare meglio personas singole e miste.

Interventi:

- pesare la miscela multi-persona in base alla densita del corpus;
- evitare che una persona con pochi dati domini o degradi la combinazione;
- introdurre fallback per gruppi di personas:
  - persona primaria;
  - gruppo;
  - globale;
- salvare esempi rappresentativi per ogni persona.

Output atteso:

- combinazioni multi-persona meno casuali;
- voce piu riconoscibile.

## Fase 6 — Validazione offline

Scopo: scegliere le modifiche in modo misurabile.

Interventi:

- split temporale train/validation;
- metriche semplici ma utili:
  - coverage;
  - tasso di generazione valida;
  - lunghezza media;
  - novelty rispetto al corpus;
  - quota di output quasi-duplicati;
- mini benchmark con set fisso di personas e prompt-context.

Output atteso:

- ogni upgrade Markov produce un confronto vero con la baseline.

## Fase 7 — Integrazione piu intelligente con Gemini

Scopo: usare Gemini come refiner e non come stampella totale.

Interventi:

- passare a Gemini bozze Markov piu compatte ma piu informative;
- allegare tag strutturali nel prompt:
  - lunghezza desiderata;
  - tono;
  - tipo messaggio;
  - personas target;
- fare candidate generation:
  - generare 3 bozze Markov;
  - scegliere la migliore con score euristico;
  - raffinare solo la migliore.

Output atteso:

- meno costo inutile lato Gemini;
- maggiore coerenza anche con Gemini spento.

## Priorita pratica

Ordine consigliato per i prossimi step:

1. Fase 1: osservabilita e sampling.
2. Fase 2: pulizia dati con modalita raw vs normalized.
3. Fase 3: backoff/interpolazione.
4. Fase 7: candidate generation prima del refine.
5. Fase 4: classi strutturali leggere.

## Stato implementazione

### Gia avviato

- Fase 1:
  - metadata di training piu ricchi;
  - summary ispezionabile localmente;
  - sampling locale dei candidati raw;
  - report locale di analisi corpus e motivi di scarto.
- Fase 2:
  - supporto `raw` vs `normalized` tramite `MARKOV_TEXT_MODE`;
  - normalizzazione selettiva di URL, mention e numeri lunghi;
  - filtro piu severo su bot command, media low-signal e testo poco informativo.
- Fase 3:
  - candidate generation multipla;
  - scoring euristico dei candidati;
  - backoff piu robusto tra ordine 2 e ordine 1;
  - soglia minima di qualita per scartare i candidati peggiori quando possibile;
  - penalita aggiuntive contro i collage troppo spezzati.
- Fase 4:
  - prima forma leggera di rendering strutturale delle mention, mantenendo `@user` come intenzione della catena ma materializzandolo come tag reale in output;
  - fine tuning di superficie in post-processing: pulizia duplicati, ammorbidimento restart maiuscole, punteggiatura finale minima, ranking piu severo sui collage;
  - riconoscimento domande base (chi/cosa/come/quando/perché/dove/quale/quanto) con generazione guidata da seed words, senza Gemini;
  - corpus live per-chat: persistenza automatica dei messaggi in arrivo e mixing dinamico con il modello base a ogni generazione.

- corpus live per contestualizzazione dinamica (a due livelli):
  - ogni messaggio in arrivo viene persistito in `live_corpus` (SQLite);
  - **livello 1 — contesto immediato** (ultimi `IMMEDIATE_CONTEXT_SIZE=3` msg): usato come seed extraction per domande, non mixato nel modello;
  - **livello 2 — corpus recente** (ultimi `LIVE_CORPUS_LIMIT=30` msg, peso `LIVE_CORPUS_WEIGHT=0.2`): mixato con il modello base per dare deriva tematica;
  - threshold minima `LIVE_CORPUS_MIN_MESSAGES=15` msg per state_size=1, doppio per state_size=2;
  - nessun retrain richiesto: il corpus si aggiorna automaticamente.
- riconoscimento domande (puro Markov) con seed contestuali:
  - `cumbot/markov/intent.py`: `detect_question_type()`, `extract_topic_seeds()`, `get_context_names()`;
  - `extract_topic_seeds()` estrae topic words e nomi propri dagli ultimi 2-3 messaggi del contesto (non usa liste fisse);
  - `generate_question_candidates()` in `generator.py` usa `make_sentence_with_start()` con questi seed;
  - `QUESTION_SEEDS` fissi rimangono come fallback se il contesto non produce seed utili;
  - fallback trasparente alla generazione normale se la generazione guidata non trova candidati validi.
- strumento di analisi DB:
  - `python -m cumbot.markov.report db-stats` mostra reaction rate, gemini usage, delta draft/output, lunghezza media, corpus live size, top reacted.
- scoring collage: `restart_penalty` portata a `max(0, r-1)*4.0` — il 2° restart in una frase costa 4 punti, eliminando quasi tutti i messaggi multi-frase disarticolati dal pool dei candidati validi.
- fix Gemini: aggiunta istruzione nel system prompt del refiner per vietare il formato "username: testo".

### Aggiornamento 2026-04-10 — Analisi Markolino

Analizzato il corpus del bot di riferimento (user5448250840, 15518 output):
- **Mediana 9 parole**, 87% zero restart, overlap contestuale medio 11% (60% zero overlap).
- Markolino NON usa context seeding esplicito né logiche question-aware. La sua "precisione" deriva interamente da: (a) corpus ampio e ben allenato, (b) output brevi e coerenti (niente collage).
- Conseguenza pratica: la direzione corretta non è aggiungere più intelligenza contestuale, ma generare frasi più brevi e pulite.

Modifiche implementate in base a questa analisi:
- `target_chars` abbassato da 90 a 55, `target_words` da 14 a 9 nello scoring.
- `restart_penalty` rivisto: 1° restart costa 1.0, ogni restart successivo costa 5.0 in più → candidati a 2+ restart escono sotto threshold con score medio -1.76.
- `MARKOV_DRAFT_MAX_CHARS` abbassato da 180 a 120.

### Ancora aperto

- metriche offline su split temporale;
- classi strutturali dei messaggi (short/exclamation, question, argumentative, meme/absurd) per candidate selection;
- benchmark comparativo tra versioni;
- feedback loop reaction → ranking (dati raccolti, segnale non ancora usato per il ranking Markov);
- integrazione domande con Gemini (intent passato come hint nel prompt refiner) — rimandato a dopo la stabilizzazione del solo Markov.

Nota per la fase reaction:

- quando verrà implementata, tutte le reaction saranno considerate positive senza distinzione di emoji;
- il segnale servirà come bias leggero di ranking, non come riscrittura aggressiva dello stile.

Aggiornamento stato:

- il tracking reaction e gia stato implementato a livello di monitoring persistente;
- per ora il segnale viene raccolto ma non influenza ancora il ranking Markov;
- il prossimo step sara usare `reaction_count` come bonus leggero e capped nella scelta del candidato finale.

## Cosa NON fare subito

- non passare subito a modelli molto piu complessi o neurali;
- non introdurre troppe feature strutturali tutte insieme;
- non alzare alla cieca l'ordine della catena;
- non giudicare la qualita solo dai messaggi "piu divertenti".

## Primo obiettivo concreto

Il primo milestone utile e questo:

"Ottenere una bozza Markov raw che, anche con Gemini off, sia piu corta, piu leggibile, meno casuale e piu riconoscibile per persona."

Per arrivarci, il primo pacchetto di lavoro dovrebbe essere:

- script/report di analisi corpus;
- sampling comparativo globale/persona;
- normalizzazione selettiva opzionale;
- generazione con candidate ranking + backoff semplice.
