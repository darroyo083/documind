"""Offline tests for the sanitized E0 validation evidence summary (PoC 3F-E0).

Covers: summary identity (milestone/run id/git/versions), group separation
(dev/fresh/combined), per-case records (valid/invalid, prediction, expected,
source-validation, gold match), aggregate metrics (valid_output_rate,
accuracy_valid_only, retention/detection, precision, false-support/rejection,
source/provider failure counts, evidence_selection_quality), per-category
breakdown, mandatory sanitization (no API keys, no raw envelopes, no full
text), raw-report SHA-256 hashing, deterministic writing, and the archival CLI
script. Zero network calls; no real provider is ever constructed.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from app.evaluation import verifier_archive, verifier_dataset
from app.evaluation.verifier import ReasonCode, VerificationDecision
from app.evaluation.verifier_providers import MockEvidenceVerifier

BACKEND_DIR = Path(__file__).resolve().parents[1]

DEV_CASES = [
    {
        "id": "d1",
        "category": "answerable_private_direct",
        "question": "fabricated question for case d1",
        "evidence": [{"source_id": "s_d1", "content": "fabricated evidence content for d1"}],
        "expected_supported": True,
        "expected_source_ids": ["s_d1"],
    },
    {
        "id": "d2",
        "category": "answerable_private_paraphrase",
        "question": "fabricated question for case d2",
        "evidence": [{"source_id": "s_d2", "content": "fabricated evidence content for d2"}],
        "expected_supported": True,
        "expected_source_ids": ["s_d2"],
    },
    {
        "id": "d3",
        "category": "unsupported_wrong_fact",
        "question": "fabricated question for case d3",
        "evidence": [{"source_id": "s_d3", "content": "fabricated evidence content for d3"}],
        "expected_supported": False,
        "expected_source_ids": [],
    },
]

FRESH_CASES = [
    {
        "id": "f1",
        "category": "answerable_private_direct",
        "question": "fabricated question for case f1",
        "evidence": [{"source_id": "s_f1", "content": "fabricated evidence content for f1"}],
        "expected_supported": True,
        "expected_source_ids": ["s_f1"],
    },
    {
        "id": "f2",
        "category": "unsupported_semantic_distractor",
        "question": "fabricated question for case f2",
        "evidence": [{"source_id": "s_f2", "content": "fabricated evidence content for f2"}],
        "expected_supported": False,
        "expected_source_ids": [],
    },
]


def _write_dataset(path: Path, cases: list[dict]) -> None:
    payload = {"dataset_version": "dev-direct", "purpose": "test fixture", "cases": cases}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _scripted_decision(question, evidence):
    """Perfect except d2 (ghost id -> invalid) and f2 (false support)."""
    case_id = question.split()[-1]
    if case_id == "d2":
        return VerificationDecision(
            supported=True,
            reason=ReasonCode.SUFFICIENT_EVIDENCE.value,
            evidence_source_ids=["ghost-id"],
        )
    if case_id == "f2":
        return VerificationDecision(
            supported=True,
            reason=ReasonCode.SUFFICIENT_EVIDENCE.value,
            evidence_source_ids=["s_f2"],
        )
    if case_id in {"d1", "f1"}:
        return VerificationDecision(
            supported=True,
            reason=ReasonCode.SUFFICIENT_EVIDENCE.value,
            evidence_source_ids=[evidence[0].source_id],
        )
    return VerificationDecision(
        supported=False,
        reason=ReasonCode.INSUFFICIENT_EVIDENCE.value,
        evidence_source_ids=[],
    )


def _build_report(cases: list[dict]) -> dict:
    from app.evaluation import verifier_eval, verifier_reporting

    evaluation = asyncio.run(
        verifier_eval.run_direct_cases_evaluation(
            cases, MockEvidenceVerifier(decision_fn=_scripted_decision)
        )
    )
    return verifier_reporting.build_verifier_json_report(
        dataset_version="dev-direct",
        embedding_provider="direct",
        embedding_model="inline-evidence",
        embedding_dimension=0,
        top_k=0,
        threshold=0.0,
        verifier_provider="opencode-go",
        verifier_model="deepseek-v4-flash",
        verifier_prompt_version="2",
        decision_schema_version="2",
        external_api=True,
        corpus_counts={"chunks": 5},
        runtime_seconds=1.25,
        git_commit="a983b55test",
        evaluation=evaluation,
    )


def _build_summary(tmp_path, *, raw_dir=None, run_id="run-test-1"):
    dev_path = tmp_path / "dev_cases.json"
    fresh_path = tmp_path / "fresh_cases.json"
    _write_dataset(dev_path, DEV_CASES)
    _write_dataset(fresh_path, FRESH_CASES)
    summary = verifier_archive.build_e0_validation_summary(
        dev_report=_build_report(DEV_CASES),
        fresh_report=_build_report(FRESH_CASES),
        dev_dataset_path=dev_path,
        fresh_dataset_path=fresh_path,
        run_id=run_id,
        raw_dir=raw_dir,
        timestamp_utc="2026-08-09T18:00:00.000Z",
    )
    return summary


class TestSummaryIdentity:
    def test_identity_fields(self, tmp_path):
        summary = _build_summary(tmp_path)
        assert summary["schema_version"] == "e0-summary-1"
        assert summary["milestone"] == "poc-3f-e0"
        assert summary["experiment"] == "verifier_v2_validation"
        assert summary["run_id"] == "run-test-1"
        assert summary["timestamp_utc"] == "2026-08-09T18:00:00.000Z"
        assert summary["git"]["commit"] == "a983b55test"
        assert summary["inputs"]["verifier_provider"] == "opencode-go"
        assert summary["inputs"]["verifier_model"] == "deepseek-v4-flash"
        assert summary["inputs"]["verifier_prompt_version"] == "2"
        assert summary["inputs"]["decision_schema_version"] == "2"

    def test_inputs_pin_dataset_digests(self, tmp_path):
        summary = _build_summary(tmp_path)
        datasets = summary["inputs"]["datasets"]
        assert [d["group"] for d in datasets] == ["dev", "fresh"]
        dev_entry = datasets[0]
        assert dev_entry["case_count"] == 3
        assert dev_entry["reported_cases"] == 3
        dev_path = tmp_path / "dev_cases.json"
        assert dev_entry["canonical_sha256"] == verifier_dataset.canonical_dataset_digest(dev_path)
        assert summary["inputs"]["verifier_calls"] == {"dev": 3, "fresh": 2, "combined": 5}

    def test_default_run_id_derived_from_timestamp(self, tmp_path):
        summary = _build_summary(tmp_path, run_id=None)
        assert summary["run_id"].startswith("poc-3f-e0-")


class TestCaseRecords:
    def test_group_separation(self, tmp_path):
        summary = _build_summary(tmp_path)
        assert [r["case_id"] for r in summary["cases"] if r["group"] == "dev"] == [
            "d1",
            "d2",
            "d3",
        ]
        assert [r["case_id"] for r in summary["cases"] if r["group"] == "fresh"] == [
            "f1",
            "f2",
        ]

    def test_valid_invalid_and_source_validation_flags(self, tmp_path):
        summary = _build_summary(tmp_path)
        by_id = {r["case_id"]: r for r in summary["cases"]}
        d1, d2, d3, f1, f2 = (by_id[key] for key in ("d1", "d2", "d3", "f1", "f2"))
        assert d1["outcome"]["valid"] is True
        assert d1["outcome"]["source_validation_passed"] is True
        assert d1["outcome"]["correct"] is True
        assert d1["outcome"]["classification"] == "true_positive"
        assert d2["outcome"]["valid"] is False
        assert d2["outcome"]["error_kind"] == "evidence_source_validation"
        assert d2["outcome"]["source_validation_passed"] is False
        assert d2["outcome"]["classification"] is None
        assert d3["outcome"]["classification"] == "true_negative"
        assert f1["outcome"]["classification"] == "true_positive"
        assert f2["outcome"]["valid"] is True
        assert f2["outcome"]["correct"] is False
        assert f2["outcome"]["classification"] == "false_positive"
        assert f2["outcome"]["source_validation_passed"] is True

    def test_prediction_and_expected_per_case(self, tmp_path):
        summary = _build_summary(tmp_path)
        by_id = {r["case_id"]: r for r in summary["cases"]}
        f2 = by_id["f2"]
        assert f2["prediction"]["supported"] is True
        assert f2["prediction"]["evidence_source_ids"] == ["s_f2"]
        assert f2["expected"]["supported"] is False
        assert f2["expected"]["source_ids"] == []
        assert f2["evidence"] == {"source_ids": ["s_f2"], "count": 1}
        assert f2["question_sha256"] and f2["question_sha256"] != "f2"

    def test_gold_source_match(self, tmp_path):
        summary = _build_summary(tmp_path)
        by_id = {r["case_id"]: r for r in summary["cases"]}
        assert by_id["d1"]["outcome"]["gold_source_match"] is True
        assert by_id["d2"]["outcome"]["gold_source_match"] is None  # invalid
        assert by_id["d3"]["outcome"]["gold_source_match"] is None  # unsupported
        assert by_id["f1"]["outcome"]["gold_source_match"] is True


class TestAggregateMetrics:
    def test_dev_metrics(self, tmp_path):
        summary = _build_summary(tmp_path)
        dev = summary["metrics"]["dev"]
        assert dev["total_cases"] == 3
        assert dev["verifier_calls"] == 3
        assert dev["valid_output_count"] == 2
        assert dev["valid_output_rate"] == round(2 / 3, 4)
        assert dev["invalid_output_count"] == 1
        assert dev["source_validation_failure_count"] == 1
        assert dev["provider_failure_count"] == 0
        assert dev["malformed_output_count"] == 0
        assert dev["false_support_count"] == 0
        assert dev["false_rejection_count"] == 0
        assert dev["answerable_retention"] == 1.0
        assert dev["unsupported_detection"] == 1.0
        assert dev["supported_precision"] == 1.0
        assert dev["unsupported_precision"] == 1.0
        assert dev["accuracy_valid_only"] == 1.0
        assert dev["gold_evidence_present_rate"] == 1.0
        assert dev["evidence_selection_quality"] == 1.0

    def test_fresh_metrics_include_false_support(self, tmp_path):
        summary = _build_summary(tmp_path)
        fresh = summary["metrics"]["fresh"]
        assert fresh["total_cases"] == 2
        assert fresh["valid_output_count"] == 2
        assert fresh["false_support_count"] == 1
        assert fresh["answerable_retention"] == 1.0
        assert fresh["unsupported_detection"] == 0.0
        assert fresh["supported_precision"] == 0.5
        assert fresh["unsupported_precision"] is None  # zero denominator -> null
        assert fresh["accuracy_valid_only"] == 0.5
        assert fresh["evidence_selection_quality"] == 1.0

    def test_combined_metrics(self, tmp_path):
        summary = _build_summary(tmp_path)
        combined = summary["metrics"]["combined"]
        assert combined["total_cases"] == 5
        assert combined["verifier_calls"] == 5
        assert combined["valid_output_count"] == 4
        assert combined["invalid_output_count"] == 1
        assert combined["valid_output_rate"] == 0.8
        assert combined["accuracy_valid_only"] == 0.75
        assert combined["answerable_retention"] == 1.0
        assert combined["unsupported_detection"] == 0.5
        assert combined["false_support_count"] == 1
        assert combined["source_validation_failure_count"] == 1

    def test_zero_evidence_cases_do_not_count_as_calls(self, tmp_path):
        from app.evaluation import verifier_eval, verifier_reporting

        zero_case = {
            "id": "d4",
            "category": "unsupported_related_topic",
            "question": "fabricated question for case d4",
            "evidence": [{"source_id": "s_d4", "content": "fabricated evidence content for d4"}],
            "expected_supported": False,
            "expected_source_ids": [],
        }
        cases = DEV_CASES + [zero_case]

        def outcome(
            query_id, answerable, supported, *, invalid=False, error_kind=None, evidence_count=1
        ):
            return verifier_eval.VerifierOutcome(
                query_id=query_id,
                split="dev",
                scope="private",
                category=(
                    "unsupported_related_topic" if not answerable else "answerable_private_direct"
                ),
                answerable=answerable,
                question=f"fabricated question for case {query_id}",
                supported=supported,
                reason=ReasonCode.SUFFICIENT_EVIDENCE.value
                if supported
                else (ReasonCode.INSUFFICIENT_EVIDENCE.value),
                evidence_source_ids=[f"s_{query_id}"] if supported else [],
                evidence_count=evidence_count,
                evidence_ids=[f"s_{query_id}"] if evidence_count else [],
                invalid=invalid,
                error_kind=error_kind,
                error="unknown source id" if error_kind else None,
            )

        outcomes = [
            outcome("d1", True, True),
            outcome("d2", True, True, invalid=True, error_kind="evidence_source_validation"),
            outcome("d3", False, False),
            outcome("d4", False, False, evidence_count=0),
        ]
        evaluation = verifier_eval.VerifierEvaluation(
            outcomes=outcomes,
            metrics=verifier_eval.group_verifier_metrics(outcomes),
            invalid_outputs=[o for o in outcomes if o.invalid],
            evidence_validation_failures=[
                o for o in outcomes if o.error_kind == "evidence_source_validation"
            ],
            false_supports=[],
            false_rejections=[],
            verifier_calls=3,
        )
        report = verifier_reporting.build_verifier_json_report(
            dataset_version="dev-direct",
            embedding_provider="direct",
            embedding_model="inline-evidence",
            embedding_dimension=0,
            top_k=0,
            threshold=0.0,
            verifier_provider="mock",
            verifier_model="mock-deterministic",
            verifier_prompt_version="2",
            external_api=False,
            corpus_counts={"chunks": 1},
            runtime_seconds=None,
            git_commit="a983b55test",
            evaluation=evaluation,
        )
        dev_path = tmp_path / "dev_zero.json"
        _write_dataset(dev_path, cases)
        fresh_path = tmp_path / "fresh_zero.json"
        _write_dataset(fresh_path, FRESH_CASES)
        summary = verifier_archive.build_e0_validation_summary(
            dev_report=report,
            fresh_report=_build_report(FRESH_CASES),
            dev_dataset_path=dev_path,
            fresh_dataset_path=fresh_path,
            run_id="run-zero",
            timestamp_utc="2026-08-09T18:00:00.000Z",
        )
        record = next(r for r in summary["cases"] if r["case_id"] == "d4")
        assert record["verifier_call"]["made"] is False
        assert summary["metrics"]["dev"]["verifier_calls"] == 3
        assert summary["metrics"]["dev"]["total_cases"] == 4


class TestCategoryBreakdown:
    def test_every_case_lands_in_exactly_one_category(self, tmp_path):
        summary = _build_summary(tmp_path)
        breakdown = summary["category_breakdown"]
        assert set(breakdown) == {
            "answerable_private_direct",
            "answerable_private_paraphrase",
            "unsupported_wrong_fact",
            "unsupported_semantic_distractor",
        }
        for per_group in breakdown.values():
            assert set(per_group) == {"dev", "fresh", "combined"}
            counts = {
                group: metrics["total_cases"] if metrics else 0
                for group, metrics in per_group.items()
            }
            assert sum(counts.values()) == counts["combined"] * 2

    def test_category_metrics_computed_per_group(self, tmp_path):
        summary = _build_summary(tmp_path)
        direct = summary["category_breakdown"]["answerable_private_direct"]
        assert direct["dev"]["total_cases"] == 1
        assert direct["dev"]["accuracy_valid_only"] == 1.0
        assert direct["fresh"]["total_cases"] == 1
        assert direct["combined"]["total_cases"] == 2
        distractor = summary["category_breakdown"]["unsupported_semantic_distractor"]
        assert distractor["dev"] is None
        assert distractor["fresh"]["total_cases"] == 1
        assert distractor["fresh"]["false_support_count"] == 1


class TestSanitization:
    def test_no_secrets_or_raw_envelopes_in_serialized_summary(self, tmp_path):
        summary = _build_summary(tmp_path)
        serialized = json.dumps(summary, sort_keys=True).lower()
        for token in ("bearer", "api_key", "api-key", "sk-", "choices", "finish_reason"):
            assert token not in serialized, token

    def test_records_contain_only_sanitized_keys(self, tmp_path):
        summary = _build_summary(tmp_path)
        record = summary["cases"][0]
        assert set(record) == {
            "case_id",
            "group",
            "category",
            "question_sha256",
            "evidence",
            "expected",
            "verifier_call",
            "prediction",
            "outcome",
        }
        assert "question" not in record
        assert "content" not in record["evidence"]
        assert "authorization" not in record["verifier_call"]
        assert "headers" not in record["verifier_call"]

    def test_no_full_question_or_evidence_text(self, tmp_path):
        summary = _build_summary(tmp_path)
        serialized = json.dumps(summary, sort_keys=True)
        for case in DEV_CASES + FRESH_CASES:
            assert case["question"] not in serialized
            for item in case["evidence"]:
                assert item["content"] not in serialized
        assert summary["cases"][0]["question_sha256"]

    def test_only_evidence_source_ids_are_kept(self, tmp_path):
        summary = _build_summary(tmp_path)
        record = next(r for r in summary["cases"] if r["case_id"] == "d1")
        assert record["evidence"] == {"source_ids": ["s_d1"], "count": 1}


class TestRawArtifacts:
    def test_raw_report_sha256_computed_when_raw_dir_provided(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        for case in DEV_CASES + FRESH_CASES:
            envelope = {
                "id": f"chatcmpl-{case['id']}",
                "model": "deepseek-v4-flash",
                "choices": [
                    {"finish_reason": "stop", "message": {"content": '{"supported": false}'}}
                ],
            }
            (raw_dir / f"{case['id']}.json").write_text(
                json.dumps(envelope, sort_keys=True), encoding="utf-8"
            )
        summary = _build_summary(tmp_path, raw_dir=raw_dir)
        by_id = {r["case_id"]: r for r in summary["cases"]}
        assert by_id["d1"]["verifier_call"]["raw_report_sha256"] is not None
        assert by_id["d2"]["verifier_call"]["raw_report_sha256"] is not None
        assert summary["raw_artifacts"]["file_count"] == 5
        assert summary["raw_artifacts"]["digest_method"] == "canonical_json_sha256"
        assert summary["raw_artifacts"]["relative_dir"] == str(raw_dir)

    def test_raw_report_sha256_null_without_raw_dir(self, tmp_path):
        summary = _build_summary(tmp_path)
        for record in summary["cases"]:
            assert record["verifier_call"]["raw_report_sha256"] is None
        assert summary["raw_artifacts"]["file_count"] == 0
        assert summary["raw_artifacts"]["relative_dir"] is None


class TestWriting:
    def test_write_is_deterministic_and_writes_markdown(self, tmp_path):
        summary = _build_summary(tmp_path)
        json_path = tmp_path / "poc_3f_e0_validation.json"
        md_path = tmp_path / "poc_3f_e0_validation.md"
        verifier_archive.write_e0_validation_summary(summary, json_path, md_path)
        first = json_path.read_bytes()
        verifier_archive.write_e0_validation_summary(summary, json_path, md_path)
        second = json_path.read_bytes()
        assert first == second
        assert md_path.is_file()
        markdown = md_path.read_text(encoding="utf-8")
        assert "Verifier calls" in markdown
        assert "d2" in markdown
        assert "bearer" not in markdown.lower()

    def test_report_case_missing_from_dataset_raises(self, tmp_path):
        dev_path = tmp_path / "dev_cases.json"
        fresh_path = tmp_path / "fresh_cases.json"
        _write_dataset(dev_path, DEV_CASES[:-1])
        _write_dataset(fresh_path, FRESH_CASES)
        with pytest.raises(ValueError, match="not present in the dev dataset"):
            verifier_archive.build_e0_validation_summary(
                dev_report=_build_report(DEV_CASES),
                fresh_report=_build_report(FRESH_CASES),
                dev_dataset_path=dev_path,
                fresh_dataset_path=fresh_path,
            )


class TestArchiveCli:
    def test_cli_wires_reports_datasets_and_raw_dir(self, tmp_path):
        dev_path = tmp_path / "dev_cases.json"
        fresh_path = tmp_path / "fresh_cases.json"
        _write_dataset(dev_path, DEV_CASES)
        _write_dataset(fresh_path, FRESH_CASES)
        dev_report_path = tmp_path / "dev_report.json"
        fresh_report_path = tmp_path / "fresh_report.json"
        dev_report_path.write_text(
            json.dumps(_build_report(DEV_CASES), sort_keys=True), encoding="utf-8"
        )
        fresh_report_path.write_text(
            json.dumps(_build_report(FRESH_CASES), sort_keys=True), encoding="utf-8"
        )
        output = tmp_path / "evidence" / "poc_3f_e0_validation.json"

        script = BACKEND_DIR / "scripts" / "archive_verifier_validation.py"
        spec = importlib.util.spec_from_file_location("archive_verifier_validation", script)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        code = module.main(
            [
                "--dev-report",
                str(dev_report_path),
                "--fresh-report",
                str(fresh_report_path),
                "--dev-dataset",
                str(dev_path),
                "--fresh-dataset",
                str(fresh_path),
                "--run-id",
                "run-cli-1",
                "--output",
                str(output),
            ]
        )
        assert code == 0
        assert output.is_file()
        summary = json.loads(output.read_text(encoding="utf-8"))
        assert summary["run_id"] == "run-cli-1"
        assert summary["inputs"]["verifier_calls"]["combined"] == 5
        assert output.with_suffix(".md").is_file()


def test_e0_raw_reports_dir_is_gitignored():
    marker = verifier_archive.E0_RAW_REPORTS_DIR / "probe.json"
    result = subprocess.run(
        ["git", "check-ignore", str(marker)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, "backend/evaluation/results/poc_3f_e0/ must stay gitignored"


def test_tracked_summary_path_is_not_gitignored():
    result = subprocess.run(
        ["git", "check-ignore", str(verifier_archive.DEFAULT_E0_SUMMARY_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, "backend/evaluation/evidence/ must stay trackable"
