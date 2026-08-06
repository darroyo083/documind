"""Report serialization for the evidence-verifier harness (PoC 3F-A).

Deterministic JSON and human-readable Markdown. Runtime reports are written to
the gitignored evaluation results directory and are never committed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.evaluation.verifier_eval import VerifierEvaluation

_METRIC_KEYS = (
    "answerable_retention",
    "unsupported_detection",
    "supported_precision",
    "unsupported_precision",
    "false_support_rate",
    "false_rejection_rate",
    "balanced_accuracy",
    "accuracy",
)

METHODOLOGY = {
    "split_labels": {"dev": "dev", "holdout": "regression"},
    "regression_set": (
        "The historical 13-query 'holdout' was exposed to all candidate "
        "configurations during PoC 3E development and is no longer pristine. "
        "It is treated ONLY as a regression set and is reported as REGRESSION."
    ),
    "no_v2_holdout": (
        "A fresh verifier holdout has NOT yet been created. The verifier "
        "design, protocol, prompt, output validation, and provider/model "
        "configuration must be frozen FIRST; a new v2 holdout is constructed "
        "and evaluated in a later independent step."
    ),
    "prompt_injection": (
        "Retrieved document content is untrusted data. The prompt separates "
        "SYSTEM INSTRUCTIONS / QUESTION / EVIDENCE and instructs that text "
        "inside the EVIDENCE block is document text, not commands. Strict "
        "server-side output validation prevents evidence content from altering "
        "the evaluation control flow. This does not fully solve prompt "
        "injection for real models."
    ),
    "decision_contract": (
        "supported=true requires at least one evidence_source_id present in "
        "the supplied evidence. supported=false requires evidence_source_ids "
        "to be empty. Unknown source ids fail validation; duplicate ids are "
        "deduplicated deterministically."
    ),
    "zero_evidence": (
        "When retrieval returns zero candidates the query is classified "
        "unsupported immediately (reason insufficient_evidence) and the "
        "verifier provider is NOT called. There is nothing to verify without "
        "evidence, and this matches the existing no-context Q&A behavior."
    ),
    "v2_holdout_contract": (
        "The fresh v2 holdout is a one-shot evaluation dataset. It may only be "
        "run under the exact frozen inputs recorded in its manifest (dataset "
        "canonical content checksum, verifier prompt version, provider/model, "
        "embedding config, retrieval top_k/threshold) with explicit "
        "confirmation. Any other use is a regression/comparison run, not a "
        "pristine holdout."
    ),
    "verifier_call_semantics": (
        "One external verifier call per query that retrieved at least one "
        "candidate. Under the real benchmark retrieval configuration (local "
        "FastEmbed, threshold 0.5, top_k 5) every current v1 query retrieves "
        "at least one candidate, so expected calls are 43 overall, 30 DEV, 13 "
        "REGRESSION."
    ),
    "benchmark_mode": (
        "mock embeddings or mock verifier = infrastructure test only; results "
        "carry no semantic meaning. Real verifier quality is only measured "
        "with local FastEmbed retrieval (BAAI/bge-small-en-v1.5) plus an "
        "external verifier (--provider deepseek --allow-external-api)."
    ),
}


def run_mode(embedding_provider: str, verifier_provider: str) -> str:
    """Classify the run: infrastructure test vs semantic verifier benchmark."""
    if embedding_provider == "mock" or verifier_provider == "mock":
        return "infrastructure_test"
    return "semantic_benchmark"


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _metric_rows(metrics: dict[str, Any]) -> list[tuple[str, str]]:
    rows = []
    for key in _METRIC_KEYS:
        if key in metrics:
            label = key.replace("_", " ").title()
            rows.append((label, _fmt(metrics[key])))
    return rows


def _outcome_dict(outcome) -> dict[str, Any]:
    return {
        "query_id": outcome.query_id,
        "split": outcome.split,
        "scope": outcome.scope,
        "category": outcome.category,
        "answerable": outcome.answerable,
        "question": outcome.question,
        "supported": outcome.supported,
        "reason": outcome.reason,
        "evidence_source_ids": list(outcome.evidence_source_ids),
        "evidence_count": outcome.evidence_count,
        "evidence_ids": list(outcome.evidence_ids),
    }


def _invalid_outcome_dict(outcome) -> dict[str, Any]:
    data = _outcome_dict(outcome)
    data["error_kind"] = outcome.error_kind
    data["error"] = outcome.error
    return data


def build_verifier_json_report(
    *,
    dataset_version: str,
    embedding_provider: str,
    embedding_model: str,
    embedding_dimension: int,
    top_k: int,
    threshold: float,
    verifier_provider: str,
    verifier_model: str,
    verifier_prompt_version: str,
    external_api: bool,
    corpus_counts: dict[str, int],
    runtime_seconds: float | None,
    git_commit: str | None,
    evaluation: VerifierEvaluation,
    dataset_canonical_sha256: str | None = None,
    frozen_v2_holdout: bool = False,
) -> dict[str, Any]:
    """Assemble the machine-readable verifier report."""
    benchmark: dict[str, Any] = {
        "kind": "evidence_verifier",
        "dataset_version": dataset_version,
        "embedding_provider": embedding_provider,
        "embedding_model": embedding_model,
        "embedding_dimension": embedding_dimension,
        "top_k": top_k,
        "similarity_threshold": threshold,
        "verifier_provider": verifier_provider,
        "verifier_model": verifier_model,
        "verifier_prompt_version": verifier_prompt_version,
        "verifier_calls": evaluation.verifier_calls,
        "run_mode": run_mode(embedding_provider, verifier_provider),
        "external_api": external_api,
        "corpus": corpus_counts,
        "runtime_seconds": round(runtime_seconds, 2) if runtime_seconds is not None else None,
        "git_commit": git_commit,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if dataset_canonical_sha256 is not None:
        benchmark["dataset_canonical_sha256"] = dataset_canonical_sha256
    if frozen_v2_holdout:
        benchmark["frozen_v2_holdout"] = True
        benchmark["one_shot_semantics"] = (
            "Fresh v2 semantic evaluation is intended as a one-shot holdout. "
            "It must not be repeated as if it were a new pristine experiment; "
            "re-running under different inputs turns v2 into a regression set."
        )
    return {
        "benchmark": benchmark,
        "methodology": METHODOLOGY,
        "metrics": evaluation.metrics,
        "invalid_outputs": [_invalid_outcome_dict(o) for o in evaluation.invalid_outputs],
        "evidence_validation_failures": [
            _invalid_outcome_dict(o) for o in evaluation.evidence_validation_failures
        ],
        "false_supports": [_outcome_dict(o) for o in evaluation.false_supports],
        "false_rejections": [_outcome_dict(o) for o in evaluation.false_rejections],
        "outcomes": [
            _outcome_dict(o) for o in sorted(evaluation.outcomes, key=lambda o: o.query_id)
        ],
    }


def _markdown_table(rows: list[tuple[str, str]]) -> list[str]:
    lines = ["| Metric | Result |", "|---|---|"]
    for name, value in rows:
        lines.append(f"| {name} | {value} |")
    return lines


def _render_metrics_group(lines: list[str], metrics: dict[str, Any]) -> None:
    lines.extend(_markdown_table(_metric_rows(metrics)))


def _render_flagged(lines: list[str], title: str, entries: list[dict[str, Any]]) -> None:
    lines.append(f"## {title}")
    lines.append("")
    if not entries:
        lines.append("None.")
        lines.append("")
        return
    for entry in sorted(entries, key=lambda e: e["query_id"]):
        lines.append(f"- **{entry['query_id']}** ({entry['split']}, {entry['category']})")
        lines.append(f"  - Question: {entry['question']}")
        lines.append(f"  - Supported: {entry['supported']}, reason: {entry['reason']}")
        ids = ", ".join(entry["evidence_source_ids"]) or "none"
        lines.append(f"  - Evidence ids: {ids}")
    lines.append("")


def _render_invalid(lines: list[str], title: str, entries: list[dict[str, Any]]) -> None:
    lines.append(f"## {title}")
    lines.append("")
    if not entries:
        lines.append("None.")
        lines.append("")
        return
    for entry in sorted(entries, key=lambda e: e["query_id"]):
        lines.append(f"- **{entry['query_id']}** ({entry['split']})")
        lines.append(f"  - Error kind: {entry.get('error_kind')}")
        lines.append(f"  - Error: {entry.get('error')}")
    lines.append("")


def render_verifier_markdown(report: dict[str, Any]) -> str:
    benchmark = report["benchmark"]
    methodology = report.get("methodology", {})
    lines: list[str] = []
    lines.append("# DocuMind Evidence Verifier Evaluation Harness (PoC 3F-A)")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    lines.append(f"- Dataset version: {benchmark['dataset_version']}")
    lines.append(f"- Embedding provider: {benchmark['embedding_provider']}")
    lines.append(f"- Embedding model: {benchmark['embedding_model']}")
    lines.append(f"- Embedding dimension: {benchmark['embedding_dimension']}")
    lines.append(f"- top_k: {benchmark['top_k']}")
    lines.append(f"- similarity threshold: {benchmark['similarity_threshold']}")
    lines.append(f"- Verifier provider: {benchmark['verifier_provider']}")
    lines.append(f"- Verifier model: {benchmark['verifier_model']}")
    lines.append(f"- Verifier prompt version: {benchmark['verifier_prompt_version']}")
    lines.append(f"- Verifier calls: {benchmark['verifier_calls']}")
    lines.append(f"- Run mode: {benchmark['run_mode']}")
    lines.append(f"- External API calls: {benchmark['external_api']}")
    if benchmark.get("dataset_canonical_sha256"):
        lines.append(f"- Dataset canonical SHA-256: {benchmark['dataset_canonical_sha256']}")
    if benchmark.get("frozen_v2_holdout"):
        lines.append("- Frozen v2 holdout: **one-shot** (confirmed)")
        lines.append(f"- One-shot semantics: {benchmark['one_shot_semantics']}")
    corpus = benchmark["corpus"]
    lines.append(
        f"- Corpus: {corpus.get('private_documents', '?')} private docs, "
        f"{corpus.get('reference_documents', '?')} reference docs, "
        f"{corpus.get('chunks', '?')} chunks"
    )
    if benchmark.get("runtime_seconds") is not None:
        lines.append(f"- Runtime: {benchmark['runtime_seconds']}s")
    lines.append("")

    if benchmark["run_mode"] == "infrastructure_test":
        lines.append("## Provider note (infrastructure test only)")
        lines.append("")
        lines.append(
            "This run used mock embeddings and/or a mock verifier, so it is an "
            "infrastructure test only. Results have NO semantic meaning and say "
            "nothing about verifier quality; they only prove the pipeline, "
            "validation, metrics, and reporting work."
        )
        lines.append("")
    else:
        lines.append("## Provider note (semantic verifier benchmark)")
        lines.append("")
        lines.append(
            "This run used local FastEmbed retrieval with an external verifier. "
            "Metrics here are the semantic verifier benchmark results for the "
            "recorded prompt version and model."
        )
        lines.append("")

    lines.append("## Methodology")
    lines.append("")
    lines.append(f"- Split labels: {methodology.get('split_labels')}")
    lines.append(f"- Regression set: {methodology.get('regression_set')}")
    lines.append(f"- No v2 holdout: {methodology.get('no_v2_holdout')}")
    lines.append(f"- V2 holdout contract: {methodology.get('v2_holdout_contract')}")
    lines.append(f"- Decision contract: {methodology.get('decision_contract')}")
    lines.append(f"- Zero evidence: {methodology.get('zero_evidence')}")
    lines.append(f"- Verifier call semantics: {methodology.get('verifier_call_semantics')}")
    lines.append(f"- Benchmark mode: {methodology.get('benchmark_mode')}")
    lines.append(f"- Prompt injection: {methodology.get('prompt_injection')}")
    lines.append("")

    metrics = report.get("metrics", {})
    for group in ("overall", "split:dev", "split:regression"):
        group_metrics = metrics.get(group)
        if not group_metrics:
            continue
        label = {
            "overall": "Overall",
            "split:dev": "DEV metrics",
            "split:regression": "REGRESSION metrics",
        }[group]
        lines.append(f"## {label}")
        lines.append("")
        _render_metrics_group(lines, group_metrics)
        lines.append("")

    lines.append("## Per scope")
    lines.append("")
    for scope in ("private", "reference", "combined"):
        scope_metrics = metrics.get(scope)
        if not scope_metrics:
            continue
        lines.append(f"### {scope.capitalize()}")
        lines.append("")
        _render_metrics_group(lines, scope_metrics)
        lines.append("")

    _render_flagged(
        lines,
        "False supports (unanswerable but accepted)",
        report.get("false_supports", []),
    )
    _render_flagged(
        lines, "False rejections (answerable but rejected)", report.get("false_rejections", [])
    )
    _render_invalid(lines, "Invalid verifier outputs", report.get("invalid_outputs", []))
    _render_invalid(
        lines,
        "Evidence-source validation failures",
        report.get("evidence_validation_failures", []),
    )

    lines.append("## Security / invariants")
    lines.append("")
    lines.append(
        "The verifier receives only retrieved, server-authorized candidates. "
        "No new DB retrieval, no user/scope expansion, and no external "
        "knowledge source feed the verifier. Evidence source ids are validated "
        "against the supplied evidence only. Retrieval leakage tests remain "
        "authoritative."
    )
    lines.append("")

    lines.append("## Future v2 holdout contract")
    lines.append("")
    lines.append(
        "This harness accepts any dataset path and derives splits from the "
        "dataset's own split field, so a future milestone can run DEV/frozen "
        "verifier then a fresh v2 holdout without redesigning the evaluator. "
        "No v2 holdout was created in this task."
    )
    lines.append("")
    return "\n".join(lines)


def write_json_report(report: dict[str, Any], path) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, ensure_ascii=False)
