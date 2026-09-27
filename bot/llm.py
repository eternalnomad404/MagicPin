"""Thin async wrapper over the Anthropic Messages API with JSON parsing."""
from __future__ import annotations

import asyncio
import json
import time
import re
from typing import Any, Optional

from anthropic import AsyncAnthropic

from . import config
from .logging_util import log_event

_client: Optional[AsyncAnthropic] = None
_sem = asyncio.Semaphore(config.LLM_CONCURRENCY)


def client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY, timeout=config.LLM_TIMEOUT_S, max_retries=1)
    return _client


def extract_json(text: str) -> Optional[dict[str, Any]]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


async def complete_json(system: str, user: str, model: str, max_tokens: int = 900,
                        tag: str = "llm") -> Optional[dict[str, Any]]:
    """One call that must return a JSON object.

    Claude 5-generation models have no temperature knob; the composer's
    determinism comes from caching by context versions (see composer.py).
    """
    t0 = time.time()
    async with _sem:
        try:
            resp = await client().messages.create(
                model=model,
                max_tokens=max_tokens,
                thinking={"type": "adaptive"},
                output_config={"effort": config.LLM_EFFORT},
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # network, auth, rate limit: caller decides fallback
            log_event("llm_error", tag=tag, model=model, error=str(exc)[:300])
            return None
    text = "".join(getattr(b, "text", "") for b in resp.content)
    data = extract_json(text)
    log_event("llm_call", tag=tag, model=model,
              input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
              parsed=data is not None, latency_ms=int((time.time() - t0) * 1000))
    return data
