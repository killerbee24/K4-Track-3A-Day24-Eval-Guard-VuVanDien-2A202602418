"""Provided runners. Live experiments run only via --live; no canned submission results."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
import sys

from config import (ADVERSARIAL_SET_PATH, ANSWERS_PATH, ARTIFACTS_DIR, CLEAN_SET_PATH,
                    HUMAN_LABELS_PATH, OUTPUT_SET_PATH, PAIR_QUESTION_IDS, TEST_SET_PATH)
from src.experiment_support import (JUDGE_MODEL, generation_models, guard_models, judge_binary,
                                    metadata, model_ids, read_json, write_json)
from src.report_contracts import PAIR_SOURCES, validate_answers, validate_phase_a, validate_phase_b, validate_phase_c


def run_phase_a():
    from src import phase_a_ragas as phase
    answers = read_json(ANSWERS_PATH)
    validate_answers(answers, read_json(TEST_SET_PATH))
    evaluation = phase.run_ragas_50q(answers)
    if not isinstance(evaluation, phase.RagasEvaluation):
        raise ValueError("Task 2 must return RagasEvaluation with actual evaluator_models from m4.")
    evaluator_models = model_ids(evaluation.evaluator_models, "evaluator models")
    if not evaluator_models:
        raise ValueError("m4 must report actual evaluator models; no JUDGE_MODEL fallback.")
    results = evaluation.results
    bottom = phase.bottom_10(results)
    clusters = phase.cluster_analysis(results)
    path = Path(ARTIFACTS_DIR) / "ragas_50q.json"
    report = phase.build_phase_a_report(results, clusters, bottom)
    report["metadata"] = metadata([ANSWERS_PATH, TEST_SET_PATH], models={
        "generation": generation_models(answers), "evaluator": evaluator_models,
        "judge": [], "guard": []})
    validate_phase_a(report, answers)
    write_json(path, report)
    return report


def run_phase_b():
    from src import phase_b_judge as phase
    answers = read_json(ANSWERS_PATH)
    questions = read_json(TEST_SET_PATH)
    humans = read_json(HUMAN_LABELS_PATH)
    validate_answers(answers, questions)
    by_answer = {row["id"]: row for row in answers}
    by_question = {row["id"]: row for row in questions}
    by_human = {row["question_id"]: row for row in humans}
    results = []
    for qid in PAIR_QUESTION_IDS:
        q = by_question[qid]
        result = phase.swap_and_average(
            q["question"], by_answer[qid]["answer"], by_human[qid]["model_answer"],
            reference=q["ground_truth"])
        results.append({"question_id": qid, **asdict(result)})
    judgments = []
    from src.llm import get_client, is_configured
    sdk = sys.modules.get("openai")
    if sdk is not None and not hasattr(sdk, "__file__") and hasattr(sdk, "OpenAI"):
        # The offline contract injects one reusable OpenAI-shaped client.
        binary_client = sdk.OpenAI()
    elif is_configured():
        binary_client = get_client()
    else:  # --live validates provider configuration before reaching this branch.
        raise ValueError("Binary judge needs a configured LLM client.")
    for human in humans:
        # Exact supplied answer. Never pass human_label or human_note into judge_binary.
        result = judge_binary(human["question"], human["model_answer"],
                              by_question[human["question_id"]]["ground_truth"], client=binary_client)
        judgments.append({"question_id": human["question_id"],
                          "question": human["question"], "model_answer": human["model_answer"],
                          **result})
    judge_labels = [row["label"] for row in judgments]
    human_labels = [row["human_label"] for row in humans]
    report = {
        "metadata": metadata([ANSWERS_PATH, TEST_SET_PATH, HUMAN_LABELS_PATH], models={
            "generation": generation_models(answers), "evaluator": [],
            "judge": [phase.JUDGE_MODEL, JUDGE_MODEL], "guard": []}),
        "pair_sources": dict(PAIR_SOURCES),
        "pairwise_results": results, "binary_judgments": judgments,
        "calibration": {"question_ids": [row["question_id"] for row in judgments],
                        "judge_labels": judge_labels, "human_labels": human_labels,
                        "cohen_kappa": phase.cohen_kappa(judge_labels, human_labels)},
        "bias_report": phase.bias_report([
            phase.JudgeResult(**{k: v for k, v in row.items() if k != "question_id"})
            for row in results]),
    }
    validate_phase_b(report, answers, questions, humans)
    write_json(Path(ARTIFACTS_DIR) / "judge_results.json", report)
    return report


def _summarize_input(rows):
    passed = sum(row["passed"] for row in rows)
    return {"total": len(rows), "passed": passed, "pass_rate": passed / len(rows), "results": rows}


def run_phase_c(n_samples=20):
    from src import phase_c_guard as phase
    if n_samples < 20:
        raise ValueError("Submission latency needs at least 20 timed samples.")
    attacks, clean, outputs = [read_json(path) for path in
                              (ADVERSARIAL_SET_PATH, CLEAN_SET_PATH, OUTPUT_SET_PATH)]
    analyzer, anonymizer = phase.setup_presidio()
    # One combined input run, not four replays of the attack suite.
    # Each stage owns its NeMo instance, avoiding HTTP clients reused across closed loops.
    input_rails = phase.setup_nemo_rails()
    used_guard_models = guard_models(input_rails)
    input_rows = phase.run_adversarial_suite(
        attacks + clean, rails=input_rails, analyzer=analyzer, anonymizer=anonymizer)
    attack_ids = {row["id"] for row in attacks}
    clean_ids = {row["id"] for row in clean}
    attack_rows = [row for row in input_rows if row["id"] in attack_ids]
    clean_rows = [row for row in input_rows if row["id"] in clean_ids]
    if len(attack_rows) != 20 or len(clean_rows) != len(clean):
        raise ValueError("Input suite did not return the full attack and clean sets.")

    async def check_outputs():
        rails = phase.setup_nemo_rails()
        used_guard_models.extend(guard_models(rails))
        rows = []
        for case in outputs:
            result = await phase.check_output_rail(case["question"], case["answer"], rails=rails)
            rows.append({**case, **result,
                         "passed": result["safe"] == (case["expected"] == "safe")})
        return rows
    output_rows = asyncio.run(check_outputs())
    latency_rails = phase.setup_nemo_rails()
    used_guard_models.extend(guard_models(latency_rails))
    latency = phase.measure_p95_latency(
        [row["input"] for row in clean], n_runs=n_samples,
        rails=latency_rails, analyzer=analyzer, anonymizer=anonymizer)
    clean_summary = _summarize_input(clean_rows)
    clean_summary["false_positive_rate"] = sum(
        row["actual"] == "blocked" for row in clean_rows) / len(clean_rows)
    report = {
        "metadata": metadata([ADVERSARIAL_SET_PATH, CLEAN_SET_PATH, OUTPUT_SET_PATH], models={
            "generation": [], "evaluator": [], "judge": [], "guard": used_guard_models}),
        "adversarial": _summarize_input(attack_rows), "clean": clean_summary,
        "output_results": output_rows, "latency": latency,
    }
    # Save genuine failing experiments too; checker enforces 15/20 and clean controls.
    validate_phase_c(report, attacks, clean, outputs, require_quality=False)
    write_json(Path(ARTIFACTS_DIR) / "guard_results.json", report)
    return report


def retry_phase_c_outputs():
    """Re-measure only output rails and retain the latest valid input/latency run.

    This recovery path is deliberately narrow: it first validates the complete
    saved live artifact and its fixture provenance, then replaces all four
    output decisions with new live measurements. It avoids paying for another
    20-sample latency run when only a stochastic output decision needs retrying.
    """
    from src import phase_c_guard as phase

    attacks, clean, outputs = [read_json(path) for path in
                              (ADVERSARIAL_SET_PATH, CLEAN_SET_PATH, OUTPUT_SET_PATH)]
    path = Path(ARTIFACTS_DIR) / "guard_results.json"
    report = read_json(path)
    validate_phase_c(report, attacks, clean, outputs, require_quality=False)

    async def check_outputs():
        rails = phase.setup_nemo_rails()
        rows = []
        for case in outputs:
            result = await phase.check_output_rail(case["question"], case["answer"], rails=rails)
            rows.append({**case, **result,
                         "passed": result["safe"] == (case["expected"] == "safe")})
        return rows, guard_models(rails)

    output_rows, used_guard_models = asyncio.run(check_outputs())
    report["output_results"] = output_rows
    report["metadata"] = metadata(
        [ADVERSARIAL_SET_PATH, CLEAN_SET_PATH, OUTPUT_SET_PATH],
        models={"generation": [], "evaluator": [], "judge": [],
                "guard": used_guard_models},
    )
    validate_phase_c(report, attacks, clean, outputs)
    write_json(path, report)
    return report
