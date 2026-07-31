"""Advisory-only GROQ text generation.

Output from generate_text is always advisory — callers must store it in a clearly
separate field/flag, never as if a human wrote or approved it.
"""

from __future__ import annotations

import asyncio
import logging

from groq import AsyncGroq

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_groq_client: AsyncGroq | None = None


def _get_client(settings: Settings | None = None) -> AsyncGroq | None:
    global _groq_client
    settings = settings or get_settings()
    if not settings.groq_api_key:
        return None
    if _groq_client is None:
        _groq_client = AsyncGroq(api_key=settings.groq_api_key)
    return _groq_client


async def generate_text(
    prompt: str,
    *,
    model: str | None = None,
    timeout: float = 10,
    max_retries: int = 2,
    settings: Settings | None = None,
) -> str | None:
    settings = settings or get_settings()
    client = _get_client(settings)
    if client is None:
        return None

    chosen_model = model or settings.groq_model
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=chosen_model,
                    messages=[{"role": "user", "content": prompt}],
                ),
                timeout=timeout,
            )
            content = response.choices[0].message.content
            return content.strip() if content else None
        except Exception as exc:  # noqa: BLE001 — advisory path must never raise
            last_error = exc
            if attempt < max_retries:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

    logger.warning(
        "GROQ generate_text failed",
        extra={"extra_data": {"model": chosen_model, "error": str(last_error), "prompt_len": len(prompt)}},
    )
    return None
