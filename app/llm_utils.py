"""Small compatibility helpers for Alexandria's OpenAI-compatible LLM calls.

The application also supports local OpenAI-compatible servers (Ollama, LM
Studio, etc.), so this module keeps their sampling parameters while adapting
requests for OpenAI reasoning models such as GPT-5.6 Luna.
"""

import os
import re
from typing import Any, Dict, Iterable, Optional


_ENV_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def resolve_api_key(configured: Optional[str]) -> str:
    """Resolve an API key from config without requiring a secret in JSON.

    Supported forms are ``env:VAR_NAME`` and ``${VAR_NAME}``.  An empty value
    falls back to ``OPENAI_API_KEY``; values such as ``local`` remain literal
    so Ollama/LM Studio continue to work as before.
    """

    value = str(configured or "").strip()
    if value.startswith("env:"):
        return os.environ.get(value[4:].strip(), "")

    match = _ENV_PATTERN.match(value)
    if match:
        return os.environ.get(match.group(1), "")

    if not value:
        return os.environ.get("OPENAI_API_KEY", "")
    return value


def is_reasoning_model(model_name: str) -> bool:
    """Return whether the model uses the GPT-5/o-series reasoning API shape."""

    name = str(model_name or "").lower().strip()
    return name.startswith(("gpt-5", "o1", "o3", "o4"))


def chat_completion(
    client: Any,
    model_name: str,
    messages: Iterable[Dict[str, Any]],
    *,
    reasoning_effort: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    extra_body: Optional[Dict[str, Any]] = None,
) -> Any:
    """Create a Chat Completions request for local or OpenAI models.

    GPT-5.6/o-series reasoning requests use ``max_completion_tokens`` and do
    not receive local-only sampling controls such as ``top_k``/``min_p``.
    Other OpenAI-compatible backends retain Alexandria's original parameters.
    """

    reasoning_model = is_reasoning_model(model_name)
    kwargs: Dict[str, Any] = {
        "model": model_name,
        "messages": list(messages),
    }

    if max_tokens is not None:
        kwargs["max_completion_tokens" if reasoning_model else "max_tokens"] = max_tokens

    effort = str(reasoning_effort or "").strip()
    if effort:
        kwargs["reasoning_effort"] = effort

    # Sampling controls are intentionally omitted for GPT-5.6 Luna with
    # reasoning effort enabled; the API rejects those controls for reasoning
    # requests.  They remain enabled for local models and for effort=none.
    use_sampling = not reasoning_model or effort.lower() in {"", "none"}
    if use_sampling:
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if presence_penalty is not None:
            kwargs["presence_penalty"] = presence_penalty
        if extra_body:
            kwargs["extra_body"] = extra_body

    return client.chat.completions.create(**kwargs)
