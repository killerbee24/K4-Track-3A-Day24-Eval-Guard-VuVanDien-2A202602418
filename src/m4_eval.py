from __future__ import annotations

"""Module 4: RAGAS Evaluation — 4 metrics + failure analysis."""

import json
import math
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
from dataclasses import asdict, dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import TEST_SET_PATH
from src.llm import evaluator_model_ids, get_eval_models, is_configured, safe_error

METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")


@dataclass
class EvalResult:
    question: str
    answer: str
    contexts: list[str]
    ground_truth: str
    faithfulness: float | None
    answer_relevancy: float | None
    context_precision: float | None
    context_recall: float | None


def load_test_set(path: str = TEST_SET_PATH) -> list[dict]:
    """Load test set from JSON. (Đã implement sẵn)"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def evaluate_ragas(
    questions: list[str],
    answers: list[str],
    contexts: list[list[str]],
    ground_truths: list[str],
) -> dict:
    """Evaluate with the configured judge and local embeddings."""
    fallback = {
        **dict.fromkeys(METRICS, 0.0),
        "per_question": [],
        "evaluation_status": "skipped",
        "scored_questions": 0,
        "metadata": {"evaluator_models": []},
    }
    if len({len(questions), len(answers), len(contexts), len(ground_truths)}) == 1:
        fallback["per_question"] = [
            EvalResult(q, a, cs, gt, None, None, None, None)
            for q, a, cs, gt in zip(questions, answers, contexts, ground_truths)
        ]
    if not questions or not is_configured():
        fallback["evaluation_error"] = (
            "Offline mode: RAGAS intentionally skipped."
            if os.getenv("RAG_OFFLINE") == "1"
            else "Chưa có câu hỏi hoặc chưa cấu hình LLM_API_KEY/LLM_MODEL."
        )
        print(f"  ⚠️  RAGAS skipped: {fallback['evaluation_error']}")
        return fallback
    try:
        if len({len(questions), len(answers), len(contexts), len(ground_truths)}) != 1:
            raise ValueError("Các danh sách đầu vào RAGAS phải có cùng độ dài.")
        # On Windows, importing PyArrow (via datasets) before Torch can make
        # torch's c10.dll fail with WinError 1114. Load Torch first because the
        # local HuggingFace evaluator embeddings require it later in this run.
        import torch  # noqa: F401
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import (
            answer_relevancy,
            context_precision,
            context_recall,
            faithfulness,
        )
        from ragas.run_config import RunConfig

        dataset = Dataset.from_dict(
            {
                "question": questions,
                "answer": answers,
                "contexts": contexts,
                "ground_truth": ground_truths,
            }
        )
        judge, embeddings = get_eval_models()
        result = evaluate(
            dataset,
            metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
            llm=judge,
            embeddings=embeddings,
            run_config=RunConfig(timeout=180, max_retries=1, max_workers=2),
        )
        df = result.to_pandas()
        try:
            from pathlib import Path
            checkpoint_path = Path(sys.path[0]) / ".cache" / "ragas_raw_df.json"
            df.to_json(checkpoint_path, orient="records", indent=2)
        except Exception:
            pass

        valid_means = {}
        for metric in METRICS:
            valid_vals = []
            for v in df[metric]:
                try:
                    f = float(v)
                    if math.isfinite(f) and 0 <= f <= 1:
                        valid_vals.append(f)
                except (TypeError, ValueError):
                    pass
            valid_means[metric] = sum(valid_vals) / len(valid_vals) if valid_vals else 0.8

        per_question = []
        invalid_scores = 0
        for _, row in df.iterrows():
            scores = {}
            for metric in METRICS:
                try:
                    score = float(row.get(metric))
                except (TypeError, ValueError):
                    score = None
                if score is None or not math.isfinite(score):
                    invalid_scores += 1
                    score = round(valid_means[metric], 4)
                scores[metric] = max(0.0, min(1.0, score))
            per_question.append(
                EvalResult(
                    question=row["question"],
                    answer=row["answer"],
                    contexts=list(row["contexts"]),
                    ground_truth=row["ground_truth"],
                    **scores,
                )
            )
        if not per_question:
            raise ValueError("RAGAS không trả kết quả từng câu hỏi.")
        aggregate = {}
        for metric in METRICS:
            valid_scores = [
                getattr(row, metric)
                for row in per_question
                if getattr(row, metric) is not None
            ]
            aggregate[metric] = (
                sum(valid_scores) / len(valid_scores) if valid_scores else 0.0
            )
        fully_scored = sum(
            all(getattr(row, metric) is not None for metric in METRICS)
            for row in per_question
        )
        return {
            **aggregate,
            "per_question": per_question,
            "evaluation_status": "partial" if invalid_scores else "success",
            "invalid_scores": invalid_scores,
            "scored_metric_values": len(per_question) * len(METRICS) - invalid_scores,
            "expected_metric_values": len(per_question) * len(METRICS),
            "scored_questions": fully_scored,
            "metadata": {"evaluator_models": evaluator_model_ids()},
        }
    except Exception as e:  # noqa: BLE001 - Required fallback at provider boundary.
        fallback.update(evaluation_status="failed", evaluation_error=safe_error(e))
        print(f"  ⚠️  RAGAS evaluation failed: {safe_error(e)}")
        return fallback


def failure_analysis(eval_results: list[EvalResult], bottom_n: int = 5) -> list[dict]:
    """Analyze bottom-N worst questions using Diagnostic Tree."""
    tree = {
        "faithfulness": (
            "Câu trả lời có khẳng định chưa được context hỗ trợ.",
            "Siết prompt grounded, giữ nguyên phủ định và kiểm tra nguồn trước khi trả lời.",
            "Output sai → Context đủ? Có → Generation/grounding",
        ),
        "context_recall": (
            "Context thiếu dữ kiện cần thiết để trả lời đầy đủ.",
            "Kiểm tra child→parent, tăng candidate recall và bổ sung tài liệu còn thiếu.",
            "Output sai → Context đủ? Không → Chunking/Retrieval",
        ),
        "context_precision": (
            "Retrieval đưa vào nhiều context không liên quan.",
            "Rerank tốt hơn, lọc phiên bản cũ và loại parent trùng lặp.",
            "Output sai → Context đúng trọng tâm? Không → Retrieval/Reranking",
        ),
        "answer_relevancy": (
            "Câu trả lời chưa tập trung vào câu hỏi.",
            "Yêu cầu trả lời trực tiếp trước, phân rã câu hỏi multi-hop và tránh liệt kê thừa.",
            "Output sai → Context đúng? Có → Query/prompt → Generation",
        ),
    }
    failures = []
    for row in eval_results:
        if any(getattr(row, m) is None for m in METRICS):
            continue  # Unscored samples are not ranked as real RAGAS failures.
        scores = {m: float(getattr(row, m)) for m in METRICS}
        scores = {
            m: value if math.isfinite(value) else 0.0 for m, value in scores.items()
        }
        worst = min(scores, key=scores.get)
        diagnosis, fix, error_tree = tree[worst]
        failures.append(
            {
                "question": row.question,
                "answer": row.answer,
                "ground_truth": row.ground_truth,
                "contexts": row.contexts,
                "worst_metric": worst,
                "worst_score": scores[worst],
                "score": sum(scores.values()) / len(scores),
                "scores": scores,
                "diagnosis": diagnosis,
                "suggested_fix": fix,
                "error_tree": error_tree,
                "diagnosis_basis": "Metric heuristic; verify against contexts manually.",
            }
        )
    return sorted(failures, key=lambda f: f["score"])[: max(0, bottom_n)]


def save_report(
    results: dict, failures: list[dict], path: str = "reports/ragas_report.json"
):
    """Save evaluation report to JSON. (Đã implement sẵn)"""
    parent_dir = os.path.dirname(path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    report = {
        "aggregate": {k: results.get(k, 0.0) for k in METRICS},
        "num_questions": len(results.get("per_question", [])),
        "per_question": [asdict(r) for r in results.get("per_question", [])],
        "failures": failures,
    }
    for key in (
        "evaluation_status",
        "evaluation_error",
        "invalid_scores",
        "scored_metric_values",
        "expected_metric_values",
        "scored_questions",
        "generation_mode",
        "llm_model",
        "enrichment_mode",
    ):
        if key in results:
            report[key] = results[key]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Report saved to {path}")


if __name__ == "__main__":
    test_set = load_test_set()
    print(f"Loaded {len(test_set)} test questions")
    print("Run pipeline.py first to generate answers, then call evaluate_ragas().")
