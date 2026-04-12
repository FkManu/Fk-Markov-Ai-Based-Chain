from __future__ import annotations

import re

from cumbot import config
from cumbot.groq.service import groq_service


_SYSTEM = (
    "Sei in una chat italiana informale e volgare. "
    "Classifica il messaggio in UNA sola parola tra: roast, reaction, agreement, generic.\n"
    "- roast: insulto o sfotto diretto al bot (es. 'sei un coglione', 'sei inutile', 'non capisci niente')\n"
    "- reaction: esclamazione o reazione emotiva breve (es. 'godo', 'minchia', 'porcodio', 'che schifo', 'wow', 'wtf')\n"
    "- agreement: accordo o validazione (es. 'esatto', 'ci sta', 'giusto', 'vero', 'certo', 'ah ok')\n"
    "- generic: tutto il resto\n"
    "Rispondi SOLO con la parola, nient'altro."
)

_VALID_LABELS = {"roast", "reaction", "agreement"}


async def classify_intent(input_text: str, bot_username: str = "") -> str:
    """Ritorna uno dei label: roast, reaction, agreement, generic.

    Fallback: 'generic' se la feature e disabilitata, manca la API key,
    Groq fallisce oppure la risposta non e valida.
    """
    if not config.GROQ_CLASSIFY_ENABLED or not config.GROQ_API_KEY:
        return "generic"

    cleaned = input_text
    if bot_username:
        cleaned = re.sub(
            rf"@{re.escape(bot_username)}\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
    if not cleaned:
        return "generic"

    try:
        response = await groq_service.generate_text(
            model=config.GROQ_ASK_MODEL,
            system_instruction=_SYSTEM,
            user_prompt=cleaned,
            temperature=0.0,
            max_output_tokens=5,
        )
    except Exception:
        return "generic"

    if not response:
        return "generic"

    label = response.strip().lower().split()[0].rstrip(".,!?")
    return label if label in _VALID_LABELS else "generic"
