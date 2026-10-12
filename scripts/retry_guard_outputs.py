"""Retry only the four live output-rail cases after a stochastic miss."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.experiment_runners import retry_phase_c_outputs
from src.llm import validate_config
from src.llm_budget import BUDGET


def main(argv=None):
    parser = argparse.ArgumentParser(description="Retry Phase C output rails (paid API)")
    parser.add_argument("--live", action="store_true", help="Acknowledge paid API use")
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("Output retries require --live.")
    validate_config()
    report = retry_phase_c_outputs()
    passed = sum(row["passed"] for row in report["output_results"])
    print(f"Phase C output rails saved: {passed}/{len(report['output_results'])} passed")
    print(f"LLM budget: {BUDGET.snapshot()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, FileNotFoundError, KeyError, TypeError, RuntimeError) as error:
        raise SystemExit(f"Output retry failed: {error}")
