"""Conservative model-family identity for verifier independence claims.

Different API endpoints, provider aliases, or model version strings do not by
themselves prove that two calls are independent.  QuantBT only claims an
independent verifier route when both the serving provider and the recognised
foundation-model family differ.  Unknown families fail closed.
"""

from __future__ import annotations

import re


_PROVIDER_FAMILY = {
    "anthropic": "claude",
    "openai": "openai",
    "azure-openai": "openai",
    "azure_openai": "openai",
    "google": "gemini",
    "google-ai": "gemini",
    "google_ai": "gemini",
    "deepseek": "deepseek",
    "qwen": "qwen",
    "alibaba": "qwen",
    "mistral": "mistral",
    "cohere": "cohere",
    "xai": "grok",
    "x-ai": "grok",
    "moonshot": "moonshot",
}


def infer_foundation_model_family(provider: str, model: str) -> str:
    """Return a conservative family label, or ``""`` when it is unproved.

    Model names take precedence over provider defaults so aggregators such as
    OpenRouter can still be classified.  Provider fallback is reserved for
    vendors whose own endpoint identifies the family.
    """

    provider_name = str(provider or "").strip().lower()
    model_name = str(model or "").strip().lower()

    if "claude" in model_name:
        return "claude"
    if "gpt" in model_name or "chatgpt" in model_name or re.match(
        r"^o[1-9](?:$|[-_.])", model_name
    ):
        return "openai"
    if "gemini" in model_name:
        return "gemini"
    if "deepseek" in model_name:
        return "deepseek"
    if "qwen" in model_name:
        return "qwen"
    if "llama" in model_name:
        return "llama"
    if "mistral" in model_name or "mixtral" in model_name:
        return "mistral"
    if "grok" in model_name:
        return "grok"
    if "command-r" in model_name or "command_r" in model_name:
        return "cohere"
    if "ernie" in model_name or "wenxin" in model_name:
        return "ernie"
    if "doubao" in model_name:
        return "doubao"
    if "moonshot" in model_name or "kimi" in model_name:
        return "moonshot"
    if "baichuan" in model_name:
        return "baichuan"

    return _PROVIDER_FAMILY.get(provider_name, "")


def has_independent_model_route(
    *,
    builder_provider: str,
    builder_model: str,
    verifier_provider: str,
    verifier_model: str,
) -> bool:
    """Whether a route can honestly carry a dual-model independence claim."""

    builder_provider_name = str(builder_provider or "").strip().lower()
    verifier_provider_name = str(verifier_provider or "").strip().lower()
    if not builder_provider_name or not verifier_provider_name:
        return False
    if builder_provider_name == verifier_provider_name:
        return False

    builder_family = infer_foundation_model_family(builder_provider, builder_model)
    verifier_family = infer_foundation_model_family(verifier_provider, verifier_model)
    return bool(
        builder_family
        and verifier_family
        and builder_family != verifier_family
    )


__all__ = [
    "has_independent_model_route",
    "infer_foundation_model_family",
]
