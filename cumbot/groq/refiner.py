from __future__ import annotations

import logging
import re

from cumbot import config
from cumbot.groq.service import groq_service, is_rate_limit_error
from cumbot.markov.tone import TONE_HINTS

# Riconosce rifiuti del modello LLM (Llama safety guardrails).
# Llama risponde con testo normale invece di sollevare un'eccezione.
_REFUSAL_RE = re.compile(
    r"^(mi dispiace|sorry|non posso|i cannot|i can'?t|non sono in grado"
    r"|come assistente|as an (ai|assistant))",
    re.IGNORECASE,
)

LOGGER = logging.getLogger(__name__)


SYSTEM_PROMPT = """Sei un amplificatore per un bot di una chat di gruppo italiana volgare e informale.
Ricevi una bozza grezza generata automaticamente.

Il tuo compito NON e riscriverla: devi prendere il concetto centrale della bozza e renderlo
piu estremo, piu graffiante o piu divertente — nello STESSO registro, con le STESSE parole chiave.
Regole ferree:
- Mantieni il verbo principale e i sostantivi chiave della bozza. Non sostituirli.
- Non aggiungere contenuto sessuale o violento se non e gia presente nella bozza.
- Non inventare argomenti, persone o azioni nuove.
- Non addolcire o censurare insulti gia presenti nella bozza: lasciali intatti o intensificali.
- Non aggiungere parolacce o insulti nuovi se la bozza non li contiene gia.
- Conta quante volte ogni parola volgare appare nella bozza. Nell'output quella parola non deve apparire piu volte di quante ne appaiono nella bozza. Es: se "cazzo" e nella bozza 1 volta, nell'output puo apparire al massimo 1 volta.
- Non usare "del cazzo", "di merda", "del cazzo" come aggettivi generici per amplificare — sono filler abusati. Usa invece aggettivi specifici: assurdo, ridicolo, marcio, totale, puro, squallido, inutile, orrendo.
- Se la bozza contiene Emoji, mantienile esattamente come sono nella stessa posizione. Non rimuoverle mai.
- Se la bozza contiene "@user", mantienilo esattamente com'e nella stessa posizione. Non rimuoverlo mai.
- Correggi la punteggiatura solo se serve alla leggibilita.
- Non inserire testo a meta frase se questo costringe a tagliare la parte finale. Preferisci sostituire singole parole con sinonimi piu forti.
- Non troncare mai la parte finale della bozza. Se termina con una domanda o richiesta diretta ("mi dai X", "sai come X"), mantieni l'intera locuzione intatta.
- Se la bozza non termina con '?', l'output non deve MAI terminare con '?'. Non trasformare affermazioni in domande aggiungendo un punto interrogativo finale.
- Non tradurre mai termini inglesi usati come slang o gergo nel testo italiano. Lasciali esattamente come appaiono nella bozza (es. "bro", "fra", "cringe", "vibe", "hype", "random", "exp", "gg", "rip", "lol", "mid", "goat", "based", "sus", "grind", "lowkey", "bruh", "fr","crush" ecc.).
- Se la bozza e gia grammaticalmente corretta e di senso compiuto, apporta solo modifiche minime.
Tono: chat italiana informale, diretta, senza filtri.
Niente emoji in eccesso. Niente punteggiatura doppia tipo "? ?" o "! !".
Un solo messaggio. Nessun prefisso "nome: testo". Nessuna lista. Nessuna spiegazione."""


async def refine_draft(
    draft: str,
    recent_context: list[dict],
    persona_ids: list[str] | None,
    tone: str = "neutral",
    temperature: float | None = None,
    trigger_input: str | None = None,
) -> str:
    if not draft.strip():
        return draft

    system_prompt = SYSTEM_PROMPT
    if persona_ids:
        system_prompt += (
            "\nLa bozza e stata generata sulla voce di persone specifiche del gruppo: "
            "mantieni quel tipo di impronta e di lessico."
        )
    tone_hint = TONE_HINTS.get(tone, "")
    if tone_hint:
        system_prompt += f"\n{tone_hint}"

    # Per i roast (insulto diretto al bot): contestualizza la risposta come contrattacco
    if tone == "aggressive" and trigger_input and trigger_input.strip():
        cleaned_trigger = re.sub(r"@\w+", "", trigger_input).strip()
        if cleaned_trigger:
            system_prompt += (
                f"\nL'utente ha scritto al bot: \"{cleaned_trigger}\". "
                "Usa la bozza come spunto lessicale ma formula un contrattacco diretto in prima persona, "
                "come se il bot stesse ribattendo all'insulto. Mantieni il registro del gruppo."
            )

    context_lines = [
        f"{item.get('speaker') or item.get('display_name') or item.get('username') or 'unknown'}: {item.get('text', '').strip()}"
        for item in recent_context
        if item.get("text")
    ]
    draft_words = len(draft.split())
    user_prompt = (
        "Ultimi messaggi del gruppo:\n"
        + ("\n".join(context_lines) if context_lines else "(nessun contesto recente)")
        + f"\n\nBozza ({draft_words} parole):\n{draft}"
        + "\n\nRispondi con un solo messaggio. Mantieni una lunghezza simile alla bozza."
    )

    try:
        response = await groq_service.generate_text(
            model=config.GROQ_REFINER_MODEL,
            system_instruction=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature if temperature is not None else config.GROQ_REFINER_TEMPERATURE,
            max_output_tokens=160,
        )
    except Exception as exc:
        if is_rate_limit_error(exc):
            LOGGER.warning("Groq rate limit → fallback Markov: %s", exc)
        else:
            LOGGER.warning("Groq error (%s) → fallback Markov: %s", type(exc).__name__, exc)
        return draft

    if response is None:
        LOGGER.warning("Groq returned None → fallback Markov")
        return draft

    if _REFUSAL_RE.match(response.strip()):
        LOGGER.warning("Groq refusal detected → fallback Markov: %s", response[:80])
        return draft

    # Ripristina @user se Groq lo ha rimosso
    from cumbot.markov.rendering import PLACEHOLDER
    if PLACEHOLDER in draft and PLACEHOLDER not in response:
        response = response.rstrip(" .!?") + f" {PLACEHOLDER}."

    return response
