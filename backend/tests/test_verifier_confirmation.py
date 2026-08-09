"""Offline tests for the frozen development-confirmation suite (E0, 8 cases).

The suite at ``backend/experiments/verifier_contract/confirmation_cases.json``
is the approved Worker B confirmation set frozen for the E0 verifier v2
validation run: exactly 8 cases (4 supported / 4 unsupported) covering all 8
requirement categories, ids disjoint from every existing set, no exact text
reuse vs the dev / retrieval_v1 / holdout_v2 / holdout_v3 datasets, and no
evaluation labels inside evidence content. Zero network calls.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.evaluation import verifier_dev_cases

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEV_CASES_PATH = BACKEND_DIR / "experiments" / "verifier_contract" / "dev_cases.json"
V2_DATASET_PATH = BACKEND_DIR / "app" / "evaluation" / "datasets" / "verifier_holdout_v2.json"
V3_DATASET_PATH = BACKEND_DIR / "app" / "evaluation" / "datasets" / "verifier_holdout_v3.json"

CONFIRMATION_CASES_PATH = (
    BACKEND_DIR / "experiments" / "verifier_contract" / "confirmation_cases.json"
)

REQUIRED_CONFIRMATION_CATEGORIES = frozenset(
    {
        "answerable_private_direct",
        "answerable_private_paraphrase",
        "answerable_private_numeric",
        "answerable_combined_multi_source",
        "unsupported_wrong_fact",
        "unsupported_numeric_mismatch",
        "unsupported_semantic_distractor",
        "security_prompt_injection",
    }
)

FROZEN_DATASET_PATHS = (
    BACKEND_DIR / "app" / "evaluation" / "datasets" / "retrieval_v1.json",
    V2_DATASET_PATH,
    V3_DATASET_PATH,
)


def _normalized_text(value: str) -> str:
    import re

    return re.sub(r"\s+", " ", value.strip()).lower()


def _collect_text(obj, texts: list[str]) -> None:
    if isinstance(obj, str):
        if obj.strip():
            texts.append(_normalized_text(obj))
    elif isinstance(obj, dict):
        for value in obj.values():
            _collect_text(value, texts)
    elif isinstance(obj, list):
        for item in obj:
            _collect_text(item, texts)


class TestConfirmationDataset:
    def test_confirmation_cases_load_and_validate(self):
        dataset = verifier_dev_cases.load_dev_cases(CONFIRMATION_CASES_PATH)
        assert dataset["dataset_version"] == "dev-direct"
        assert len(dataset["cases"]) == 8

    def test_confirmation_balance_is_four_supported_four_unsupported(self):
        dataset = verifier_dev_cases.load_dev_cases(CONFIRMATION_CASES_PATH)
        supported = sum(1 for case in dataset["cases"] if case["expected_supported"])
        assert supported == 4
        assert len(dataset["cases"]) - supported == 4

    def test_confirmation_covers_all_eight_requirement_categories(self):
        dataset = verifier_dev_cases.load_dev_cases(CONFIRMATION_CASES_PATH)
        categories = {case["category"] for case in dataset["cases"]}
        assert categories == REQUIRED_CONFIRMATION_CATEGORIES
        assert len(categories) == 8

    def test_confirmation_case_ids_unique(self):
        dataset = verifier_dev_cases.load_dev_cases(CONFIRMATION_CASES_PATH)
        ids = [case["id"] for case in dataset["cases"]]
        assert len(ids) == len(set(ids))

    def test_confirmation_expected_source_ids_consistent_with_evidence(self):
        dataset = verifier_dev_cases.load_dev_cases(CONFIRMATION_CASES_PATH)
        for case in dataset["cases"]:
            evidence_ids = {item["source_id"] for item in case["evidence"]}
            if case["expected_supported"]:
                assert case["expected_source_ids"]
                assert set(case["expected_source_ids"]) <= evidence_ids
            else:
                assert case["expected_source_ids"] == []

    def test_confirmation_ids_disjoint_from_dev_and_frozen_datasets(self):
        dataset = verifier_dev_cases.load_dev_cases(CONFIRMATION_CASES_PATH)
        confirmation_ids = {case["id"] for case in dataset["cases"]}
        known_ids: set[str] = set()
        dev = verifier_dev_cases.load_dev_cases(DEV_CASES_PATH)
        known_ids.update(case["id"] for case in dev["cases"])
        for path in FROZEN_DATASET_PATHS:
            with open(path, encoding="utf-8") as handle:
                frozen = json.load(handle)
            known_ids.update(query["id"] for query in frozen["queries"])
        assert confirmation_ids.isdisjoint(known_ids)

    def test_confirmation_content_not_reused_from_other_sets(self):
        dataset = verifier_dev_cases.load_dev_cases(CONFIRMATION_CASES_PATH)
        confirmation_texts: list[str] = []
        for case in dataset["cases"]:
            _collect_text(case["question"], confirmation_texts)
            for item in case["evidence"]:
                _collect_text(item["content"], confirmation_texts)
        assert len(confirmation_texts) == 8 + sum(
            len(case["evidence"]) for case in dataset["cases"]
        )

        existing_texts: list[str] = []
        dev = verifier_dev_cases.load_dev_cases(DEV_CASES_PATH)
        for case in dev["cases"]:
            _collect_text(case["question"], existing_texts)
            for item in case["evidence"]:
                _collect_text(item["content"], existing_texts)
        for path in FROZEN_DATASET_PATHS:
            with open(path, encoding="utf-8") as handle:
                _collect_text(json.load(handle), existing_texts)

        existing = set(existing_texts)
        duplicates = [text for text in confirmation_texts if text in existing]
        assert duplicates == []

    def test_confirmation_evidence_contains_no_evaluation_labels(self):
        dataset = verifier_dev_cases.load_dev_cases(CONFIRMATION_CASES_PATH)
        for case in dataset["cases"]:
            for item in case["evidence"]:
                content = item["content"].lower()
                for label in ("expected_supported", "category", "answerable"):
                    assert label not in content, (
                        f"{case['id']} evidence leaks evaluation label {label!r}"
                    )

    def test_confirmation_cases_never_expose_expected_ids_inside_questions(self):
        dataset = verifier_dev_cases.load_dev_cases(CONFIRMATION_CASES_PATH)
        for case in dataset["cases"]:
            for label in ("expected_source_ids", "expected_supported", "source_id"):
                assert label not in case["question"].lower()
