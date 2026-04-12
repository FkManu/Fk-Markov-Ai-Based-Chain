from __future__ import annotations

import re


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

_PLAYFUL_RE = re.compile(
    r"\b((?:a(?:ha){2,}h?)|(?:(?:ha){2,}h?)|lol|lmao|xd|kek|jajaj+)\b",
    re.IGNORECASE | re.UNICODE,
)


def detect_tone(recent_context: list[dict], input_text: str = "") -> str:
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


TONE_HINTS: dict[str, str] = {
    "aggressive": (
        "Contesto aggressivo. Se la bozza contiene gia insulti o parolacce, mantienili o "
        "intensificali. Non aggiungere parolacce nuove se non sono gia nella bozza."
    ),
    "playful": (
        "Contesto ironico e leggero. Se possibile rendila piu divertente o sarcastica "
        "senza stravolgere il senso."
    ),
    "neutral": "",
}


TONE_SEEDS: dict[str, list[str]] = {
    "aggressive": ["cazzo", "merda", "fanculo", "basta", "mai", "stronzo"],
    "playful": ["ahah", "pazzo", "bello", "raga"],
    "neutral": [],
}
