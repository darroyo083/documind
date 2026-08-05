"""Evaluation dataset loading and validation.

The dataset is a committed, human-readable JSON definition with explicit
ground truth. Pages carry stable ``semantic_id`` values that are used to map
produced chunks to ground truth; they never appear in query text and are never
part of the text sent to the embedding provider. Production retrieval code
never depends on this module.
"""

import json
from pathlib import Path
from typing import Any

VALID_SCOPES = {"private", "reference", "combined"}
VALID_CATEGORIES = {
    "private_direct",
    "private_paraphrase",
    "private_multi_chunk",
    "reference_direct",
    "reference_paraphrase",
    "combined_private_winner",
    "combined_reference_winner",
    "combined_multi_source",
    "cross_space_decoy",
    "cross_user_decoy",
    "unanswerable_private",
    "unanswerable_reference",
    "unanswerable_combined",
    "hard_negative",
    "semantic_decoy",
}
UNANSWERABLE_CATEGORIES = {
    "unanswerable_private",
    "unanswerable_reference",
    "unanswerable_combined",
}
REFERENCE_CATEGORIES = {
    "reference_direct",
    "reference_paraphrase",
    "unanswerable_reference",
}
PRIVATE_CATEGORIES = {
    "private_direct",
    "private_paraphrase",
    "private_multi_chunk",
    "unanswerable_private",
    "cross_space_decoy",
    "cross_user_decoy",
}
COMBINED_CATEGORIES = {
    "combined_private_winner",
    "combined_reference_winner",
    "combined_multi_source",
    "unanswerable_combined",
}


def load_dataset(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        dataset = json.load(handle)
    validate_dataset(dataset)
    return dataset


def _collect_documents(dataset: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map semantic document id -> document record for all private + reference docs."""
    documents: dict[str, dict[str, Any]] = {}
    for user_key, user in dataset["users"].items():
        for space_key, space in user["spaces"].items():
            for doc_key, doc in space["documents"].items():
                documents[doc_key] = {
                    "kind": "private",
                    "user": user_key,
                    "space": space_key,
                    "filename": doc["filename"],
                    "pages": doc["pages"],
                }
    for doc_key, doc in dataset["reference_documents"].items():
        documents[doc_key] = {
            "kind": "reference",
            "user": None,
            "space": None,
            "filename": doc["filename"],
            "pages": doc["pages"],
        }
    return documents


def _collect_semantic_pages(
    documents: dict[str, dict[str, Any]],
) -> tuple[dict[str, str], dict[str, list[dict[str, Any]]]]:
    """Map semantic page id -> document id, plus document id -> page records."""
    page_documents: dict[str, str] = {}
    pages_by_document: dict[str, list[dict[str, Any]]] = {}
    for doc_key, doc in documents.items():
        for page in doc["pages"]:
            semantic_id = page.get("semantic_id")
            if semantic_id in page_documents and page_documents[semantic_id] != doc_key:
                raise ValueError(
                    f"Semantic page id {semantic_id} appears in more than one document"
                )
            page_documents[semantic_id] = doc_key
            pages_by_document.setdefault(doc_key, []).append(page)
    return page_documents, pages_by_document


def validate_dataset(dataset: dict[str, Any]) -> None:
    errors: list[str] = []

    if not isinstance(dataset.get("dataset_version"), str) or not dataset["dataset_version"]:
        errors.append("dataset_version must be a non-empty string")
    if "users" not in dataset or not dataset["users"]:
        errors.append("dataset must define at least one user")
    if "reference_documents" not in dataset or not dataset["reference_documents"]:
        errors.append("dataset must define at least one reference document")
    if "queries" not in dataset or not dataset["queries"]:
        errors.append("dataset must define at least one query")

    documents = _collect_documents(dataset)
    page_documents: dict[str, str] = {}
    for doc_key, doc in documents.items():
        if not doc["pages"]:
            errors.append(f"document {doc_key} has no pages")
        for page in doc["pages"]:
            if not isinstance(page, dict) or not isinstance(page.get("semantic_id"), str):
                errors.append(f"document {doc_key} has a page without a semantic_id")
                continue
            if not isinstance(page.get("text"), str) or not page["text"].strip():
                errors.append(f"document {doc_key} page {page['semantic_id']} has empty text")
            semantic_id = page["semantic_id"]
            if semantic_id in page_documents and page_documents[semantic_id] != doc_key:
                errors.append(f"semantic page id {semantic_id} appears in more than one document")
            page_documents[semantic_id] = doc_key

    seen_ids: set[str] = set()
    for index, query in enumerate(dataset["queries"]):
        prefix = f"query[{index}]"
        query_id = query.get("id")
        if not isinstance(query_id, str) or not query_id:
            errors.append(f"{prefix}: missing id")
            continue
        if query_id in seen_ids:
            errors.append(f"{prefix}: duplicate query id {query_id!r}")
        seen_ids.add(query_id)

        scope = query.get("scope")
        if scope not in VALID_SCOPES:
            errors.append(f"{prefix} {query_id}: invalid scope {scope!r}")
        category = query.get("category")
        if category not in VALID_CATEGORIES:
            errors.append(f"{prefix} {query_id}: invalid category {category!r}")

        question = query.get("question")
        if not isinstance(question, str) or not question.strip():
            errors.append(f"{prefix} {query_id}: missing question")

        answerable = query.get("answerable")
        if not isinstance(answerable, bool):
            errors.append(f"{prefix} {query_id}: answerable must be boolean")

        expected_chunks = query.get("expected_relevant_chunks") or []
        expected_docs = query.get("expected_relevant_documents") or []
        forbidden = query.get("forbidden_documents") or []
        for field in (
            "expected_relevant_chunks",
            "expected_relevant_documents",
            "forbidden_documents",
        ):
            value = query.get(field) or []
            if not isinstance(value, list):
                errors.append(f"{prefix} {query_id}: {field} must be a list")

        if answerable and not expected_chunks:
            errors.append(f"{prefix} {query_id}: answerable query has no relevant chunks")
        if not answerable and expected_chunks:
            errors.append(f"{prefix} {query_id}: unanswerable query lists relevant chunks")

        for chunk in expected_chunks:
            if chunk not in page_documents:
                errors.append(f"{prefix} {query_id}: unknown relevant chunk {chunk!r}")
        for doc in expected_docs:
            if doc not in documents:
                errors.append(f"{prefix} {query_id}: unknown relevant document {doc!r}")
        for doc in forbidden:
            if doc not in documents:
                errors.append(f"{prefix} {query_id}: unknown forbidden document {doc!r}")
        overlap = set(expected_docs) & set(forbidden)
        if overlap:
            errors.append(
                f"{prefix} {query_id}: expected document also forbidden: {sorted(overlap)}"
            )

        kinds = query.get("expected_source_kinds") or []
        for kind in kinds:
            if kind not in {"private", "reference"}:
                errors.append(f"{prefix} {query_id}: invalid expected source kind {kind!r}")

        if category in UNANSWERABLE_CATEGORIES and answerable:
            errors.append(f"{prefix} {query_id}: unanswerable category must be answerable=false")
        if category in UNANSWERABLE_CATEGORIES and scope != category.replace("unanswerable_", ""):
            errors.append(f"{prefix} {query_id}: unanswerable category scope mismatch")
        if category in PRIVATE_CATEGORIES and scope != "private":
            errors.append(f"{prefix} {query_id}: private category requires private scope")
        if category in REFERENCE_CATEGORIES and scope != "reference":
            errors.append(f"{prefix} {query_id}: reference category requires reference scope")
        if category in COMBINED_CATEGORIES and scope != "combined":
            errors.append(f"{prefix} {query_id}: combined category requires combined scope")
        if category in {"cross_space_decoy", "cross_user_decoy"} and not forbidden:
            errors.append(f"{prefix} {query_id}: decoy category must list forbidden documents")
        if category == "combined_multi_source" and set(kinds) != {"private", "reference"}:
            errors.append(f"{prefix} {query_id}: combined_multi_source needs both source kinds")

        space = query.get("space")
        space_exists = any(space in user.get("spaces", {}) for user in dataset["users"].values())
        if not space_exists:
            errors.append(f"{prefix} {query_id}: unknown space {space!r}")

        for chunk in expected_chunks:
            chunk_doc = page_documents.get(chunk)
            if chunk_doc in set(forbidden):
                errors.append(
                    f"{prefix} {query_id}: relevant chunk {chunk!r} belongs to a forbidden document"
                )
            if category in {"cross_space_decoy"} and chunk_doc:
                doc = documents[chunk_doc]
                if doc["kind"] != "private" or doc["space"] != space:
                    errors.append(
                        f"{prefix} {query_id}: cross-space query relevant chunk "
                        "is not in requested space"
                    )
            if category in {"cross_user_decoy"} and chunk_doc:
                doc = documents[chunk_doc]
                if doc["kind"] != "private" or doc["space"] != space:
                    errors.append(
                        f"{prefix} {query_id}: cross-user query relevant chunk "
                        "is not in requested space"
                    )

    if errors:
        raise ValueError("Invalid evaluation dataset:\n- " + "\n- ".join(errors))


def dataset_summary(dataset: dict[str, Any]) -> dict[str, Any]:
    documents = _collect_documents(dataset)
    _, pages_by_document = _collect_semantic_pages(documents)
    queries = dataset["queries"]
    private_docs = sum(1 for doc in documents.values() if doc["kind"] == "private")
    reference_docs = sum(1 for doc in documents.values() if doc["kind"] == "reference")
    categories: dict[str, int] = {}
    scopes: dict[str, int] = {}
    answerable = 0
    relevant_chunks = 0
    for query in queries:
        categories[query["category"]] = categories.get(query["category"], 0) + 1
        scopes[query["scope"]] = scopes.get(query["scope"], 0) + 1
        answerable += 1 if query["answerable"] else 0
        if query["answerable"]:
            relevant_chunks += len(query.get("expected_relevant_chunks") or [])
    return {
        "dataset_version": dataset["dataset_version"],
        "users": len(dataset["users"]),
        "private_spaces": sum(len(user.get("spaces", {})) for user in dataset["users"].values()),
        "private_documents": private_docs,
        "reference_documents": reference_docs,
        "total_pages": sum(len(pages) for pages in pages_by_document.values()),
        "queries": len(queries),
        "answerable": answerable,
        "unanswerable": len(queries) - answerable,
        "relevant_chunks": relevant_chunks,
        "categories": categories,
        "scopes": scopes,
    }
