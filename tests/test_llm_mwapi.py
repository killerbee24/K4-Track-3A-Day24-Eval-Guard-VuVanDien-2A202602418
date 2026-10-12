from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.llm import generate_with_metadata
from src import llm_budget


def test_anthropic_message_shape_with_injected_client():
    client = SimpleNamespace(messages=Mock())
    client.messages.create.return_value = SimpleNamespace(
        model="claude-provider-snapshot",
        content=[SimpleNamespace(type="text", text="OK")],
        usage=SimpleNamespace(input_tokens=3, output_tokens=1),
    )
    text, model = generate_with_metadata(
        "system", "prompt", model="claude-requested", max_tokens=16, client=client
    )
    assert (text, model) == ("OK", "claude-provider-snapshot")
    call = client.messages.create.call_args.kwargs
    assert call["system"] == "system"
    assert call["messages"] == [{"role": "user", "content": "prompt"}]
    assert call["max_tokens"] == 16


def test_budget_blocks_before_crossing_run_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_budget, "LLM_PRICE_MULTIPLIER", 1.0)
    monkeypatch.setattr(llm_budget, "LLM_BASE_INPUT_USD_PER_MTOK", 1.0)
    monkeypatch.setattr(llm_budget, "LLM_BASE_OUTPUT_USD_PER_MTOK", 1.0)
    monkeypatch.setattr(llm_budget, "LLM_MAX_RUN_USD", 0.00001)
    monkeypatch.setattr(llm_budget, "LLM_MAX_DAILY_USD", 1.0)
    monkeypatch.setattr(llm_budget, "LLM_MAX_REQUESTS", 10)
    monkeypatch.setattr(llm_budget, "LLM_MAX_OUTPUT_TOKENS", 100)
    manager = llm_budget.BudgetManager(tmp_path / "budget.json")
    with pytest.raises(llm_budget.BudgetExceeded, match="run cost"):
        manager.reserve("prompt", max_output_tokens=100)


def test_budget_records_actual_usage(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_budget, "LLM_PRICE_MULTIPLIER", 1.0)
    monkeypatch.setattr(llm_budget, "LLM_BASE_INPUT_USD_PER_MTOK", 2.0)
    monkeypatch.setattr(llm_budget, "LLM_BASE_OUTPUT_USD_PER_MTOK", 10.0)
    monkeypatch.setattr(llm_budget, "LLM_MAX_RUN_USD", 1.0)
    monkeypatch.setattr(llm_budget, "LLM_MAX_DAILY_USD", 1.0)
    monkeypatch.setattr(llm_budget, "LLM_MAX_REQUESTS", 10)
    monkeypatch.setattr(llm_budget, "LLM_MAX_OUTPUT_TOKENS", 100)
    manager = llm_budget.BudgetManager(tmp_path / "budget.json")
    reservation = manager.reserve("hello", max_output_tokens=10)
    charged = manager.commit(reservation, input_tokens=100, output_tokens=20)
    assert charged == pytest.approx(0.0004)
    assert manager.snapshot()["spent_today_utc_usd"] == pytest.approx(0.0004)


def test_budget_cancel_does_not_charge_rejected_request(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_budget, "LLM_PRICE_MULTIPLIER", 1.0)
    monkeypatch.setattr(llm_budget, "LLM_BASE_INPUT_USD_PER_MTOK", 1.0)
    monkeypatch.setattr(llm_budget, "LLM_BASE_OUTPUT_USD_PER_MTOK", 1.0)
    monkeypatch.setattr(llm_budget, "LLM_MAX_RUN_USD", 1.0)
    monkeypatch.setattr(llm_budget, "LLM_MAX_DAILY_USD", 1.0)
    monkeypatch.setattr(llm_budget, "LLM_MAX_REQUESTS", 10)
    monkeypatch.setattr(llm_budget, "LLM_MAX_OUTPUT_TOKENS", 100)
    manager = llm_budget.BudgetManager(tmp_path / "budget.json")
    reservation = manager.reserve("hello", max_output_tokens=10)
    manager.cancel(reservation)
    assert manager.snapshot()["spent_today_utc_usd"] == 0


def test_langchain_anthropic_uses_mwapi_base_url(monkeypatch):
    pytest.importorskip("langchain_anthropic")
    from src import llm

    monkeypatch.setattr(llm, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm, "LLM_MODEL", "claude-test")
    monkeypatch.setattr(llm, "LLM_API_FORMAT", "anthropic")
    monkeypatch.setattr(llm, "LLM_BASE_URL", "https://api.mwapi.dev")
    model = llm._chat_model("claude-test", max_tokens=32)
    assert str(model.anthropic_api_url).rstrip("/") == "https://api.mwapi.dev"
    assert model.model == "claude-test"
