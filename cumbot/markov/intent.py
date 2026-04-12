from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


# Parole-seme di fallback per ciascun tipo di domanda, usate SOLO se il
# contesto immediato non produce seed utili.
QUESTION_SEEDS: dict[str, list[str]] = {
    "chi":    [],
    "cosa":   ["cosa", "niente", "qualcosa", "roba", "sto", "ho"],
    "come":   ["così", "bene", "male", "col", "con", "in", "a"],
    "quando": ["domani", "stasera", "alle", "tra", "dopo", "mai", "prima"],
    "perché": ["perché", "per", "a", "non", "è", "boh", "perche"],
    "dove":   ["a", "in", "qua", "là", "lì", "fuori", "casa", "qui"],
    "quale":  ["quello", "questo", "uno", "il", "la", "quel"],
    "quanto": ["tanto", "poco", "molto", "troppo", "un"],
}

_KEYWORD_MAP = {
    "chi": "chi",
    "cosa": "cosa",
    "che cosa": "cosa",
    "come": "come",
    "quando": "quando",
    "perché": "perché",
    "perche": "perché",
    "dove": "dove",
    "quale": "quale",
    "quanto": "quanto",
}

# Stopwords italiane per la topic extraction
STOPWORDS_IT: frozenset[str] = frozenset({
    "il", "la", "lo", "le", "i", "gli", "un", "una", "uno",
    "che", "di", "del", "della", "dei", "degli", "delle",
    "da", "dal", "dalla", "dai", "dagli", "dalle",
    "a", "al", "alla", "ai", "agli", "alle",
    "in", "nel", "nella", "nei", "negli", "nelle",
    "con", "su", "sul", "sulla", "sui", "sugli", "sulle",
    "per", "tra", "fra", "e", "ed", "ma", "però", "o", "né",
    "se", "come", "quando", "dove", "perché", "perche",
    "cosa", "chi", "quale", "quanto", "quanta", "quanti", "quante",
    "non", "mi", "ti", "si", "ci", "vi", "li", "lo", "la", "le",
    "ho", "hai", "ha", "abbiamo", "avete", "hanno",
    "sono", "sei", "siamo", "siete",
    "sto", "stai", "sta", "stiamo", "state", "stanno",
    "questo", "questa", "questi", "queste",
    "quello", "quella", "quelli", "quelle",
    "già", "anche", "poi", "però", "quindi", "allora", "cioè", "cioe",
    "boh", "beh", "ah", "oh", "eh", "uh",
    "tipo", "raga", "bro", "dai", "vabbè", "vabbe",
    "più", "piu", "meno", "molto", "poco", "tanto", "troppo",
    "mai", "sempre", "ancora", "già", "solo", "proprio",
    "me", "te", "lui", "lei", "noi", "voi", "loro",
    "io", "tu",
})

_TOKEN_RE = re.compile(r"[\w']+", re.UNICODE)


def detect_question_type(text: str) -> str | None:
    """Ritorna il tipo di domanda o None se non è una domanda riconosciuta.

    Tipi possibili: "chi", "cosa", "come", "quando", "perché", "dove",
    "quale", "quanto", "generic".
    "generic" = finisce con "?" ma non contiene una keyword specifica.

    Cerca le keyword come word-boundary ovunque nel testo (non solo all'inizio),
    così funziona su frasi come "ma chi sei?", "dimmi quando arriva" o
    "non so come fare" anche senza punto interrogativo.
    Viene restituita la keyword che appare per prima nel testo.
    """
    stripped = text.strip()
    if not stripped:
        return None

    cleaned = stripped.lower()

    first_match_pos = len(cleaned)
    first_match_type: str | None = None

    for keyword, question_type in _KEYWORD_MAP.items():
        pattern = r"\b" + re.escape(keyword) + r"\b"
        m = re.search(pattern, cleaned)
        if m and m.start() < first_match_pos:
            first_match_pos = m.start()
            first_match_type = question_type

    if first_match_type:
        return first_match_type

    if stripped.endswith("?"):
        return "generic"

    return None


def get_context_names(recent_context: list[dict]) -> list[str]:
    """Estrae nomi/username unici dai metadati speaker del contesto.

    Preferisce display_name su username, deduplicando case-insensitive.
    """
    seen_lower: set[str] = set()
    names: list[str] = []

    for item in recent_context:
        for field in ("display_name", "username", "speaker"):
            value = (item.get(field) or "").strip()
            if value and value.lower() not in seen_lower:
                seen_lower.add(value.lower())
                names.append(value)
            if value:
                break

    return names


def _extract_proper_nouns(text: str) -> list[str]:
    """Estrae parole capitalizzate che non sono inizio di frase (possibili nomi propri)."""
    tokens = text.split()
    names = []
    for i, tok in enumerate(tokens):
        cleaned = re.sub(r"[^\w]", "", tok)
        if not cleaned:
            continue
        # Salta la prima parola (sempre maiuscola) e parole che seguono punteggiatura
        if i == 0:
            continue
        prev = tokens[i - 1]
        if prev and prev[-1] in ".!?":
            continue
        if cleaned[0].isupper() and cleaned.lower() not in STOPWORDS_IT and len(cleaned) > 1:
            names.append(cleaned)
    return names


def extract_seeds_from_input(
    input_text: str,
    question_type: str | None,
    bot_username: str = "",
) -> list[str]:
    """Estrae seed direttamente dalla domanda stessa (non dal contesto precedente).

    Rimuove prima il @mention del bot, poi applica la stessa logica di
    extract_topic_seeds sul testo della domanda. Da usare in combinazione con
    extract_topic_seeds (i seed del trigger hanno priorità su quelli del contesto).
    """
    text = input_text
    if bot_username:
        text = re.sub(rf"@{re.escape(bot_username)}\b", "", text, flags=re.IGNORECASE).strip()
    if not text:
        return []

    if question_type == "chi":
        return _extract_proper_nouns(text)[:6]

    tokens = _TOKEN_RE.findall(text.lower())
    return [
        t for t in tokens
        if len(t) > 3 and t not in STOPWORDS_IT and t.isalpha()
    ][:6]


# ---------------------------------------------------------------------------
# Action detection
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class BotAction:
    type: Literal["gif", "sticker", "insulta"]
    target: str = ""  # rilevante solo per "insulta"


_SEND_VERBS = (
    r"manda(?:mi|ci|melo|mela)?"
    r"|invia(?:mi|ci)?"
    r"|mostra(?:mi|ci)?"
    r"|dam(?:mi|ce|melo|mela)"
    r"|dacc[ei]"
    r"|datemi"
    r"|fammi\s+vedere"
    r"|facci\s+vedere"
    r"|voglio"
    r"|puoi\s+mandar(?:mi|ci)?"
)
_ART = r"(?:una?|la|lo|il|un|uno|le|gli|dei)?\s*"

_SEND_GIF_RE = re.compile(
    rf"(?:{_SEND_VERBS})\s+{_ART}gif\b"
    r"|\bgif\b",   # fallback: "gif" da sola ovunque nel messaggio
    re.IGNORECASE,
)

_SEND_STICKER_RE = re.compile(
    rf"(?:{_SEND_VERBS})\s+{_ART}sticker\b"
    r"|\bsticker\b",
    re.IGNORECASE,
)

# "insulta Marco", "insulta quel coglione", "insulta @nomeutente", ecc.
_INSULTA_RE = re.compile(
    r"\binsulta(?:lo|la|li|le)?\b\s*(.*?)(?:\s*[?!.,]?\s*$)",
    re.IGNORECASE,
)


def detect_action(text: str, bot_username: str = "") -> BotAction | None:
    """Rileva comandi d'azione espliciti nel messaggio trigger.

    Rimuove prima il @mention del bot, poi cerca pattern specifici.
    Ritorna un BotAction oppure None se non c'è un comando riconoscibile.

    Azioni supportate:
    - gif:     "manda una gif", "mandami gif", "gif"
    - sticker: "manda uno sticker", "mandami sticker", "sticker"
    - insulta: "insulta Marco", "insultalo", "insulta quel tizio"
    """
    cleaned = text
    if bot_username:
        cleaned = re.sub(rf"@{re.escape(bot_username)}\b", "", cleaned, flags=re.IGNORECASE).strip()
    if not cleaned:
        return None

    if _SEND_GIF_RE.search(cleaned):
        return BotAction(type="gif")

    if _SEND_STICKER_RE.search(cleaned):
        return BotAction(type="sticker")

    m = _INSULTA_RE.search(cleaned)
    if m:
        raw_target = (m.group(1) or "").strip().lstrip("@")
        # Rimuovi punteggiatura finale e prendi al massimo le prime 3 parole
        target_words = re.findall(r"[\w']+", raw_target)[:3]
        target = " ".join(target_words)
        return BotAction(type="insulta", target=target)

    return None


def extract_topic_seeds(
    immediate_context: list[dict],
    question_type: str,
    max_seeds: int = 6,
) -> list[str]:
    """Estrae parole-chiave dal contesto immediato (ultimi 2-3 messaggi).

    Per "chi": cerca nomi propri nel testo (parole capitalizzate non inizio frase).
    Per altri tipi: estrae parole sostanziali (len > 3, non stopword) dai messaggi.
    Ritorna al massimo max_seeds seed in ordine di rilevanza (ultimi messaggi prima).
    """
    seeds: list[str] = []
    seen_lower: set[str] = set()

    # Itera in ordine inverso: i messaggi più recenti hanno priorità
    for item in reversed(immediate_context):
        text = (item.get("text") or "").strip()
        if not text:
            continue

        if question_type == "chi":
            candidates = _extract_proper_nouns(text)
        else:
            tokens = _TOKEN_RE.findall(text.lower())
            candidates = [
                t for t in tokens
                if len(t) > 3 and t not in STOPWORDS_IT and t.isalpha()
            ]

        for candidate in candidates:
            key = candidate.lower()
            if key not in seen_lower:
                seen_lower.add(key)
                seeds.append(candidate)
            if len(seeds) >= max_seeds:
                break

        if len(seeds) >= max_seeds:
            break

    return seeds
