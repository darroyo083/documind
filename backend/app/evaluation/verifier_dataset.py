"""Loading and validation for the fresh v2 verifier holdout dataset.

This dataset is the one-shot frozen holdout for the evidence verifier. It is
deliberately validated separately from the v1 retrieval/sufficiency dataset
because v1 enforces a ``dev``/``holdout`` split while v2 must contain exactly
one role: ``fresh_holdout``.

Nothing in this module is used by production code. Ground truth is expressed
exclusively through stable fixture identifiers (page ``semantic_id`` values and
document keys); those identifiers never appear inside query text or document
content.

Validation is intentionally strict: a v2 dataset may only be frozen when every
structural, isolation, and freshness invariant passes.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.evaluation.dataset import VALID_SCOPES

V2_DATASET_VERSION = "2"
V3_DATASET_VERSION = "3"
V2_SPLIT = "fresh_holdout"
V2_QUERY_COUNT = 24
V2_ANSWERABLE_COUNT = 12
V2_UNSUPPORTED_COUNT = 12
V2_SCOPE_COUNTS = {"private": 8, "reference": 8, "combined": 8}
V2_ANSWERABLE_PER_SCOPE = 4
V2_UNSUPPORTED_PER_SCOPE = 4
V3_FORBIDDEN_MARKERS = ("EVAL_FACT", "HOLDOUT", "GOLD", "ANSWERABLE", "SUPPORTED")

FORBIDDEN_MARKERS = ("EVAL_FACT_", "HOLDOUT_", "GOLD_")

ANSWERABLE_CATEGORIES = frozenset(
    {
        "answerable_private_direct",
        "answerable_private_paraphrase",
        "answerable_private_numeric",
        "answerable_private_multi_chunk",
        "answerable_reference_direct",
        "answerable_reference_paraphrase",
        "answerable_reference_numeric",
        "answerable_reference_later_chunk",
        "answerable_combined_multi_source",
        "answerable_combined_private_winner",
        "answerable_combined_reference_winner",
        "answerable_combined_private_paraphrase",
    }
)
UNSUPPORTED_CATEGORIES = frozenset(
    {
        "unsupported_related_topic",
        "unsupported_wrong_fact",
        "unsupported_numeric_mismatch",
        "unsupported_semantic_distractor",
        "unsupported_specificity_mismatch",
        "unsupported_temporal_mismatch",
        "unsupported_cross_document",
        "unsupported_combined_near_miss",
    }
)
VALID_CATEGORIES = ANSWERABLE_CATEGORIES | UNSUPPORTED_CATEGORIES

_WS = re.compile(r"\s+")


def normalized_text(value: str) -> str:
    """Normalize text for exact identity comparisons (freshness checks)."""
    return _WS.sub(" ", value.strip()).lower()


def sha256_of_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def raw_bytes_sha256(path: str | Path) -> str:
    """SHA-256 over the exact file bytes as they exist on disk.

    Diagnostic only. Raw bytes are NOT the frozen-contract digest: git may
    normalize line endings between CRLF (Windows checkout) and LF (Linux
    checkout) when no ``.gitattributes`` pins ``eol``, so exact bytes are not
    portable across machines. Use :func:`canonical_dataset_digest` for the
    frozen-contract checksum.
    """
    return sha256_of_bytes(Path(path).read_bytes())


def canonical_json_digest(obj: Any) -> str:
    """SHA-256 over a deterministic canonical JSON serialization.

    Canonicalization: parsed content re-serialized with UTF-8, ``sort_keys``,
    compact separators, and stable Unicode. Whitespace and line-ending-only
    differences (LF vs CRLF) intentionally produce the SAME digest, while any
    semantic content change produces a different digest. The same function is
    used when freezing, when validating before an external run, and in tests.
    """
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_of_bytes(canonical.encode("utf-8"))


def canonical_dataset_digest(path: str | Path) -> str:
    """Canonical JSON content digest of the dataset (the frozen-contract digest).

    Line-ending-independent: an identical logical dataset hashes identically on
    any platform regardless of CRLF/LF checkout behavior. Any semantic edit to
    the dataset content changes the digest.
    """
    with open(path, encoding="utf-8") as handle:
        dataset = json.load(handle)
    return canonical_json_digest(dataset)


def load_verifier_holdout_dataset(path: str | Path) -> dict[str, Any]:
    """Load the v2 dataset and run full validation."""
    with open(path, encoding="utf-8") as handle:
        dataset = json.load(handle)
    validate_verifier_holdout_dataset(dataset)
    return dataset


def load_verifier_holdout_v3_dataset(path: str | Path) -> dict[str, Any]:
    """Load the fresh v3 dataset and run the shared strict holdout validation."""
    with open(path, encoding="utf-8") as handle:
        dataset = json.load(handle)
    validate_verifier_holdout_v3_dataset(dataset)
    return dataset


def validate_verifier_holdout_v3_dataset(dataset: dict[str, Any]) -> None:
    """Validate v3 with the proven v2 structural contract and v3 version identity."""
    if dataset.get("dataset_version") != V3_DATASET_VERSION:
        raise ValueError(f"dataset_version must be {V3_DATASET_VERSION!r}")
    structural_copy = deepcopy(dataset)
    structural_copy["dataset_version"] = V2_DATASET_VERSION
    try:
        validate_verifier_holdout_dataset(structural_copy)
    except ValueError as exc:
        raise ValueError(str(exc).replace("v2 verifier", "v3 verifier")) from exc
    semantic_ids = [
        page["semantic_id"]
        for document in collect_documents(dataset).values()
        for page in document["pages"]
    ]
    if len(semantic_ids) != len(set(semantic_ids)):
        raise ValueError("Invalid v3 verifier holdout dataset: duplicate semantic id")
    embedded_text = _embedded_text(dataset)
    for marker in V3_FORBIDDEN_MARKERS:
        if any(marker in text for text in embedded_text):
            raise ValueError(f"Invalid v3 verifier holdout dataset: forbidden marker {marker!r}")


# ---------------------------------------------------------------------------
# Structural helpers
# ---------------------------------------------------------------------------


def collect_documents(dataset: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map document key -> {kind, user, space, filename, pages} for private + reference."""
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


def collect_page_documents(documents: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Map page semantic_id -> document key."""
    page_documents: dict[str, str] = {}
    for doc_key, doc in documents.items():
        for page in doc["pages"]:
            page_documents[page["semantic_id"]] = doc_key
    return page_documents


def document_allowed_in_scope(doc: dict[str, Any], scope: str, space_key: str) -> bool:
    if scope == "private":
        return doc["kind"] == "private" and doc["space"] == space_key
    if scope == "reference":
        return doc["kind"] == "reference"
    return doc["kind"] == "reference" or (doc["kind"] == "private" and doc["space"] == space_key)


def validate_verifier_holdout_dataset(dataset: dict[str, Any]) -> None:
    """Raise ValueError with all structural/isolation violations if invalid."""
    errors: list[str] = []

    if dataset.get("dataset_version") != V2_DATASET_VERSION:
        errors.append(f"dataset_version must be {V2_DATASET_VERSION!r}")
    if not isinstance(dataset.get("purpose"), str) or not dataset["purpose"]:
        errors.append("purpose must be a non-empty string")
    if not isinstance(dataset.get("description"), str) or not dataset["description"]:
        errors.append("description must be a non-empty string")

    if "users" not in dataset or not dataset["users"]:
        errors.append("dataset must define at least one user")
    if "reference_documents" not in dataset or not dataset["reference_documents"]:
        errors.append("dataset must define at least one reference document")
    if "queries" not in dataset or not dataset["queries"]:
        errors.append("dataset must define at least one query")

    documents = collect_documents(dataset)
    page_documents = collect_page_documents(documents)

    seen_user_keys: set[str] = set()
    for user_key, user in dataset["users"].items():
        if user_key in seen_user_keys:
            errors.append(f"duplicate user key {user_key!r}")
        seen_user_keys.add(user_key)
        spaces = user.get("spaces", {})
        if not spaces:
            errors.append(f"user {user_key} has no spaces")
        for space_key, space in spaces.items():
            if not space.get("documents"):
                errors.append(f"space {space_key} has no documents")
            for doc_key, doc in space["documents"].items():
                if not doc.get("pages"):
                    errors.append(f"document {doc_key} has no pages")
                for page in doc["pages"]:
                    _validate_page(page, doc_key, errors, page_documents)

    for doc_key, doc in dataset["reference_documents"].items():
        if not doc.get("pages"):
            errors.append(f"reference document {doc_key} has no pages")
        for page in doc["pages"]:
            _validate_page(page, doc_key, errors, page_documents)

    seen_queries: set[str] = set()
    counts = {"answerable": 0, "unanswerable": 0}
    scope_counts: dict[str, dict[str, int]] = {
        scope: {"answerable": 0, "unanswerable": 0} for scope in VALID_SCOPES
    }

    for index, query in enumerate(dataset["queries"]):
        prefix = f"query[{index}]"
        query_id = query.get("id")
        if not isinstance(query_id, str) or not query_id:
            errors.append(f"{prefix}: missing id")
            continue
        if query_id in seen_queries:
            errors.append(f"{prefix}: duplicate query id {query_id!r}")
        seen_queries.add(query_id)

        scope = query.get("scope")
        if scope not in VALID_SCOPES:
            errors.append(f"{prefix} {query_id}: invalid scope {scope!r}")

        answerable = query.get("answerable")
        if not isinstance(answerable, bool):
            errors.append(f"{prefix} {query_id}: answerable must be boolean")
            answerable = False

        category = query.get("category")
        if category not in VALID_CATEGORIES:
            errors.append(f"{prefix} {query_id}: invalid category {category!r}")
        else:
            expected_answerable = category in ANSWERABLE_CATEGORIES
            if answerable != expected_answerable:
                errors.append(
                    f"{prefix} {query_id}: category {category!r} answerability "
                    f"({expected_answerable}) conflicts with answerable={answerable}"
                )

        question = query.get("question")
        if not isinstance(question, str) or not question.strip():
            errors.append(f"{prefix} {query_id}: missing question")

        split = query.get("evaluation_split")
        if split != V2_SPLIT:
            errors.append(f"{prefix} {query_id}: evaluation_split must be {V2_SPLIT!r}")

        space = query.get("space")
        space_exists = any(space in user.get("spaces", {}) for user in dataset["users"].values())
        if not space_exists:
            errors.append(f"{prefix} {query_id}: unknown space {space!r}")

        expected_chunks = query.get("expected_relevant_chunks") or []
        expected_docs = query.get("expected_relevant_documents") or []
        forbidden = query.get("forbidden_documents") or []
        kinds = query.get("expected_source_kinds") or []
        for field in (
            "expected_relevant_chunks",
            "expected_relevant_documents",
            "forbidden_documents",
        ):
            if not isinstance(query.get(field) or [], list):
                errors.append(f"{prefix} {query_id}: {field} must be a list")

        if answerable and not expected_chunks:
            errors.append(f"{prefix} {query_id}: answerable query has no relevant chunks")
        if not answerable and expected_chunks:
            errors.append(f"{prefix} {query_id}: unsupported query lists relevant chunks")
        if not answerable and (expected_docs or kinds):
            errors.append(
                f"{prefix} {query_id}: unsupported query must not list "
                "expected docs or source kinds"
            )

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

        for kind in kinds:
            if kind not in {"private", "reference"}:
                errors.append(f"{prefix} {query_id}: invalid expected source kind {kind!r}")

        if answerable and scope in ("private", "reference"):
            expected_kind = scope
            if kinds and set(kinds) != {expected_kind}:
                errors.append(
                    f"{prefix} {query_id}: expected source kinds for {scope} scope must be "
                    f"[{expected_kind!r}]"
                )
        if answerable and scope == "combined":
            if not kinds:
                errors.append(
                    f"{prefix} {query_id}: combined answerable query must list source kinds"
                )
            elif not set(kinds) <= {"private", "reference"}:
                errors.append(
                    f"{prefix} {query_id}: combined source kinds must be private/reference"
                )
            if category == "answerable_combined_multi_source" and set(kinds) != {
                "private",
                "reference",
            }:
                errors.append(f"{prefix} {query_id}: combined_multi_source needs both source kinds")

        for doc_key in expected_docs:
            doc = documents.get(doc_key)
            if doc is None:
                continue
            if not document_allowed_in_scope(doc, scope, space):
                errors.append(
                    f"{prefix} {query_id}: expected document {doc_key!r} is not available "
                    f"in {scope} scope for space {space!r}"
                )

        for chunk in expected_chunks:
            doc_key = page_documents.get(chunk)
            doc = documents.get(doc_key) if doc_key else None
            if doc is None:
                continue
            if not document_allowed_in_scope(doc, scope, space):
                errors.append(
                    f"{prefix} {query_id}: expected chunk {chunk!r} belongs to a document "
                    f"({doc_key!r}) not available in {scope} scope"
                )
            if doc_key in set(forbidden):
                errors.append(
                    f"{prefix} {query_id}: relevant chunk {chunk!r} belongs to a forbidden document"
                )

        if answerable:
            counts["answerable"] += 1
        else:
            counts["unanswerable"] += 1
        if scope in scope_counts:
            scope_counts[scope]["answerable" if answerable else "unanswerable"] += 1

    if counts["answerable"] != V2_ANSWERABLE_COUNT:
        errors.append(
            f"expected {V2_ANSWERABLE_COUNT} answerable queries, got {counts['answerable']}"
        )
    if counts["unanswerable"] != V2_UNSUPPORTED_COUNT:
        errors.append(
            f"expected {V2_UNSUPPORTED_COUNT} unsupported queries, got {counts['unanswerable']}"
        )
    for scope, expected in V2_SCOPE_COUNTS.items():
        actual = scope_counts[scope]["answerable"] + scope_counts[scope]["unanswerable"]
        if actual != expected:
            errors.append(f"scope {scope}: expected {expected} queries, got {actual}")
        if scope_counts[scope]["answerable"] != V2_ANSWERABLE_PER_SCOPE:
            errors.append(
                f"scope {scope}: expected {V2_ANSWERABLE_PER_SCOPE} answerable queries, "
                f"got {scope_counts[scope]['answerable']}"
            )
        if scope_counts[scope]["unanswerable"] != V2_UNSUPPORTED_PER_SCOPE:
            errors.append(
                f"scope {scope}: expected {V2_UNSUPPORTED_PER_SCOPE} unsupported queries, "
                f"got {scope_counts[scope]['unanswerable']}"
            )

    _check_markers(dataset, errors)
    if errors:
        raise ValueError("Invalid v2 verifier holdout dataset:\n- " + "\n- ".join(errors))


def _validate_page(
    page: Any, doc_key: str, errors: list[str], page_documents: dict[str, str]
) -> None:
    if not isinstance(page, dict) or not isinstance(page.get("semantic_id"), str):
        errors.append(f"document {doc_key} has a page without a semantic_id")
        return
    if not isinstance(page.get("text"), str) or not page["text"].strip():
        errors.append(f"document {doc_key} page {page['semantic_id']} has empty text")
    semantic_id = page["semantic_id"]
    if semantic_id in page_documents and page_documents[semantic_id] != doc_key:
        errors.append(f"semantic page id {semantic_id} appears in more than one document")
    page_documents[semantic_id] = doc_key


def _check_markers(dataset: dict[str, Any], errors: list[str]) -> None:
    """Reject evaluation marker tokens in any embedded text or question."""
    texts = _embedded_text(dataset)
    for marker in FORBIDDEN_MARKERS:
        for text in texts:
            if marker in text:
                errors.append(f"forbidden marker {marker!r} found in embedded content")


def _embedded_text(dataset: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for user in dataset["users"].values():
        for space in user.get("spaces", {}).values():
            for doc in space.get("documents", {}).values():
                for page in doc.get("pages", []):
                    texts.append(page.get("text", ""))
    for doc in dataset["reference_documents"].values():
        for page in doc.get("pages", []):
            texts.append(page.get("text", ""))
    for query in dataset["queries"]:
        texts.append(query.get("question", ""))
    return texts


# ---------------------------------------------------------------------------
# Freshness (v1 identity isolation)
# ---------------------------------------------------------------------------


def collect_v1_identities(dataset: dict[str, Any]) -> dict[str, set[str]]:
    """Collect the identity namespaces of a v1-style dataset for freshness checks."""
    questions = {normalized_text(q["question"]) for q in dataset["queries"]}
    page_ids: set[str] = set()
    document_ids: set[str] = set()
    user_ids: set[str] = set()
    page_texts: set[str] = set()
    for user_key, user in dataset["users"].items():
        user_ids.add(user_key)
        for space_key, space in user["spaces"].items():
            for doc_key, doc in space["documents"].items():
                document_ids.add(doc_key)
                for page in doc["pages"]:
                    page_ids.add(page["semantic_id"])
                    page_texts.add(normalized_text(page["text"]))
    for doc_key, doc in dataset["reference_documents"].items():
        document_ids.add(doc_key)
        for page in doc["pages"]:
            page_ids.add(page["semantic_id"])
            page_texts.add(normalized_text(page["text"]))
    return {
        "questions": questions,
        "page_ids": page_ids,
        "document_ids": document_ids,
        "user_ids": user_ids,
        "page_texts": page_texts,
    }


def freshness_errors(v2_dataset: dict[str, Any], v1_dataset: dict[str, Any]) -> list[str]:
    """Identity-freshness violations of v2 relative to v1 (exact normalized checks only)."""
    errors: list[str] = []
    v2_ids = collect_v1_identities(v2_dataset)
    v1_ids = collect_v1_identities(v1_dataset)

    shared_questions = v2_ids["questions"] & v1_ids["questions"]
    if shared_questions:
        errors.append(f"v2 reuses exact v1 question(s): {sorted(shared_questions)}")

    shared_pages = v2_ids["page_ids"] & v1_ids["page_ids"]
    if shared_pages:
        errors.append(f"v2 reuses v1 page semantic id(s): {sorted(shared_pages)}")

    shared_docs = v2_ids["document_ids"] & v1_ids["document_ids"]
    if shared_docs:
        errors.append(f"v2 reuses v1 fixture document id(s): {sorted(shared_docs)}")

    shared_users = v2_ids["user_ids"] & v1_ids["user_ids"]
    if shared_users:
        errors.append(f"v2 reuses v1 user fixture id(s): {sorted(shared_users)}")

    shared_text = v2_ids["page_texts"] & v1_ids["page_texts"]
    if shared_text:
        errors.append(f"v2 reuses exact v1 page text (first: {sorted(shared_text)[0]!r})")
    return errors


def dataset_summary(dataset: dict[str, Any]) -> dict[str, Any]:
    """Summary counts for the committed v2 dataset (also used by tests)."""
    documents = collect_documents(dataset)
    page_ids: list[str] = []
    for doc in documents.values():
        page_ids.extend(page["semantic_id"] for page in doc["pages"])
    answerable = sum(1 for q in dataset["queries"] if q["answerable"])
    categories: dict[str, int] = {}
    scopes: dict[str, int] = {}
    for query in dataset["queries"]:
        categories[query["category"]] = categories.get(query["category"], 0) + 1
        scopes[query["scope"]] = scopes.get(query["scope"], 0) + 1
    return {
        "dataset_version": dataset["dataset_version"],
        "split": dataset.get("split"),
        "users": len(dataset["users"]),
        "private_spaces": sum(len(user.get("spaces", {})) for user in dataset["users"].values()),
        "private_documents": sum(1 for d in documents.values() if d["kind"] == "private"),
        "reference_documents": sum(1 for d in documents.values() if d["kind"] == "reference"),
        "total_pages": len(page_ids),
        "queries": len(dataset["queries"]),
        "answerable": answerable,
        "unanswerable": len(dataset["queries"]) - answerable,
        "categories": categories,
        "scopes": scopes,
    }
