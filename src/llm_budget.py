"""Local request/token/cost circuit breaker for paid LLM calls.

The provider dashboard quota remains the authoritative hard stop.  This module
adds a second, fail-closed limit inside the lab so a loop cannot silently spend
dozens of dollars on the MWAPI high-speed tier.
"""
from __future__ import annotations

import json
import math
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import (
    LLM_BASE_INPUT_USD_PER_MTOK,
    LLM_BASE_OUTPUT_USD_PER_MTOK,
    LLM_MAX_DAILY_USD,
    LLM_MAX_OUTPUT_TOKENS,
    LLM_MAX_REQUESTS,
    LLM_MAX_RUN_USD,
    LLM_PRICE_MULTIPLIER,
    ROOT_DIR,
)


class BudgetExceeded(RuntimeError):
    """Raised before an API request would cross a configured limit."""


@dataclass(frozen=True)
class Reservation:
    id: str
    estimated_input_tokens: int
    max_output_tokens: int
    reserved_usd: float


def _usage_value(usage: Any, *names: str) -> int | None:
    if usage is None:
        return None
    for name in names:
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        if isinstance(value, int) and value >= 0:
            return value
    return None


def response_usage(response: Any) -> tuple[int | None, int | None]:
    """Read token usage from either Anthropic, OpenAI, or LangChain responses."""
    usage = getattr(response, "usage", None)
    if usage is not None:
        return (
            _usage_value(usage, "input_tokens", "prompt_tokens"),
            _usage_value(usage, "output_tokens", "completion_tokens"),
        )

    llm_output = getattr(response, "llm_output", None) or {}
    usage = llm_output.get("token_usage") or llm_output.get("usage")
    input_tokens = _usage_value(usage, "input_tokens", "prompt_tokens")
    output_tokens = _usage_value(usage, "output_tokens", "completion_tokens")
    if input_tokens is not None or output_tokens is not None:
        return input_tokens, output_tokens

    # Some LangChain chat integrations attach usage to the generated message.
    for generation_group in getattr(response, "generations", []) or []:
        for generation in generation_group or []:
            message = getattr(generation, "message", None)
            usage = getattr(message, "usage_metadata", None)
            input_tokens = _usage_value(usage, "input_tokens")
            output_tokens = _usage_value(usage, "output_tokens")
            if input_tokens is not None or output_tokens is not None:
                return input_tokens, output_tokens
    return None, None


class BudgetManager:
    def __init__(self, ledger_path: Path | None = None):
        self.ledger_path = ledger_path or Path(ROOT_DIR) / ".cache" / "llm_budget.json"
        self._lock = threading.RLock()
        self._reservations: dict[str, Reservation] = {}
        self._requests = 0
        self._spent_usd = 0.0

    @staticmethod
    def _validate_settings() -> None:
        numeric = {
            "LLM_PRICE_MULTIPLIER": LLM_PRICE_MULTIPLIER,
            "LLM_BASE_INPUT_USD_PER_MTOK": LLM_BASE_INPUT_USD_PER_MTOK,
            "LLM_BASE_OUTPUT_USD_PER_MTOK": LLM_BASE_OUTPUT_USD_PER_MTOK,
            "LLM_MAX_RUN_USD": LLM_MAX_RUN_USD,
            "LLM_MAX_DAILY_USD": LLM_MAX_DAILY_USD,
            "LLM_MAX_REQUESTS": LLM_MAX_REQUESTS,
            "LLM_MAX_OUTPUT_TOKENS": LLM_MAX_OUTPUT_TOKENS,
        }
        invalid = [name for name, value in numeric.items() if value <= 0]
        if invalid:
            raise ValueError(f"LLM budget settings must be positive: {', '.join(invalid)}")

    @staticmethod
    def estimate_input_tokens(*parts: str) -> int:
        # One Unicode character per token is intentionally conservative for
        # Vietnamese.  It can stop early, but it will not understate long input.
        return max(1, sum(len(part or "") for part in parts))

    @staticmethod
    def cost_usd(input_tokens: int, output_tokens: int) -> float:
        input_rate = LLM_BASE_INPUT_USD_PER_MTOK * LLM_PRICE_MULTIPLIER
        output_rate = LLM_BASE_OUTPUT_USD_PER_MTOK * LLM_PRICE_MULTIPLIER
        return (
            input_tokens * input_rate + output_tokens * output_rate
        ) / 1_000_000

    def _read_daily_spend(self) -> float:
        if not self.ledger_path.exists():
            return 0.0
        try:
            payload = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BudgetExceeded(
                f"Cannot safely read LLM budget ledger {self.ledger_path}: {error}"
            ) from error
        if payload.get("date_utc") != datetime.now(timezone.utc).date().isoformat():
            return 0.0
        spent = payload.get("spent_usd", 0.0)
        if not isinstance(spent, (int, float)) or not math.isfinite(spent) or spent < 0:
            raise BudgetExceeded("LLM budget ledger contains an invalid spent_usd value.")
        return float(spent)

    def _write_daily_spend(self, spent_usd: float) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "date_utc": datetime.now(timezone.utc).date().isoformat(),
            "spent_usd": round(spent_usd, 8),
        }
        temp_path = self.ledger_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(self.ledger_path)

    def reserve(self, *prompt_parts: str, max_output_tokens: int) -> Reservation:
        self._validate_settings()
        capped_output = min(max(1, int(max_output_tokens)), LLM_MAX_OUTPUT_TOKENS)
        estimated_input = self.estimate_input_tokens(*prompt_parts)
        reserved_usd = self.cost_usd(estimated_input, capped_output)
        with self._lock:
            reserved_total = sum(r.reserved_usd for r in self._reservations.values())
            if self._requests + 1 > LLM_MAX_REQUESTS:
                raise BudgetExceeded(
                    f"LLM request limit reached ({LLM_MAX_REQUESTS} requests per process)."
                )
            if self._spent_usd + reserved_total + reserved_usd > LLM_MAX_RUN_USD:
                raise BudgetExceeded(
                    f"Request blocked: estimated run cost would exceed ${LLM_MAX_RUN_USD:.2f}."
                )
            daily_spend = self._read_daily_spend()
            if daily_spend + reserved_total + reserved_usd > LLM_MAX_DAILY_USD:
                raise BudgetExceeded(
                    f"Request blocked: estimated daily cost would exceed ${LLM_MAX_DAILY_USD:.2f}."
                )
            reservation = Reservation(
                id=uuid.uuid4().hex,
                estimated_input_tokens=estimated_input,
                max_output_tokens=capped_output,
                reserved_usd=reserved_usd,
            )
            self._reservations[reservation.id] = reservation
            self._requests += 1
            return reservation

    def commit(
        self,
        reservation: Reservation,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> float:
        with self._lock:
            active = self._reservations.pop(reservation.id, None)
            if active is None:
                return 0.0
            cost = (
                self.cost_usd(input_tokens, output_tokens)
                if input_tokens is not None and output_tokens is not None
                else active.reserved_usd
            )
            self._spent_usd += cost
            self._write_daily_spend(self._read_daily_spend() + cost)
            return cost

    def cancel(self, reservation: Reservation) -> None:
        """Release a request rejected before inference, such as HTTP 401/403."""
        with self._lock:
            self._reservations.pop(reservation.id, None)

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            return {
                "requests_this_process": self._requests,
                "spent_this_process_usd": round(self._spent_usd, 8),
                "reserved_this_process_usd": round(
                    sum(r.reserved_usd for r in self._reservations.values()), 8
                ),
                "spent_today_utc_usd": round(self._read_daily_spend(), 8),
                "max_run_usd": LLM_MAX_RUN_USD,
                "max_daily_usd": LLM_MAX_DAILY_USD,
                "max_requests": LLM_MAX_REQUESTS,
            }


BUDGET = BudgetManager()


def langchain_budget_callback():
    """Create a callback that reserves before and accounts after LangChain calls."""
    from langchain_core.callbacks import BaseCallbackHandler

    class CostCallback(BaseCallbackHandler):
        raise_error = True

        def __init__(self):
            self._by_run: dict[str, Reservation] = {}

        def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):  # noqa: ANN001
            invocation = kwargs.get("invocation_params") or {}
            max_tokens = invocation.get("max_tokens") or LLM_MAX_OUTPUT_TOKENS
            reservation = BUDGET.reserve(
                *(str(prompt) for prompt in prompts), max_output_tokens=max_tokens
            )
            self._by_run[str(run_id)] = reservation

        def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):  # noqa: ANN001
            flattened = [str(message) for batch in messages for message in batch]
            invocation = kwargs.get("invocation_params") or {}
            max_tokens = invocation.get("max_tokens") or LLM_MAX_OUTPUT_TOKENS
            reservation = BUDGET.reserve(
                *flattened, max_output_tokens=max_tokens
            )
            self._by_run[str(run_id)] = reservation

        def on_llm_end(self, response, *, run_id, **kwargs):  # noqa: ANN001
            reservation = self._by_run.pop(str(run_id), None)
            if reservation is not None:
                BUDGET.commit(reservation, *response_usage(response))

        def on_llm_error(self, error, *, run_id, **kwargs):  # noqa: ANN001
            reservation = self._by_run.pop(str(run_id), None)
            if reservation is not None:
                status_code = getattr(error, "status_code", None)
                if status_code in (400, 401, 403, 404, 422):
                    BUDGET.cancel(reservation)
                else:
                    # Timeouts/transport failures may happen after inference.
                    BUDGET.commit(reservation)

    return CostCallback()
