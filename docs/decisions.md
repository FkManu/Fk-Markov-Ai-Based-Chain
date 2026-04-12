# Decision Log

## 2026-04-10 — sessione 6 (pianificato)

- Reactions randomiche: probabilità separata (REACTION_PROBABILITY) per non sovraccaricare l'API. Fallback silente su eccezione perché i permessi di reazione variano per gruppo. Fire-and-forget per non aggiungere latenza al middleware.
- GIF corpus: dedup per file_unique_id (stesso file da mittenti diversi → un solo record). Conteggio GIF recenti via DB (finestra temporale in minuti) invece del collector in memoria, perché il collector usa @dataclass(slots=True) e non è modificabile senza breaking change.
- Whitelist chat: comportamento "silenzio totale" (non risposta unica) per non rivelare la presenza del bot in chat non autorizzate.
- Setup panel: lista chat come primo step in qualunque contesto (privato o gruppo) — più uniforme che avere due flussi separati. Gli admin possono configurare qualsiasi chat nota dal bot anche se vi accedono da un contesto diverso.

## 2026-04-10 — sessione 4

- I messaggi da bot nel corpus vengono filtrati con `is_bot_sender()`: controlla EXCLUDE_USER_IDS + nome che termina per "bot". Markolino (user5448250840) va aggiunto esplicitamente a EXCLUDE_USER_IDS nel .env — il suo display name "Markolino" non triggera l'euristica sul nome.
- `/retrain` incorpora automaticamente il live_corpus (messaggi ricevuti in produzione) nel training base. Non serve un nuovo export manuale per aggiornare il dataset.
- `register_chat` ON CONFLICT non resetta più `autopost_enabled`. Prima ogni messaggio in arrivo poteva sovrascrivere un toggle fatto a runtime.
- Penalità `?` alzata da -0.2 a -0.5; `MARKOV_CANDIDATE_COUNT` default 8→12. Con pool più ampio e penalità più forte la distribuzione si bilancia meglio verso affermazioni.

## 2026-04-10 — sessione 3

- Gemini fallback ora loggato a livello WARNING con causa (quota/rate, safety block, eccezione generica). Prima era completamente silente — impossibile diagnosticare se il fallback era per quota o per altro.
- Limite operativo: gemini-2.5-flash-lite free tier è 30 RPM / 1500 RPD. Su chat attive il rate limit è il motivo principale del fallback.
- `_lowercase_restart_capitals()`: post-processing sui candidati Markov per abbassare maiuscole spurie a metà frase. Esclusioni: acronimi (tutto maiuscolo), nomi composti con uppercase interno. Nomi propri semplici (es. "Polina") vengono abbassati — limitazione nota.
- `detect_question_type()` riscritta con `re.search` + word boundary: ora intercetta keyword di domanda ovunque nel testo, non solo all'inizio. Prima keyword trovata (left-to-right) vince.

## 2026-04-10 — sessione 2

- Question bias: 87% degli output finivano con "?" (corpus artifact, non scoring issue). Introdotta penalità -0.2 per "?" e bonus +0.3 solo per "." e "!" per bilanciare la distribuzione.
- `restart_penalty` per il 1° restart alzato da 1.0 a 2.0: il candidato 0-restart vince quasi sempre rispetto a uno 1-restart di qualità analoga.
- Strategia Gemini cambiata da "riscrivere" a "amplificare": Gemini deve prendere il concetto centrale del draft Markov ed esagerarlo senza inventare argomenti nuovi, mantenendo le parole chiave e la stessa lunghezza (± 3 parole). Vietato rewrite completo, emoji spam e punteggiatura doppia.
- Aggiunto `draft_words` nel prompt utente come anchor esplicito sulla lunghezza target.

## 2026-04-10

- Analizzato corpus Markolino (16437 messaggi): mediana output 9 parole, 87% zero restart, overlap contestuale medio 11% (60% zero overlap). Conclusione: la sua "precisione" deriva da un modello ben allenato su frasi brevi e pulite, NON da logiche contestuali esplicite.
- Abbassato `target_chars` da 90 a 55 e `target_words` da 14 a 9 nello scoring: allinea il nostro output alla distribuzione di lunghezza osservata in Markolino.
- Rivisto `restart_penalty`: da `max(0, r-1)*4.0` a `min(r,1)*1.0 + max(0,r-1)*5.0`. Il 1° restart ora costa 1.0 (scoraggiato ma non eliminato); il 2° costa 6.0 — i candidati a 2+ restart escono invariabilmente sotto la threshold 2.5 (score medio -1.76 sui draft reali).
- Abbassato `MARKOV_DRAFT_MAX_CHARS` default da 180 a 120: `make_short_sentence` genera candidati più brevi in partenza, riducendo la probabilità di restart strutturali.

## 2026-04-07

- Il progetto vive nel repo esistente `CumBot`.
- La configurazione operativa e lo stato sono separati per `chat_id`.
- La persona attiva e admin-only e supporta uno o piu Telegram user ID.
- Per ora il training usa un solo export Telegram JSON standard.
- La libreria Gemini scelta e `google-genai`, non `google-generativeai`.
- Il modello iniziale consigliato per costo/beneficio e `gemini-2.5-flash-lite`.
- In caso di quota esaurita:
  - `Simula` usa fallback diretto alla bozza Markov.
  - `/ask` risponde che il budget giornaliero e finito.
- I documenti in `docs/` sono living docs e vanno aggiornati nel corso del progetto.

## 2026-04-09 — sessione 3

- `restart_penalty` portata a `max(0, r-1)*4.0`: il 1° restart è gratuito (stile chat), il 2° costa 4 punti e fa crollare quasi tutti i collage sotto threshold. Motivazione: l'analisi numerica sui draft reali mostrava score 5.8-6.5 per frasi con 2 pensieri incollati — completamente indistinguibili da frasi fluide.
- I seed per le domande vengono estratti dal contesto immediato (ultimi 3 msg) e non da liste fisse per tipo. Motivazione: i seed fissi (es. "domani" per "quando?") raramente matchano transizioni nel modello allenato sulla chat specifica; le parole del contesto recente invece ci sono quasi sempre.
- Il live corpus usa 30 messaggi (non 100) al peso 0.2 (non 0.4). Motivazione: finestra più stretta = contesto più focalizzato sul topic corrente; peso più basso = lo stile del modello allenato rimane dominante.
- Il contesto immediato (3 msg) viene usato SOLO per seed extraction, non viene mixato come modello. Motivazione: 3 messaggi sono troppo pochi per un modello markovify utile; usiamo quei token come guida diretta per `make_sentence_with_start()`.

## 2026-04-09 — sessione 2

- Il riconoscimento domande (chi/cosa/come/quando/perché/dove/quale/quanto) viene gestito a livello Markov puro, senza coinvolgere Gemini, per non sprecare token e per perfezionare prima la catena.
- Per "chi?" i semi di generazione sono i nomi reali degli speaker dal contesto recente: non si usano nomi hardcoded ne inventati.
- Le domande generiche (finiscono con "?" ma senza keyword specifica) usano la generazione normale, senza seed.
- Il corpus live usa fire-and-forget (`asyncio.ensure_future`) per non aggiungere latenza al middleware.
- Il peso del live model nella combine e conservativo (`0.4`) per mantenere dominante lo stile del modello allenato.
- Il live corpus e globale per chat, non filtrato per persona: contribuisce al contesto tematico, non alla voce.
- La threshold minima del live corpus (30/60 messaggi) evita che modelli degeneri da corpora piccoli inquinino la generazione.

## 2026-04-09

- La modernizzazione Markov parte senza dipendere da Gemini.
- La pipeline Markov ha ora una versione esplicita (`2.0`).
- Il trainer supporta `MARKOV_TEXT_MODE=raw|normalized`, con default `normalized`.
- Il generatore non sceglie piu il primo output valido: produce piu candidati e li ordina con uno score euristico.
