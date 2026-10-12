from __future__ import annotations

"""Phase C: Production Guardrails — Presidio PII + NeMo Guardrails + P95 Latency."""

import asyncio
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (ADVERSARIAL_SET_PATH, GUARDRAILS_CONFIG_DIR, GUARD_MODEL,
                    LATENCY_BUDGET_P95_MS, LLM_API_FORMAT, PRESIDIO_LANGUAGE)


# The lab's PII policy is intentionally limited to high-precision structured
# identifiers. The bundled English spaCy model is not a Vietnamese name model
# and otherwise labels ordinary Vietnamese phrases as PERSON (and strings such
# as ``v2024`` as US_DRIVER_LICENSE), creating unacceptable false positives.
BLOCKED_PII_ENTITIES = {"VN_CCCD", "VN_PHONE", "EMAIL_ADDRESS"}
OUTPUT_REFUSAL = (
    "Xin lỗi, tôi không thể cung cấp định danh cá nhân, thông tin đăng nhập "
    "hoặc dữ liệu bí mật."
)


def _contains_structured_output_secret(text: str) -> bool:
    """High-precision backstop for secrets that an LLM rail may miss randomly."""
    non_public_emails = [
        email
        for email in re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
        if email.lower() != "helpdesk@cty.vn"
    ]
    has_identifier = bool(
        re.search(r"\b(?:\d{9}|\d{12}|0[3-9]\d{8})\b", text)
        or non_public_emails
    )
    has_credential_value = bool(
        re.search(
            r"(?is)\b(?:mật\s*khẩu|password|api\s*key|access\s*token|secret)\b"
            r".{0,80}?(?:\blà\b|\bis\b|:)\s*\S+",
            text,
        )
    )
    return has_identifier or has_credential_value


# ─── Task 9a: Presidio PII Detection ─────────────────────────────────────────

def setup_presidio():
    """Khởi tạo Presidio engine với custom Vietnamese PII recognizers. (Đã implement sẵn)

    Custom recognizers thêm vào:
        VN_CCCD  — số CCCD 12 chữ số hoặc CMND 9 chữ số
        VN_PHONE — số điện thoại Việt Nam (0[3-9]xxxxxxxx)

    Các recognizers mặc định đã có sẵn: EMAIL, PHONE_NUMBER (international), ...
    """
    from presidio_analyzer import AnalyzerEngine, RecognizerRegistry, Pattern, PatternRecognizer
    from presidio_anonymizer import AnonymizerEngine

    cccd_recognizer = PatternRecognizer(
        supported_entity="VN_CCCD",
        patterns=[
            Pattern("CCCD 12 digits", r"\b\d{12}\b", 0.9),
            Pattern("CMND 9 digits",  r"\b\d{9}\b",  0.7),
        ],
    )
    phone_recognizer = PatternRecognizer(
        supported_entity="VN_PHONE",
        patterns=[Pattern("VN mobile", r"\b0[3-9]\d{8}\b", 0.9)],
    )

    registry = RecognizerRegistry()
    registry.load_predefined_recognizers()
    registry.add_recognizer(cccd_recognizer)
    registry.add_recognizer(phone_recognizer)

    analyzer  = AnalyzerEngine(registry=registry)
    anonymizer = AnonymizerEngine()
    return analyzer, anonymizer


def pii_scan(text: str, analyzer=None, anonymizer=None) -> dict:
    """Task 9a: Quét PII trong văn bản bằng Presidio.

    Returns:
        {
          "has_pii":    bool,
          "entities":   [{"type": str, "text": str, "score": float, "start": int, "end": int}],
          "anonymized": str,   # text với PII được thay bằng <TYPE>
        }
    """
    if not isinstance(text, str):
        raise TypeError("PII input must be text.")
    if analyzer is None or anonymizer is None:
        analyzer, anonymizer = setup_presidio()
    results = [
        result
        for result in analyzer.analyze(text=text, language=PRESIDIO_LANGUAGE)
        if result.entity_type in BLOCKED_PII_ENTITIES
    ]
    if not results:
        return {"has_pii": False, "entities": [], "anonymized": text}
    anonymized = anonymizer.anonymize(text=text, analyzer_results=results).text
    entities = [
        {
            "type": result.entity_type,
            "text": text[result.start:result.end],
            "score": round(float(result.score), 3),
            "start": result.start,
            "end": result.end,
        }
        for result in sorted(results, key=lambda row: (row.start, row.end, row.entity_type))
    ]
    return {"has_pii": True, "entities": entities, "anonymized": anonymized}


# ─── Task 9b + 11: NeMo Guardrails ───────────────────────────────────────────

def setup_nemo_rails():
    """Khởi tạo NeMo Guardrails từ guardrails/config.yml. (Đã implement sẵn)

    Config directory: guardrails/
        config.yml  — model + rails config
        rails.co    — câu từ chối Colang 1.0; built-in self-check flows được bật trong YAML
    """
    from nemoguardrails import RailsConfig, LLMRails
    from src.llm import get_guard_model, validate_config

    validate_config(GUARD_MODEL)
    config = RailsConfig.from_path(GUARDRAILS_CONFIG_DIR)
    for model_config in config.models:
        if model_config.type == "main":
            model_config.engine = LLM_API_FORMAT
            model_config.model = GUARD_MODEL
    # Injecting the LangChain model ensures MWAPI's Anthropic base URL and the
    # local budget callback are used instead of NeMo's OpenAI defaults.
    rails = LLMRails(config, llm=get_guard_model())
    return rails


async def check_input_rail(text: str, rails=None) -> dict:
    """Task 9b: Kiểm tra input qua NeMo input rails (topic guard + jailbreak guard).

    Returns:
        {
          "allowed":        bool,
          "blocked_reason": str | None,
          "response":       str,          # NeMo's raw response
        }
    """
    if rails is None:
        rails = setup_nemo_rails()
    result = await rails.generate_async(
        messages=[{"role": "user", "content": text}],
        options={"rails": ["input"], "log": {"activated_rails": True}},
    )
    response_rows = getattr(result, "response", None)
    if not isinstance(response_rows, list) or not response_rows:
        raise ValueError("NeMo input rail returned no response.")
    first = response_rows[0]
    response = first.get("content", "") if isinstance(first, dict) else getattr(first, "content", "")
    if not isinstance(response, str):
        raise ValueError("NeMo input rail response content must be text.")
    activated = getattr(getattr(result, "log", None), "activated_rails", None)
    if activated is None:
        raise ValueError("NeMo input rail did not return activated_rails logging.")
    blocked = any(
        rail.get("stop", False) if isinstance(rail, dict) else getattr(rail, "stop", False)
        for rail in activated
    )
    return {
        "allowed": not blocked,
        "blocked_reason": "nemo_input_rail" if blocked else None,
        "response": response,
    }


async def check_output_rail(question: str, answer: str, rails=None) -> dict:
    """Task 11: Kiểm tra LLM output qua NeMo output rails trước khi trả về user.

    NeMo output rails hoạt động trong context của cả cuộc hội thoại (input + output).
    Kiểm tra PII và nội dung nhạy cảm. Self-check này không thay RAGAS faithfulness
    hoặc kiểm tra factual accuracy với retrieved contexts.

    Returns:
        {
          "safe":           bool,
          "flagged_reason": str | None,
          "final_answer":   str,          # answer đã qua guard (có thể bị redact)
        }
    """
    if rails is None:
        rails = setup_nemo_rails()
    result = await rails.generate_async(
        messages=[
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ],
        options={"rails": ["output"], "log": {"activated_rails": True}},
    )
    response_rows = getattr(result, "response", None)
    if not isinstance(response_rows, list) or not response_rows:
        raise ValueError("NeMo output rail returned no response.")
    first = response_rows[0]
    response = first.get("content", "") if isinstance(first, dict) else getattr(first, "content", "")
    if not isinstance(response, str) or not response.strip():
        raise ValueError("NeMo output rail returned empty content.")
    activated = getattr(getattr(result, "log", None), "activated_rails", None)
    if activated is None:
        raise ValueError("NeMo output rail did not return activated_rails logging.")
    nemo_flagged = any(
        rail.get("stop", False) if isinstance(rail, dict) else getattr(rail, "stop", False)
        for rail in activated
    )
    policy_flagged = _contains_structured_output_secret(answer)
    flagged = nemo_flagged or policy_flagged
    return {
        "safe": not flagged,
        "flagged_reason": (
            "nemo_output_rail" if nemo_flagged
            else "structured_secret_policy" if policy_flagged
            else None
        ),
        "final_answer": (
            response if nemo_flagged
            else OUTPUT_REFUSAL if policy_flagged
            else answer
        ),
    }


# ─── Task 10: Adversarial Test Suite ─────────────────────────────────────────

def run_adversarial_suite(adversarial_set: list[dict], rails=None,
                           analyzer=None, anonymizer=None) -> list[dict]:
    """Task 10: Chạy 20 adversarial inputs qua full guard stack, so sánh với expected.

    Guard stack order:
        1. pii_scan()         → block nếu has_pii (cho category pii_injection)
        2. check_input_rail() → block nếu jailbreak / off-topic / prompt injection

    Returns:
        list of {
          "id": int, "category": str, "input": str,
          "expected": "blocked"|"allowed",
          "actual":   "blocked"|"allowed",
          "blocked_by": str | None,       # "presidio" | "nemo_input" | None
          "passed": bool,
        }
    """
    if analyzer is None or anonymizer is None:
        analyzer, anonymizer = setup_presidio()
    if rails is None:
        rails = setup_nemo_rails()
    required = {"id", "category", "input", "expected"}

    async def _run_all():
        rows = []
        for item in adversarial_set:
            missing = required - item.keys()
            if missing:
                raise ValueError(f"Guard input is missing: {', '.join(sorted(missing))}")
            if item["expected"] not in {"blocked", "allowed"}:
                raise ValueError("Guard expected value must be blocked or allowed.")
            blocked_by = None
            if pii_scan(item["input"], analyzer, anonymizer)["has_pii"]:
                blocked_by = "presidio"
            if blocked_by is None:
                rail_result = await check_input_rail(item["input"], rails)
                if not rail_result["allowed"]:
                    blocked_by = "nemo_input"
            actual = "blocked" if blocked_by else "allowed"
            rows.append(
                {
                    "id": item["id"],
                    "category": item["category"],
                    "input": item["input"],
                    "expected": item["expected"],
                    "actual": actual,
                    "blocked_by": blocked_by,
                    "passed": actual == item["expected"],
                }
            )
        return rows

    rows = asyncio.run(_run_all())
    print(f"Input guard suite: {sum(row['passed'] for row in rows)}/{len(rows)} passed")
    return rows


# ─── Task 12: P95 Latency Measurement ────────────────────────────────────────

def measure_p95_latency(test_inputs: list[str], n_runs: int = 20,
                         rails=None, analyzer=None, anonymizer=None) -> dict:
    """Task 12: measure INPUT layers sequentially, not end-to-end guard/RAG latency.

    Reuse engines. Inside ONE event loop, execute two real warm-up calls per layer,
    excluded from samples. Then collect exactly n_runs timed samples (cycle clean
    inputs), always measuring BOTH PII and NeMo input even if PII blocks.
    Use perf_counter; keep raw milliseconds. summarize_latency() supplies linear
    percentiles at (n - 1) * q. Submission requires n_runs >= 20.
    Short-circuit request timing, RAG and output timing are outside this scope.
    """
    from src.experiment_support import summarize_latency

    if not test_inputs or n_runs < 1:
        raise ValueError("Need at least one input and n_runs >= 1.")
    if any(not isinstance(text, str) or not text.strip() for text in test_inputs):
        raise ValueError("Latency inputs must be non-empty strings.")
    if analyzer is None or anonymizer is None:
        analyzer, anonymizer = setup_presidio()
    if rails is None:
        rails = setup_nemo_rails()

    async def _measure():
        for index in range(2):
            text = test_inputs[index % len(test_inputs)]
            pii_scan(text, analyzer, anonymizer)
            await check_input_rail(text, rails)
        samples = []
        for index in range(n_runs):
            text = test_inputs[index % len(test_inputs)]
            started = time.perf_counter()
            pii_scan(text, analyzer, anonymizer)
            presidio_ms = (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            await check_input_rail(text, rails)
            nemo_ms = (time.perf_counter() - started) * 1000
            samples.append(
                {
                    "presidio_ms": presidio_ms,
                    "nemo_input_ms": nemo_ms,
                    "input_guard_ms": presidio_ms + nemo_ms,
                }
            )
        return samples

    return summarize_latency(asyncio.run(_measure()), warmup_runs=2)


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from scripts.run_experiments import main
    raise SystemExit(main(["--phase", "c", *sys.argv[1:]]))
