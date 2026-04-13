from __future__ import annotations

import logging
import re

from cumbot import config
from cumbot.groq.service import GroqService, is_rate_limit_error

LOGGER = logging.getLogger(__name__)

# Client dedicato per /ask: usa GROQ_ASK_API_KEY se configurata,
# altrimenti cade su GROQ_API_KEY. Tenerlo separato evita che i rate
# limit di /ask impattino refiner e classifier.
_ask_service = GroqService(api_key=config.GROQ_ASK_API_KEY or None)

# Catena di fallback: compound-beta (web search) → mini → llama standard
_FALLBACK_CHAIN: list[tuple[str, int]] = [
    (config.GROQ_COMPOUND_MODEL, 800),       # compound-beta — web search integrata
    (config.GROQ_COMPOUND_MINI_MODEL, 600),  # compound-beta-mini — più veloce
    (config.GROQ_ASK_MODEL, 800),            # llama-3.3-70b — fallback senza search
]

ASK_SYSTEM_PROMPT = """Sei un assistente diretto, informale e aggiornato.
Rispondi sempre in italiano.

Regole:
- Sii conciso: max 3-4 frasi per risposte semplici, max 6-8 punti per liste.
- Se la risposta richiede piu punti usa elenchi con trattino (-), senza titoli.
- Niente markdown pesante (**grassetto**, ## titoli): solo testo e trattini.
- Se hai usato fonti web, integra le info direttamente senza citare URL.
- Non terminare con "Spero che...", "Fammi sapere se...", o frasi di chiusura generiche."""

# Citazioni inline tipo "[1]" o "[source]" inserite dai compound model
_CITATION_RE = re.compile(r"\[\d+\]|\[source(?:\s+\d+)?\]", re.IGNORECASE)


def _clean_compound_response(text: str) -> str:
    """Rimuove artefatti dei compound model (citazioni numeriche, link residui)."""
    text = _CITATION_RE.sub("", text)
    lines = [l for l in text.splitlines() if not re.match(r"^\s*https?://\S+\s*$", l)]
    return "\n".join(lines).strip()


async def _try_conversation(
    messages: list[dict],
    temperature: float,
) -> str:
    """Esegue la catena compound-beta → mini → llama con messaggi multi-turn."""
    last_exc: Exception | None = None

    for model, max_tokens in _FALLBACK_CHAIN:
        if not model:
            continue
        try:
            response = await _ask_service.generate_conversation(
                model=model,
                messages=messages,
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
            if response:
                return _clean_compound_response(response)
        except Exception as exc:
            last_exc = exc
            LOGGER.warning("ask_groq model=%s failed (%s): %s", model, type(exc).__name__, exc)
            continue

    if last_exc is not None and is_rate_limit_error(last_exc):
        return "Troppe richieste al modello AI, riprova tra un momento."
    return "Il modello AI sta avendo problemi, riprova tra poco."


async def ask_groq(question: str, temperature: float | None = None) -> str:
    key_available = config.GROQ_ASK_API_KEY or config.GROQ_API_KEY
    if not key_available:
        return "Manca GROQ_API_KEY, quindi per ora non riesco a usare /ask."

    temp = temperature if temperature is not None else config.GROQ_ASK_TEMPERATURE
    messages = [
        {"role": "system", "content": ASK_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    return await _try_conversation(messages, temp)


async def ask_groq_conversation(
    history: list[dict],
    new_user_message: str,
    temperature: float | None = None,
) -> tuple[str, list[dict]]:
    """Continua una conversazione esistente.

    Ritorna (risposta, history_aggiornata) — la history include già il nuovo
    turno user + assistant, pronta per essere salvata nello store.
    """
    key_available = config.GROQ_ASK_API_KEY or config.GROQ_API_KEY
    if not key_available:
        err = "Manca GROQ_API_KEY, quindi per ora non riesco a usare /ask."
        return err, history

    temp = temperature if temperature is not None else config.GROQ_ASK_TEMPERATURE
    messages = history + [{"role": "user", "content": new_user_message}]
    answer = await _try_conversation(messages, temp)
    updated_history = messages + [{"role": "assistant", "content": answer}]
    return answer, updated_history
