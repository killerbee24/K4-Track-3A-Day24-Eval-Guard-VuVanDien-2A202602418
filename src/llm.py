"""Shared MWAPI/Claude access for generation, evaluation, and guardrails."""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any

from config import (
    ENABLE_LLM_ENRICHMENT,
    ENRICHMENT_MODEL,
    EVALUATOR_EMBEDDING_MODEL,
    EVALUATOR_MODEL,
    GUARD_MODEL,
    LLM_API_FORMAT,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_OUTPUT_TOKENS,
    LLM_MODEL,
    LLM_TIMEOUT,
)
from src.llm_budget import BUDGET, langchain_budget_callback, response_usage

_MANAGED_CLIENT_IDS: set[int] = set()


def is_configured() -> bool:
    """Return whether live LLM calls have an API key and model."""
    return os.getenv("RAG_OFFLINE", "0") != "1" and bool(
        LLM_API_KEY and LLM_API_KEY != "sk-..." and LLM_MODEL
    )


def is_enrichment_configured() -> bool:
    """M5 is opt-in because it can make one paid request per chunk."""
    return ENABLE_LLM_ENRICHMENT and is_configured()


def validate_config(model: str | None = None) -> None:
    if not is_configured():
        raise ValueError(
            "Set LLM_API_KEY and the exact MWAPI LLM_MODEL in .env before live calls."
        )
    if LLM_API_FORMAT not in {"anthropic", "openai"}:
        raise ValueError("LLM_API_FORMAT must be 'anthropic' or 'openai'.")
    if LLM_TIMEOUT <= 0:
        raise ValueError("LLM_TIMEOUT must be greater than zero.")
    if not (model or LLM_MODEL):
        raise ValueError("The selected LLM model ID is blank.")


def api_base_url() -> str:
    """Return the SDK base URL without producing /v1/v1/messages."""
    base = LLM_BASE_URL.rstrip("/")
    if LLM_API_FORMAT == "anthropic":
        return base.removesuffix("/v1")
    return base if base.endswith("/v1") else base + "/v1"


@lru_cache(maxsize=1)
def get_client():
    """Reuse one SDK client across all direct generation calls."""
    validate_config()
    kwargs = {
        "api_key": LLM_API_KEY,
        "base_url": api_base_url(),
        "timeout": LLM_TIMEOUT,
        "max_retries": 1,
    }
    if LLM_API_FORMAT == "anthropic":
        from anthropic import Anthropic

        client = Anthropic(**kwargs)
    else:
        from openai import OpenAI

        client = OpenAI(**kwargs)
    _MANAGED_CLIENT_IDS.add(id(client))
    return client


def _extract_anthropic_text(response: Any) -> str:
    return "".join(
        block.text
        for block in getattr(response, "content", [])
        if getattr(block, "type", None) == "text"
    )


def generate_with_metadata(
    system: str,
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 512,
    client=None,
    json_response: bool = False,
) -> tuple[str, str]:
    """Generate text and return ``(content, provider_model_id)``.

    An explicitly supplied OpenAI-shaped mock/client remains supported so the
    starter's offline unit tests do not need network access.
    """
    selected_model = (model or LLM_MODEL).strip()
    if client is None:
        validate_config(selected_model)
        client = get_client()
    elif not selected_model:
        raise ValueError("A model ID is required when using an injected client.")

    capped_tokens = min(max(1, int(max_tokens)), LLM_MAX_OUTPUT_TOKENS)
    # Only clients created by get_client() are considered billable. Explicit
    # injected mocks used by offline tests must never touch the budget ledger.
    billable = is_configured() and id(client) in _MANAGED_CLIENT_IDS
    reservation = (
        BUDGET.reserve(system, prompt, max_output_tokens=capped_tokens)
        if billable
        else None
    )
    try:
        # Prefer capability detection for injected offline OpenAI mocks.
        if hasattr(client, "chat"):
            kwargs = {
                "model": selected_model,
                "temperature": 0,
                "max_tokens": capped_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            }
            if json_response:
                kwargs["response_format"] = {"type": "json_object"}
            response = client.chat.completions.create(**kwargs)
            text = response.choices[0].message.content or ""
        else:
            response = client.messages.create(
                model=selected_model,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=capped_tokens,
                temperature=0,
            )
            text = _extract_anthropic_text(response)
    except Exception as error:
        if reservation is not None:
            status_code = getattr(error, "status_code", None)
            if status_code in (400, 401, 403, 404, 422):
                # Rejected before inference, so it is not token-billed.
                BUDGET.cancel(reservation)
            else:
                # Timeouts/transport failures can occur after inference.
                BUDGET.commit(reservation)
        raise

    if reservation is not None:
        BUDGET.commit(reservation, *response_usage(response))
    if not text.strip():
        raise ValueError("The LLM returned empty content.")
    reported_model = getattr(response, "model", None)
    used_model = (
        reported_model
        if isinstance(reported_model, str) and reported_model.strip()
        else selected_model
    )
    return text.strip(), used_model


def generate_text(
    system: str,
    prompt: str,
    max_tokens: int = 512,
    *,
    model: str | None = None,
    client=None,
) -> str:
    """Generate deterministic text through MWAPI's Anthropic endpoint."""
    text, _ = generate_with_metadata(
        system,
        prompt,
        model=model or ENRICHMENT_MODEL,
        max_tokens=max_tokens,
        client=client,
    )
    return text


def generate_json(
    system: str,
    payload: str,
    *,
    model: str,
    max_tokens: int = 512,
    client=None,
) -> dict:
    """Generate and validate one JSON object on Anthropic or OpenAI protocol."""
    text, _ = generate_with_metadata(
        system,
        payload,
        model=model,
        max_tokens=max_tokens,
        client=client,
        json_response=True,
    )
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        result = json.loads(cleaned[start : end + 1])
    if not isinstance(result, dict):
        raise ValueError("The LLM JSON response must be an object.")
    return result


def safe_error(error: Exception) -> str:
    """Keep provider errors useful without logging the configured API key."""
    message = str(error)
    return message.replace(LLM_API_KEY, "[REDACTED]") if LLM_API_KEY else message


def evaluator_model_ids() -> list[str]:
    """Actual model identifiers used for the RAGAS call."""
    return sorted({EVALUATOR_MODEL, EVALUATOR_EMBEDDING_MODEL})


def _chat_model(model: str, *, max_tokens: int):
    validate_config(model)
    capped_tokens = min(max_tokens, LLM_MAX_OUTPUT_TOKENS)
    callbacks = [langchain_budget_callback()]
    if LLM_API_FORMAT == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model,
            anthropic_api_key=LLM_API_KEY,
            anthropic_api_url=api_base_url(),
            temperature=0,
            max_tokens=capped_tokens,
            timeout=LLM_TIMEOUT,
            max_retries=1,
            callbacks=callbacks,
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        openai_api_key=LLM_API_KEY,
        openai_api_base=api_base_url(),
        temperature=0,
        max_tokens=capped_tokens,
        request_timeout=LLM_TIMEOUT,
        max_retries=1,
        callbacks=callbacks,
    )


def get_eval_models():
    """Build an explicit MWAPI Claude judge and local embedding model for RAGAS."""
    # RAGAS 0.1.x expects short JSON/statement outputs. A 256-token ceiling is
    # sufficient for these prompts and keeps the 200-call 50q batch inside the
    # configured $3/run circuit breaker on the MWAPI 5x tier.
    judge = _chat_model(EVALUATOR_MODEL, max_tokens=256)
    from langchain_community.embeddings import HuggingFaceEmbeddings

    embeddings = HuggingFaceEmbeddings(
        model_name=EVALUATOR_EMBEDDING_MODEL,
        encode_kwargs={"normalize_embeddings": True},
    )
    return judge, embeddings


def get_guard_model():
    """Build the budget-tracked main LLM injected into NeMo Guardrails."""
    return _chat_model(GUARD_MODEL, max_tokens=64)
