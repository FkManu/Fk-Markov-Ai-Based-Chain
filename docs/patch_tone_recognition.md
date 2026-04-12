# Patch: Riconoscimento tono/contesto (Feature E)

## Obiettivo

Fare in modo che il bot riconosca il tono emotivo della conversazione recente e risponda
di conseguenza: aggressivo se viene insultato o se la chat è in modalità litigio,
leggero/ironico se la chat è in modalità "risate". Zero chiamate Groq extra.

## Analisi corpus (dati reali, 1M messaggi)

- Markolino NON fa mirroring esplicito degli insulti (solo 1.1% dei reply a insulti contiene a sua volta un insulto)
- Il tono aggressivo emerge naturalmente dal corpus ricco, non da logica ad-hoc
- "ahah/haha" ubiqui (~4.5% di tutti i messaggi) → soglia playful = ≥2 hit in 5 messaggi
- Vocabolario aggressivo confermato dal corpus: frocio, negro, finocchio, mongo, down, bestia, animale, ecc.

## File da creare

### `cumbot/markov/tone.py` (nuovo)

```python
from __future__ import annotations
import re

# Pattern aggressivi — basati su frequenze reali del corpus (>100 occorrenze)
_AGGRESSIVE_RE = re.compile(
    r"\b(cazzo|merda|culo|minchia"
    r"|troi[ae]|puttane?"
    r"|froc[io]|froci|finocc?h[io]|finocchi"
    r"|negro|negri"
    r"|coglion[ei]"
    r"|fanculo|vaffanculo|affanculo|mafanculo"
    r"|porco\s+dio|porcodio"
    r"|scemo|scema|scemi"
    r"|bastardo|bastarda"
    r"|mongo|mongoloide|ritardato|ritardata|down\b"
    r"|animale|bestia"
    r"|figlio\s+di\s+puttana"
    r"|pezzo\s+di\s+merda"
    r"|muori|crepa|fottiti|vattene|sparisci"
    r"|lurido|lurida"
    r"|ti\s+(odio|schifo|ammazzo|spezzo))\b",
    re.IGNORECASE | re.UNICODE,
)

# Pattern playful — solo marker di risata esplicita (ahah è ubiquo: soglia ≥2 hit)
_PLAYFUL_RE = re.compile(
    r"\b(ahah+|ahahah+|haha+|lol|lmao|xd|kek|jajaj+)\b",
    re.IGNORECASE | re.UNICODE,
)


def detect_tone(recent_context: list[dict], input_text: str = "") -> str:
    """Analizza il tono degli ultimi 5 messaggi + il trigger.

    Ritorna "aggressive", "playful" o "neutral".
    Logica:
    - aggressive: basta 1 hit (insulto diretto = segnale chiaro)
    - playful: >=2 hit di risata nei 5 messaggi (ahah da solo e troppo comune)
    """
    texts = [input_text] if input_text else []
    for item in recent_context[-5:]:
        text = (item.get("text") or "").strip()
        if text:
            texts.append(text)
    combined = " ".join(texts).lower()
    if _AGGRESSIVE_RE.search(combined):
        return "aggressive"
    if len(_PLAYFUL_RE.findall(combined)) >= 2:
        return "playful"
    return "neutral"


# Hint iniettato nel system prompt Groq — guida la direzione dell'amplificazione
TONE_HINTS: dict[str, str] = {
    "aggressive": (
        "Il contesto e aggressivo e ostile. "
        "Amplifica in direzione nervosa, tagliente, senza peli sulla lingua."
    ),
    "playful": (
        "Il contesto e leggero e ironico. "
        "Amplifica in direzione divertente, sarcastica."
    ),
    "neutral": "",
}

# Seed Markov per tono — parole con alta frequenza nel corpus nel registro corretto
TONE_SEEDS: dict[str, list[str]] = {
    "aggressive": ["cazzo", "merda", "fanculo", "basta", "mai", "stronzo"],
    "playful":    ["ahah", "pazzo", "bello", "raga"],
    "neutral":    [],
}
```

## File da modificare

### `cumbot/groq/refiner.py`

Aggiungere import all'inizio del file:
```python
from cumbot.markov.tone import TONE_HINTS
```

Modificare la firma di `refine_draft()`:
```python
async def refine_draft(
    draft: str,
    recent_context: list[dict],
    persona_ids: list[str] | None,
    tone: str = "neutral",
) -> str:
```

Nella funzione, subito dopo il blocco che costruisce `system_prompt` (riga ~36, dopo il check `if persona_ids`), aggiungere:
```python
    tone_hint = TONE_HINTS.get(tone, "")
    if tone_hint:
        system_prompt += f"\n{tone_hint}"
```

### `cumbot/handlers/mention_handler.py`

Aggiungere all'import block esistente:
```python
from cumbot.markov.tone import detect_tone, TONE_SEEDS
```

Nella funzione `handle_mention()`, subito dopo la riga `question_type = detect_question_type(input_text)` (riga ~81), aggiungere:
```python
    tone = detect_tone(recent_context, input_text=input_text)
```

Nella sezione seed, il blocco `else: seed_words = []` diventa:
```python
    else:
        # Nessuna domanda riconosciuta: usa seed di tono come orientamento (se non neutral)
        seed_words = TONE_SEEDS.get(tone, []) if tone != "neutral" else []
```

Nella chiamata a `refine_draft()` (riga ~104), aggiungere `tone=tone`:
```python
        output = await refine_draft(
            draft=draft,
            recent_context=recent_context,
            persona_ids=persona_ids,
            tone=tone,
        )
```

### `cumbot/scheduler.py`

Aggiungere import:
```python
from cumbot.markov.tone import detect_tone
```

In `send_autopost_message()`, subito dopo `recent_context = collector.get_recent(chat_id)` (riga ~31), aggiungere:
```python
    tone = detect_tone(recent_context)
```

Nella chiamata a `refine_draft()` (riga ~38), aggiungere `tone=tone`:
```python
        output = await refine_draft(
            draft=draft,
            recent_context=recent_context,
            persona_ids=settings.active_persona_ids,
            tone=tone,
        )
```

## Verifica

```bash
# 1. Test unitari
pytest tests/ -q

# 2. Smoke test tono aggressivo (Python)
python3 -c "
from cumbot.markov.tone import detect_tone
ctx = [{'text': 'sei uno stronzo'}, {'text': 'vaffanculo frocio'}]
print(detect_tone(ctx, input_text='@bot rispondimi'))  # atteso: aggressive

ctx2 = [{'text': 'ahahahah'}, {'text': 'hahaha sei pazzo'}, {'text': 'lol'}]
print(detect_tone(ctx2))  # atteso: playful

ctx3 = [{'text': 'ok ci vediamo dopo'}, {'text': 'sì dai'}]
print(detect_tone(ctx3))  # atteso: neutral
"

# 3. Test su bot live
# - Mandare "@bot sei uno stronzo" → /outputs → verificare che draft e output siano più taglienti
# - Mandare 3 messaggi con ahahahah poi @bot → /outputs → verificare tono ironico
# - Verificare in log che non ci siano chiamate Groq extra
```

## Note

- Zero chiamate Groq extra: il tone hint è solo una stringa aggiunta al system prompt esistente
- Il rilevamento aggressivo ha soglia 1 (un insulto basta): in una chat volgare come questa, un insulto diretto al bot o in contesto è un segnale forte
- Il rilevamento playful ha soglia 2 (ahah è troppo comune — 45k occorrenze nel corpus)
- I seed di tono Markov funzionano solo se quelle parole esistono nel corpus — con questo corpus volgare funzionano
- Priorità seed: se c'è domanda riconosciuta, i seed di domanda hanno la precedenza sui seed di tono (il tono Groq hint è comunque attivo)
