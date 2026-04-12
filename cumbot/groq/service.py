from __future__ import annotations

import logging

from groq import AsyncGroq

from cumbot import config

LOGGER = logging.getLogger(__name__)


def is_rate_limit_error(exc: Exception) -> bool:
    payload = f"{type(exc).__name__}: {exc}".lower()
    return any(
        fragment in payload
        for fragment in ("429", "rate_limit", "rate limit", "ratelimit", "too many")
    )


class GroqService:
    def __init__(self) -> None:
        self._client: AsyncGroq | None = None

    def _get_client(self) -> AsyncGroq | None:
        if not config.GROQ_API_KEY:
            return None
        if self._client is None:
            self._client = AsyncGroq(api_key=config.GROQ_API_KEY)
        return self._client

    async def generate_text(
        self,
        *,
        model: str,
        system_instruction: str,
        user_prompt: str,
        temperature: float,
        max_output_tokens: int,
    ) -> str | None:
        client = self._get_client()
        if client is None:
            return None
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_output_tokens,
        )
        text = response.choices[0].message.content
        return text.strip() if text else None


groq_service = GroqService()
