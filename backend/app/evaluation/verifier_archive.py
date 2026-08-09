"""Sanitized E0 validation evidence summary (PoC 3F-E0, Worker C design).

Takes the two direct-cases run reports (DEV 14 + FRESH 8) and emits ONE
tracked, sanitized summary under ``backend/evaluation/evidence/``. The raw,
complete run reports stay in the gitignored results directory
(``backend/evaluation/results/poc_3f_e0/``); this summary is what git history
preserves.

Sanitization is mandatory and deliberate:
- NO API keys, NO Authorization headers, NO raw provider envelopes (no
  ``choices``/``message``/``usage`` passthrough), NO full question text and NO
  full evidence text. Questions are reduced to a SHA-256; evidence is reduced
  to its source ids.
- Per-case ``raw_report_sha256`` is the canonical-JSON digest of the sanitized
  per-case envelope file in the gitignored raw directory (when one is
  supplied); it is null when no raw directory is available yet.

The summary reuses existing report fields wherever possible
(``verifier_reporting.build_verifier_json_report``) and never restructures the
frozen reporting. Nothing here is used by production code.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evaluation import verifier_dataset, verifier_dev_cases

E0_SUMMARY_SCHEMA_VERSION = "e0-summary-1"
E0_MILESTONE = "poc-3f-e0"
E0_EXPERIMENT = "verifier_v2_validation"
E0_DIGEST_METHOD = "canonical_json_sha256"

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_E0_SUMMARY_PATH = BACKEND_DIR / "evaluation" / "evidence" / "poc_3f_e0_validation.json"
# Raw run reports for E0 land here (gitignored via backend/evaluation/results/).
E0_RAW_REPORTS_DIR = BACKEND_DIR / "evaluation" / "results" / "poc_3f_e0"

_GROUP_KEYS = ("dev", "fresh", "combined")


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _sha256_utf8(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _raw_envelope_sha256(raw_dir: Path | None, case_id: str) -> str | None:
    """Canonical JSON content digest of the per-case raw envelope, if present."""
    if raw_dir is None:
        return None
    path = raw_dir / f"{case_id}.json"
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return verifier_dataset.canonical_json_digest(payload)


def _load_report(report: dict[str, Any], group: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(report, dict) or "benchmark" not in report or "outcomes" not in report:
        raise ValueError(f"{group} report must be a verifier JSON report dict")
    invalid_by_id = {entry["query_id"]: entry for entry in report.get("invalid_outputs", [])}
    return report, invalid_by_id


def _case_record(
    outcome: dict[str, Any],
    invalid_entry: dict[str, Any] | None,
    dataset_case: dict[str, Any],
    group: str,
    raw_dir: Path | None,
) -> dict[str, Any]:
    """One sanitized per-case record (Worker C schema section 5)."""
    case_id = outcome["query_id"]
    expected_supported = outcome["answerable"]
    expected_ids = dataset_case["expected_source_ids"]
    evidence_ids = list(outcome["evidence_ids"])
    supported = outcome["supported"]
    invalid = invalid_entry is not None
    error_kind = invalid_entry.get("error_kind") if invalid_entry else None
    error = invalid_entry.get("error") if invalid_entry else None

    if invalid:
        source_validation_passed = False if error_kind == "evidence_source_validation" else None
        correct = None
        classification = None
    else:
        source_validation_passed = True
        correct = bool(supported) is bool(expected_supported)
        if bool(supported) is bool(expected_supported):
            classification = "true_positive" if expected_supported else "true_negative"
        else:
            classification = "false_positive" if supported else "false_negative"

    gold_present = expected_supported and set(expected_ids) <= set(evidence_ids)
    if invalid or not expected_supported:
        gold_source_match = None
    else:
        gold_source_match = set(outcome["evidence_source_ids"]) == set(expected_ids)

    return {
        "case_id": case_id,
        "group": group,
        "category": outcome["category"],
        "question_sha256": _sha256_utf8(outcome["question"]),
        "evidence": {"source_ids": evidence_ids, "count": len(evidence_ids)},
        "expected": {
            "supported": expected_supported,
            "source_ids": expected_ids,
            "gold_evidence_present": gold_present,
        },
        "verifier_call": {
            "made": outcome["evidence_count"] > 0,
            "raw_report_sha256": _raw_envelope_sha256(raw_dir, case_id),
            "http_status": None,
            "latency_ms": None,
            "usage_tokens": None,
        },
        "prediction": {
            "supported": supported,
            "evidence_source_ids": list(outcome["evidence_source_ids"]),
            "reason": outcome["reason"],
        },
        "outcome": {
            "valid": not invalid,
            "error_kind": error_kind,
            "error": error,
            "source_validation_passed": source_validation_passed,
            "correct": correct,
            "classification": classification,
            "gold_source_match": gold_source_match,
        },
    }


def group_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Worker C section 6 metric set for one group (dev / fresh / combined).

    Invalid outputs are never folded into accuracy: accuracy is
    ``accuracy_valid_only`` over the valid subset and is always published next
    to ``valid_output_rate`` / ``invalid_output_count``. Ratios with zero
    denominator are null, never 0.0.
    """
    total = len(records)
    valid = [r for r in records if r["outcome"]["valid"]]
    answerable = [r for r in records if r["expected"]["supported"]]
    supported_pred = [r for r in valid if r["prediction"]["supported"]]
    tp = sum(1 for r in supported_pred if r["expected"]["supported"])
    fp = len(supported_pred) - tp
    rejected = [r for r in valid if not r["prediction"]["supported"]]
    tn = sum(1 for r in rejected if not r["expected"]["supported"])
    fn = len(rejected) - tn
    provider_failures = sum(1 for r in records if r["outcome"]["error_kind"] == "provider_error")
    source_failures = sum(
        1 for r in records if r["outcome"]["error_kind"] == "evidence_source_validation"
    )
    malformed = sum(1 for r in records if r["outcome"]["error_kind"] == "malformed_output")
    gold_present = sum(1 for r in answerable if r["expected"]["gold_evidence_present"])
    valid_answerable = [r for r in valid if r["expected"]["supported"]]
    gold_match = sum(1 for r in valid_answerable if r["outcome"]["gold_source_match"] is True)

    answerable_retention = _rate(tp, tp + fn)
    unsupported_detection = _rate(tn, tn + fp)
    supported_precision = _rate(tp, tp + fp)
    unsupported_precision = _rate(tn, tn + fn)
    balanced = (
        round((answerable_retention + unsupported_detection) / 2, 4)
        if answerable_retention is not None and unsupported_detection is not None
        else None
    )

    return {
        "total_cases": total,
        "verifier_calls": sum(1 for r in records if r["verifier_call"]["made"]),
        "valid_output_count": len(valid),
        "valid_output_rate": _rate(len(valid), total),
        "invalid_output_count": total - len(valid),
        "invalid_output_rate": _rate(total - len(valid), total),
        "provider_failure_count": provider_failures,
        "provider_failure_rate": _rate(provider_failures, total),
        "source_validation_failure_count": source_failures,
        "source_validation_failure_rate": _rate(source_failures, total),
        "malformed_output_count": malformed,
        "false_support_count": fp,
        "false_rejection_count": fn,
        "answerable_retention": answerable_retention,
        "unsupported_detection": unsupported_detection,
        "supported_precision": supported_precision,
        "unsupported_precision": unsupported_precision,
        "false_support_rate": _rate(fp, tn + fp),
        "false_rejection_rate": _rate(fn, tp + fn),
        "balanced_accuracy_valid_only": balanced,
        "accuracy_valid_only": _rate(tp + tn, len(valid)),
        "gold_evidence_present_rate": _rate(gold_present, len(answerable)),
        "evidence_selection_quality": _rate(gold_match, len(valid_answerable)),
    }


def build_e0_validation_summary(
    *,
    dev_report: dict[str, Any],
    fresh_report: dict[str, Any],
    dev_dataset_path: str | Path,
    fresh_dataset_path: str | Path,
    run_id: str | None = None,
    raw_dir: str | Path | None = None,
    timestamp_utc: str | None = None,
) -> dict[str, Any]:
    """Build the sanitized E0 summary from two direct-cases run reports.

    ``dev_report``/``fresh_report`` are outputs of
    ``verifier_reporting.build_verifier_json_report``. Dataset paths are the
    tracked case files actually used for each run (their canonical digests pin
    the inputs and their ``expected_source_ids`` enable gold-evidence checks).
    """
    dev_benchmark = dev_report["benchmark"]
    dev_dataset = verifier_dev_cases.load_dev_cases(dev_dataset_path)
    fresh_dataset = verifier_dev_cases.load_dev_cases(fresh_dataset_path)
    dev_cases_by_id = {case["id"]: case for case in dev_dataset["cases"]}
    fresh_cases_by_id = {case["id"]: case for case in fresh_dataset["cases"]}

    now = datetime.now(UTC)
    timestamp = timestamp_utc or now.isoformat()
    run = run_id or f"poc-3f-e0-{now:%Y%m%d-%H%M%S}"

    records: list[dict[str, Any]] = []
    for group, report, cases_by_id in (
        ("dev", dev_report, dev_cases_by_id),
        ("fresh", fresh_report, fresh_cases_by_id),
    ):
        benchmark, invalid_by_id = _load_report(report, group)
        for outcome in sorted(benchmark["outcomes"], key=lambda o: o["query_id"]):
            case_id = outcome["query_id"]
            if case_id not in cases_by_id:
                raise ValueError(
                    f"{group} report case {case_id!r} is not present in the {group} dataset"
                )
            records.append(
                _case_record(
                    outcome,
                    invalid_by_id.get(case_id),
                    cases_by_id[case_id],
                    group,
                    Path(raw_dir) if raw_dir is not None else None,
                )
            )

    by_group: dict[str, list[dict[str, Any]]] = {"dev": [], "fresh": [], "combined": []}
    for record in records:
        by_group[record["group"]].append(record)
        by_group["combined"].append(record)

    metrics = {key: group_metrics(by_group[key]) for key in _GROUP_KEYS}

    category_breakdown: dict[str, dict[str, Any]] = {}
    for category in sorted({r["category"] for r in records}):
        per_group: dict[str, Any] = {}
        for key in _GROUP_KEYS:
            subset = [r for r in by_group[key] if r["category"] == category]
            per_group[key] = group_metrics(subset) if subset else None
        category_breakdown[category] = per_group

    commit = dev_benchmark.get("git_commit") or fresh_report["benchmark"].get("git_commit")
    raw_dir_path = Path(raw_dir) if raw_dir is not None else None
    raw_file_count = sum(1 for r in records if r["verifier_call"]["raw_report_sha256"] is not None)

    return {
        "schema_version": E0_SUMMARY_SCHEMA_VERSION,
        "milestone": E0_MILESTONE,
        "experiment": E0_EXPERIMENT,
        "run_id": run,
        "timestamp_utc": timestamp,
        "git": {"commit": commit},
        "inputs": {
            "datasets": [
                {
                    "group": "dev",
                    "path": str(dev_dataset_path),
                    "dataset_version": dev_dataset["dataset_version"],
                    "canonical_sha256": verifier_dataset.canonical_dataset_digest(dev_dataset_path),
                    "case_count": len(dev_dataset["cases"]),
                    "reported_cases": len(by_group["dev"]),
                },
                {
                    "group": "fresh",
                    "path": str(fresh_dataset_path),
                    "dataset_version": fresh_dataset["dataset_version"],
                    "canonical_sha256": verifier_dataset.canonical_dataset_digest(
                        fresh_dataset_path
                    ),
                    "case_count": len(fresh_dataset["cases"]),
                    "reported_cases": len(by_group["fresh"]),
                },
            ],
            "verifier_provider": dev_benchmark.get("verifier_provider"),
            "verifier_model": dev_benchmark.get("verifier_model"),
            "verifier_prompt_version": dev_benchmark.get("verifier_prompt_version"),
            "decision_schema_version": dev_benchmark.get("decision_schema_version"),
            "run_mode": dev_benchmark.get("run_mode"),
            "external_api": dev_benchmark.get("external_api"),
            "verifier_calls": {
                "dev": metrics["dev"]["verifier_calls"],
                "fresh": metrics["fresh"]["verifier_calls"],
                "combined": metrics["combined"]["verifier_calls"],
            },
        },
        "raw_artifacts": {
            "relative_dir": str(raw_dir_path) if raw_dir_path is not None else None,
            "digest_method": E0_DIGEST_METHOD,
            "file_count": raw_file_count,
        },
        "cases": records,
        "metrics": metrics,
        "category_breakdown": category_breakdown,
        "methodology": {
            "invalid_handling": (
                "invalid outputs are excluded from classification rates but "
                "reported as counts/rates over N; accuracy is valid-only and "
                "explicitly named accuracy_valid_only"
            ),
            "zero_denominator": "ratios with zero denominator are null, never 0.0",
            "grouping": "case group (dev/fresh) is assigned from the source dataset file",
            "raw_hashing": (
                "canonical_json_sha256 of the sanitized per-case provider "
                "envelope in the gitignored raw directory; null when no raw "
                "directory is available"
            ),
            "sanitization": (
                "summary contains no API keys, no Authorization headers, no raw "
                "provider envelopes, no full question or evidence text"
            ),
        },
    }


def render_e0_validation_markdown(summary: dict[str, Any]) -> str:
    """Human-readable Markdown rendering of the sanitized E0 summary."""
    lines: list[str] = []
    lines.append("# DocuMind E0 — Verifier v2 Validation Evidence Summary")
    lines.append("")
    lines.append(f"- Milestone: {summary['milestone']}")
    lines.append(f"- Experiment: {summary['experiment']}")
    lines.append(f"- Run id: {summary['run_id']}")
    lines.append(f"- Timestamp (UTC): {summary['timestamp_utc']}")
    lines.append(f"- Git commit: {summary['git'].get('commit')}")
    lines.append(f"- Summary schema version: {summary['schema_version']}")
    inputs = summary["inputs"]
    lines.append(f"- Provider: {inputs['verifier_provider']}")
    lines.append(f"- Model: {inputs['verifier_model']}")
    lines.append(f"- Prompt version: {inputs['verifier_prompt_version']}")
    lines.append(f"- Decision schema version: {inputs['decision_schema_version']}")
    calls = inputs["verifier_calls"]
    lines.append(
        f"- Verifier calls: dev={calls['dev']}, fresh={calls['fresh']}, "
        f"combined={calls['combined']}"
    )
    for dataset in inputs["datasets"]:
        lines.append(
            f"- {dataset['group']} dataset: {dataset['path']} "
            f"(version {dataset['dataset_version']}, canonical SHA-256 "
            f"{dataset['canonical_sha256']}, {dataset['case_count']} planned / "
            f"{dataset['reported_cases']} reported)"
        )
    lines.append("")

    metric_order = (
        "total_cases",
        "verifier_calls",
        "valid_output_count",
        "valid_output_rate",
        "invalid_output_count",
        "invalid_output_rate",
        "provider_failure_count",
        "source_validation_failure_count",
        "malformed_output_count",
        "false_support_count",
        "false_rejection_count",
        "answerable_retention",
        "unsupported_detection",
        "supported_precision",
        "unsupported_precision",
        "balanced_accuracy_valid_only",
        "accuracy_valid_only",
        "gold_evidence_present_rate",
        "evidence_selection_quality",
    )

    def render_metric_table(metrics: dict[str, Any]) -> None:
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        for key in metric_order:
            value = metrics.get(key)
            lines.append(f"| {key} | {'null' if value is None else value} |")
        lines.append("")

    for group in _GROUP_KEYS:
        lines.append(f"## Metrics — {group}")
        lines.append("")
        render_metric_table(summary["metrics"][group])

    lines.append("## Category breakdown")
    lines.append("")
    for category, per_group in summary["category_breakdown"].items():
        lines.append(f"### {category}")
        lines.append("")
        lines.append("| Group | Cases | Valid | Accuracy (valid-only) | Retention | Detection |")
        lines.append("|---|---|---|---|---|---|")
        for group in _GROUP_KEYS:
            metrics = per_group.get(group)
            if metrics is None:
                lines.append(f"| {group} | — | — | — | — | — |")
                continue
            lines.append(
                f"| {group} | {metrics['total_cases']} | "
                f"{metrics['valid_output_count']} | "
                f"{metrics['accuracy_valid_only']} | "
                f"{metrics['answerable_retention']} | "
                f"{metrics['unsupported_detection']} |"
            )
        lines.append("")

    lines.append("## Cases")
    lines.append("")
    lines.append(
        "| Case | Group | Category | Call | Valid | Error kind | Expected | Predicted | "
        "Source validation | Gold match |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for record in sorted(summary["cases"], key=lambda r: (r["group"], r["case_id"])):
        outcome = record["outcome"]
        prediction = record["prediction"]
        expected = record["expected"]
        lines.append(
            f"| {record['case_id']} | {record['group']} | {record['category']} | "
            f"{record['verifier_call']['made']} | {outcome['valid']} | "
            f"{outcome['error_kind']} | {expected['supported']} | "
            f"{prediction['supported']} | {outcome['source_validation_passed']} | "
            f"{outcome['gold_source_match']} |"
        )
    lines.append("")

    lines.append("## Methodology")
    lines.append("")
    for key, value in summary["methodology"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def write_e0_validation_summary(summary: dict[str, Any], json_path, md_path=None) -> None:
    """Deterministic JSON (and optional Markdown) output for the summary."""
    path = Path(json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True, ensure_ascii=False)
    if md_path is not None:
        md = Path(md_path)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(render_e0_validation_markdown(summary), encoding="utf-8")
