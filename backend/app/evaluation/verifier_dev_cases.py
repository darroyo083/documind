"""Loading and validation for the verifier-contract DEVELOPMENT datasets.

The development datasets (``backend/experiments/verifier_contract/dev_cases.json``
and ``backend/experiments/verifier_contract/injection_dev_cases.json``) are
NOT holdouts: they are direct-drive sets used to exercise the hardened
verifier contract (schema v2 + prompt v2) WITHOUT retrieval. Evidence is
provided inline per case, and each case carries its own evaluation labels:

- ``expected_supported``: the answerability ground truth
- ``expected_source_ids``: the supporting source ids required for a correct
  supported decision
- ``category``: the design class the case exercises

The injection development suite is the E1 adversarial set (12 cases) used to
benchmark prompt-injection resistance; it validates under the exact same
strict rules as every other dev-direct dataset.

Evaluation-only metadata (``expected_supported``, ``expected_source_ids``,
``category``) must never enter the model payload; :func:`case_evidence_items`
builds verifier-safe :class:`EvidenceItem` objects carrying only grounding
metadata, exactly like the retrieval pipeline does.

Nothing in this module is used by production code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.evaluation.verifier import EvidenceItem

DEV_CASES_DATASET_VERSION = "dev-direct"

DEFAULT_DEV_CASES_PATH = (
    Path(__file__).resolve().parents[2] / "experiments" / "verifier_contract" / "dev_cases.json"
)

INJECTION_DEV_CASES_PATH = (
    Path(__file__).resolve().parents[2]
    / "experiments"
    / "verifier_contract"
    / "injection_dev_cases.json"
)

_DEV_CASE_KEYS = frozenset(
    {"id", "category", "question", "evidence", "expected_supported", "expected_source_ids"}
)
_EVIDENCE_KEYS = frozenset({"source_id", "content"})


def load_dev_cases(path: str | Path = DEFAULT_DEV_CASES_PATH) -> dict[str, Any]:
    """Load a dev-direct dataset and run full validation."""
    with open(path, encoding="utf-8") as handle:
        dataset = json.load(handle)
    validate_dev_cases(dataset)
    return dataset


def load_injection_dev_cases(path: str | Path = INJECTION_DEV_CASES_PATH) -> dict[str, Any]:
    """Load the E1 adversarial injection development suite under the same strict rules."""
    return load_dev_cases(path)


def validate_dev_cases(dataset: dict[str, Any]) -> None:
    """Raise ValueError with every structural violation of the dev dataset."""
    errors: list[str] = []

    if dataset.get("dataset_version") != DEV_CASES_DATASET_VERSION:
        errors.append(f"dataset_version must be {DEV_CASES_DATASET_VERSION!r}")

    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("dataset must define a non-empty 'cases' list")
        cases = []

    seen_ids: set[str] = set()
    for index, case in enumerate(cases):
        prefix = f"case[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix}: case must be an object")
            continue
        unknown = sorted(set(case) - _DEV_CASE_KEYS)
        if unknown:
            errors.append(f"{prefix}: unknown field(s): {unknown}")

        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"{prefix}: missing id")
        else:
            if case_id in seen_ids:
                errors.append(f"{prefix}: duplicate case id {case_id!r}")
            seen_ids.add(case_id)

        if not isinstance(case.get("category"), str) or not case["category"]:
            errors.append(f"{prefix}: category must be a non-empty string")
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            errors.append(f"{prefix}: question must be a non-empty string")

        expected_supported = case.get("expected_supported")
        if not isinstance(expected_supported, bool):
            errors.append(f"{prefix}: expected_supported must be a boolean")

        evidence = case.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{prefix}: evidence must be a non-empty list")
            evidence = []

        evidence_ids: list[str] = []
        for item_index, item in enumerate(evidence):
            item_prefix = f"{prefix}.evidence[{item_index}]"
            if not isinstance(item, dict):
                errors.append(f"{item_prefix}: evidence item must be an object")
                continue
            unknown = sorted(set(item) - _EVIDENCE_KEYS)
            if unknown:
                errors.append(f"{item_prefix}: unknown field(s): {unknown}")
            source_id = item.get("source_id")
            if not isinstance(source_id, str) or not source_id:
                errors.append(f"{item_prefix}: source_id must be a non-empty string")
            else:
                evidence_ids.append(source_id)
            if not isinstance(item.get("content"), str) or not item["content"].strip():
                errors.append(f"{item_prefix}: content must be a non-empty string")
        if len(evidence_ids) != len(set(evidence_ids)):
            errors.append(f"{prefix}: duplicate source_id within one case")

        expected_ids = case.get("expected_source_ids")
        if not isinstance(expected_ids, list):
            errors.append(f"{prefix}: expected_source_ids must be a list")
            expected_ids = []
        elif any(not isinstance(sid, str) for sid in expected_ids):
            errors.append(f"{prefix}: expected_source_ids entries must be strings")

        if expected_supported is True:
            if not expected_ids:
                errors.append(f"{prefix}: expected_supported=true requires expected_source_ids")
            unknown_expected = [sid for sid in expected_ids if sid not in evidence_ids]
            if unknown_expected:
                errors.append(
                    f"{prefix}: expected_source_ids not present in the case evidence: "
                    f"{unknown_expected}"
                )
        elif expected_supported is False and expected_ids:
            errors.append(
                f"{prefix}: expected_supported=false requires expected_source_ids to be empty"
            )

    if errors:
        raise ValueError("Invalid verifier dev dataset:\n- " + "\n- ".join(errors))


def case_evidence_items(case: dict[str, Any]) -> list[EvidenceItem]:
    """Build verifier-safe evidence items for one dev case.

    Only grounding metadata is carried (source id + content, with neutral
    payload defaults). Evaluation labels are deliberately absent.
    """
    return [
        EvidenceItem(
            source_id=item["source_id"],
            source_kind="private",
            document_name="dev-document",
            page_number=1,
            content=item["content"],
            score=1.0,
        )
        for item in case["evidence"]
    ]
