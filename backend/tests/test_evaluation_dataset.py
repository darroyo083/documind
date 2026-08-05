"""Tests for evaluation dataset validation and the committed dataset."""

import copy
from pathlib import Path

import pytest

from app.evaluation import dataset as ds

DATASET_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "evaluation" / "datasets" / "retrieval_v1.json"
)


@pytest.fixture(scope="module")
def committed_dataset():
    return ds.load_dataset(DATASET_PATH)


def test_committed_dataset_is_valid(committed_dataset):
    summary = ds.dataset_summary(committed_dataset)
    assert summary["dataset_version"] == "1"
    assert summary["users"] == 2
    assert summary["private_spaces"] == 4
    assert summary["private_documents"] == 8
    assert summary["reference_documents"] == 3
    assert summary["total_pages"] == 21
    assert 40 <= summary["queries"] <= 50
    assert summary["answerable"] + summary["unanswerable"] == summary["queries"]
    assert summary["unanswerable"] == 9
    assert summary["answerable"] == 34
    assert summary["relevant_chunks"] == 39


def test_committed_dataset_categories(committed_dataset):
    summary = ds.dataset_summary(committed_dataset)
    for category in ds.VALID_CATEGORIES:
        assert category in summary["categories"], f"missing category {category}"


def test_committed_dataset_scopes(committed_dataset):
    summary = ds.dataset_summary(committed_dataset)
    assert set(summary["scopes"]) == {"private", "reference", "combined"}


def test_committed_unanswerable_breakdown(committed_dataset):
    by_scope: dict[str, int] = {}
    for query in committed_dataset["queries"]:
        if not query["answerable"]:
            by_scope[query["scope"]] = by_scope.get(query["scope"], 0) + 1
    assert by_scope == {"private": 3, "reference": 3, "combined": 3}


def test_reject_duplicate_query_ids(committed_dataset):
    mutated = copy.deepcopy(committed_dataset)
    mutated["queries"][1]["id"] = mutated["queries"][0]["id"]
    with pytest.raises(ValueError, match="duplicate query id"):
        ds.validate_dataset(mutated)


def test_reject_invalid_scope(committed_dataset):
    mutated = copy.deepcopy(committed_dataset)
    mutated["queries"][0]["scope"] = "everything"
    with pytest.raises(ValueError, match="invalid scope"):
        ds.validate_dataset(mutated)


def test_reject_answerable_without_relevant_chunks(committed_dataset):
    mutated = copy.deepcopy(committed_dataset)
    mutated["queries"][0]["expected_relevant_chunks"] = []
    with pytest.raises(ValueError, match="no relevant chunks"):
        ds.validate_dataset(mutated)


def test_reject_unknown_semantic_chunk(committed_dataset):
    mutated = copy.deepcopy(committed_dataset)
    mutated["queries"][0]["expected_relevant_chunks"] = ["not_a_page_id"]
    with pytest.raises(ValueError, match="unknown relevant chunk"):
        ds.validate_dataset(mutated)


def test_reject_unknown_fixture_document(committed_dataset):
    mutated = copy.deepcopy(committed_dataset)
    mutated["queries"][0]["expected_relevant_documents"] = ["not_a_document"]
    with pytest.raises(ValueError, match="unknown relevant document"):
        ds.validate_dataset(mutated)


def test_reject_duplicate_semantic_ids_across_documents(committed_dataset):
    mutated = copy.deepcopy(committed_dataset)
    target_doc = mutated["users"]["user_b"]["spaces"]["user_b_space"]["documents"]["user_b_policy"]
    target_doc["pages"][0] = {
        "semantic_id": "private_policy_cancellation",
        "text": "Orion Health Plan. Cancellation requires 45 days written notice.",
    }
    with pytest.raises(ValueError, match="more than one document"):
        ds.validate_dataset(mutated)


def test_reject_page_without_semantic_id(committed_dataset):
    mutated = copy.deepcopy(committed_dataset)
    target_doc = mutated["users"]["user_a"]["spaces"]["user_a_insurance"]["documents"][
        "user_a_policy"
    ]
    target_doc["pages"].append({"text": "A page without a semantic id."})
    with pytest.raises(ValueError, match="without a semantic_id"):
        ds.validate_dataset(mutated)


def test_reject_expected_doc_also_forbidden(committed_dataset):
    mutated = copy.deepcopy(committed_dataset)
    query = next(q for q in mutated["queries"] if q["id"] == "priv_direct_cancel")
    query["forbidden_documents"] = ["user_a_policy"]
    with pytest.raises(ValueError, match="also forbidden"):
        ds.validate_dataset(mutated)


def test_reject_malformed_category(committed_dataset):
    mutated = copy.deepcopy(committed_dataset)
    mutated["queries"][0]["category"] = "made_up"
    with pytest.raises(ValueError, match="invalid category"):
        ds.validate_dataset(mutated)


def test_reject_cross_space_relevant_chunk_not_in_space(committed_dataset):
    mutated = copy.deepcopy(committed_dataset)
    query = next(q for q in mutated["queries"] if q["id"] == "cross_space_cancel")
    query["expected_relevant_chunks"] = ["private_housing_notice"]
    query["expected_relevant_documents"] = ["user_a_rental"]
    with pytest.raises(ValueError, match="not in requested space"):
        ds.validate_dataset(mutated)


def test_unanswerable_category_requires_answerable_false(committed_dataset):
    mutated = copy.deepcopy(committed_dataset)
    query = next(q for q in mutated["queries"] if q["id"] == "unanswerable_private")
    query["answerable"] = True
    query["expected_relevant_chunks"] = ["private_policy_cancellation"]
    query["expected_relevant_documents"] = ["user_a_policy"]
    with pytest.raises(ValueError, match="answerable"):
        ds.validate_dataset(mutated)


def test_semantic_ids_never_leak_into_questions(committed_dataset):
    semantic_ids = set()
    for user in committed_dataset["users"].values():
        for space in user["spaces"].values():
            for doc in space["documents"].values():
                for page in doc["pages"]:
                    semantic_ids.add(page["semantic_id"])
    for doc in committed_dataset["reference_documents"].values():
        for page in doc["pages"]:
            semantic_ids.add(page["semantic_id"])
    for query in committed_dataset["queries"]:
        for semantic_id in semantic_ids:
            assert semantic_id not in query["question"]


def test_no_evaluation_markers_in_dataset_text(committed_dataset):
    for user in committed_dataset["users"].values():
        for space in user["spaces"].values():
            for doc in space["documents"].values():
                for page in doc["pages"]:
                    assert "EVAL_FACT_" not in page["text"]
    for doc in committed_dataset["reference_documents"].values():
        for page in doc["pages"]:
            assert "EVAL_FACT_" not in page["text"]
