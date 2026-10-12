"""Inspect MWAPI configuration; only --test sends a paid generation request."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (
    LLM_API_FORMAT,
    LLM_API_KEY,
    LLM_BASE_INPUT_USD_PER_MTOK,
    LLM_BASE_OUTPUT_USD_PER_MTOK,
    LLM_MAX_DAILY_USD,
    LLM_MAX_RUN_USD,
    LLM_MODEL,
    LLM_PRICE_MULTIPLIER,
    LLM_TIMEOUT,
)
from src.llm import api_base_url, generate_text, safe_error, validate_config
from src.llm_budget import BUDGET


def _list_models() -> None:
    root = api_base_url().removesuffix("/v1")
    auth_options = [
        {"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01"},
        {"Authorization": f"Bearer {LLM_API_KEY}", "anthropic-version": "2023-06-01"},
    ]
    if LLM_API_FORMAT == "openai":
        auth_options = [{"Authorization": f"Bearer {LLM_API_KEY}"}]
    models = None
    denied_statuses = []
    for headers in auth_options:
        request = urllib.request.Request(f"{root}/v1/models", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=LLM_TIMEOUT) as response:
                models = json.load(response).get("data", [])
            break
        except urllib.error.HTTPError as error:
            if error.code not in (401, 403):
                raise
            denied_statuses.append(error.code)
    if models is None:
        statuses = "/".join(map(str, denied_statuses)) or "unknown"
        raise ValueError(
            f"MWAPI denied GET /v1/models ({statuses}). Some keys cannot view the "
            "catalog; copy the exact model ID from the dashboard. This does not "
            "prove that POST /v1/messages is unavailable."
        )
    if not models:
        raise ValueError("MWAPI did not return model IDs; copy the exact ID from its dashboard.")
    for model in models:
        print(model["id"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", action="store_true", help="List model IDs exposed by MWAPI")
    parser.add_argument("--test", action="store_true", help="Make one short paid Claude call")
    parser.add_argument("--budget", action="store_true", help="Show the local budget ledger")
    args = parser.parse_args(argv)

    print(f"API format: {LLM_API_FORMAT}")
    print(f"Base URL: {api_base_url()}")
    print(f"Model: {LLM_MODEL or '(set exact MWAPI model ID in .env)'}")
    print(f"API key: {'configured' if LLM_API_KEY else 'missing'}")
    print(
        "Estimated effective rates: "
        f"${LLM_BASE_INPUT_USD_PER_MTOK * LLM_PRICE_MULTIPLIER:g}/M input, "
        f"${LLM_BASE_OUTPUT_USD_PER_MTOK * LLM_PRICE_MULTIPLIER:g}/M output "
        f"(base ${LLM_BASE_INPUT_USD_PER_MTOK:g}/${LLM_BASE_OUTPUT_USD_PER_MTOK:g} "
        f"x {LLM_PRICE_MULTIPLIER:g})"
    )
    print(f"Caps: ${LLM_MAX_RUN_USD:g}/run, ${LLM_MAX_DAILY_USD:g}/UTC day")

    try:
        if args.budget:
            print(BUDGET.snapshot())
        if args.models:
            if not LLM_API_KEY:
                raise ValueError("Set LLM_API_KEY before listing models.")
            _list_models()
        if args.test:
            validate_config()
            print(
                generate_text(
                    "Reply with exactly one word: OK.",
                    "Connection check.",
                    max_tokens=16,
                    model=LLM_MODEL,
                )
            )
        if not (args.models or args.test or args.budget):
            validate_config()
            print("Configuration is complete. No API request was sent.")
        return 0
    except Exception as error:  # noqa: BLE001 - CLI sanitizes provider errors.
        message = safe_error(error)
        if "GROUP_NOT_ALLOWED" in message:
            message += (
                "\nMWAPI recognized the key but its assigned group is disabled for this "
                "account. Reassign/regenerate the key under an allowed high-speed group "
                "in the MWAPI dashboard, or contact MWAPI support."
            )
        print(f"Error: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
