from __future__ import annotations

from cumbot import config
from cumbot.groq.service import groq_service, is_rate_limit_error


ASK_SYSTEM_PROMPT = """Sei un assistente utile, diretto e informale.
Rispondi in italiano in modo chiaro e naturale.
Se una richiesta e ambigua, fai l'assunzione piu ragionevole invece di diventare prolisso."""


async def ask_groq(question: str, temperature: float | None = None) -> str:
    if not config.GROQ_API_KEY:
        return "Manca GROQ_API_KEY, quindi per ora non riesco a usare /ask."

    try:
        response = await groq_service.generate_text(
            model=config.GROQ_ASK_MODEL,
            system_instruction=ASK_SYSTEM_PROMPT,
            user_prompt=question,
            temperature=temperature if temperature is not None else config.GROQ_ASK_TEMPERATURE,
            max_output_tokens=400,
        )
    except Exception as exc:
        if is_rate_limit_error(exc):
            return "Troppe richieste al modello AI, riprova tra un momento."
        return "Il modello AI sta avendo problemi, riprova tra poco."

    return response or "Il modello AI sta avendo problemi, riprova tra poco."
