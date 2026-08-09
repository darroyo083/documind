"""E0 evidence archival: build the tracked sanitized validation summary.

Post-run step for the PoC 3F-E0 verifier v2 validation. Takes the two
direct-cases run reports (DEV 14 + FRESH 8) and emits the sanitized, tracked
summary (JSON + Markdown) under ``backend/evaluation/evidence/``.

Raw run reports stay in the gitignored results directory; the summary pins
dataset digests, git SHA, call counts, and per-case outcomes. Sanitization is
mandatory: no API keys, no Authorization headers, no raw provider envelopes,
no full question/evidence text.

Usage (fully offline):

    python scripts/archive_verifier_validation.py \
        --dev-report evaluation/results/poc_3f_e0/dev_report.json \
        --fresh-report evaluation/results/poc_3f_e0/fresh_report.json \
        --dev-dataset experiments/verifier_contract/dev_cases.json \
        --fresh-dataset experiments/verifier_contract/confirmation_cases.json \
        --raw-dir evaluation/results/poc_3f_e0/<run_id>/raw \
        --run-id poc-3f-e0-20260809-180000
"""

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.evaluation import verifier_archive  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the sanitized E0 verifier validation evidence summary."
    )
    parser.add_argument("--dev-report", type=Path, required=True)
    parser.add_argument("--fresh-report", type=Path, required=True)
    parser.add_argument("--dev-dataset", type=Path, required=True)
    parser.add_argument("--fresh-dataset", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=verifier_archive.DEFAULT_E0_SUMMARY_PATH,
        help="Tracked summary JSON path.",
    )
    parser.add_argument(
        "--md-output",
        type=Path,
        default=None,
        help="Optional Markdown path (defaults to the JSON path with .md).",
    )
    return parser.parse_args(argv)


def load_report(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = verifier_archive.build_e0_validation_summary(
        dev_report=load_report(args.dev_report),
        fresh_report=load_report(args.fresh_report),
        dev_dataset_path=args.dev_dataset,
        fresh_dataset_path=args.fresh_dataset,
        run_id=args.run_id,
        raw_dir=args.raw_dir,
    )
    md_path = args.md_output or args.output.with_suffix(".md")
    verifier_archive.write_e0_validation_summary(summary, args.output, md_path)
    print(f"E0 validation summary: {args.output}")
    print(f"E0 validation summary (markdown): {md_path}")
    calls = summary["inputs"]["verifier_calls"]
    print(
        f"Verifier calls: dev={calls['dev']}, fresh={calls['fresh']}, combined={calls['combined']}"
    )
    print("Sanitized: no API keys, no raw provider envelopes, no full text.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
