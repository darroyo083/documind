"""Benchmark runner.

Builds a synthetic corpus through the real ingestion/import paths, then
exercises the production retrieval service directly (no answer provider, no
LLM) and evaluates retrieval candidates against explicit ground truth.

Higher score means more similar (score = 1 - cosine_distance). Candidate order
returned by ``retrieve_chunks`` is the ranking used here.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, cast

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.documents import ingest_document
from app.application.reference import import_reference_document
from app.application.retrieval import retrieve_chunks
from app.config import settings
from app.domain.rag import EmbeddingProvider, KnowledgeScope
from app.evaluation import metrics
from app.infrastructure.models import (
    Document,
    DocumentChunk,
    KnowledgeSpace,
    ReferenceDocument,
    ReferenceDocumentChunk,
    User,
)


@dataclass
class DocRecord:
    semantic_id: str
    kind: str
    database_id: str
    name: str
    space_key: str | None
    user_key: str | None


@dataclass
class Corpus:
    dataset_version: str
    user_ids: dict[str, str] = field(default_factory=dict)
    space_ids: dict[str, str] = field(default_factory=dict)
    space_users: dict[str, str] = field(default_factory=dict)
    documents: dict[str, DocRecord] = field(default_factory=dict)
    document_pages: dict[str, list[dict]] = field(default_factory=dict)
    page_chunks: dict[str, list[str]] = field(default_factory=dict)
    chunk_to_pages: dict[str, list[str]] = field(default_factory=dict)
    document_id_to_semantic: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)


@dataclass
class QueryResult:
    id: str
    scope: str
    category: str
    space: str
    answerable: bool
    question: str
    expected_chunks: list[str]
    expected_documents: list[str]
    forbidden_documents: list[str]
    required_source_kinds: list[str]
    relevant_ranks: list[int]
    document_relevant_ranks: list[int]
    first_relevant_rank: int | None
    retrieval_count: int
    candidate_documents: list[str]
    candidate_kinds: list[str]
    candidate_scores: list[float]
    candidate_relevant: list[bool]
    candidate_forbidden: list[bool]
    forbidden_retrieved: list[str]
    scope_violations: list[str]
    source_kinds_present: list[str]
    has_cross_user_forbidden: bool = False
    has_cross_space_forbidden: bool = False


@dataclass
class EvaluationResults:
    top_k: int
    threshold: float
    results: list[QueryResult]
    metrics: dict[str, Any]


class _PdfUpload:
    """Minimal UploadFile stand-in accepted by ``ingest_document``."""

    def __init__(self, data: bytes, filename: str):
        self._data = data
        self.filename = filename
        self.content_type = "application/pdf"

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._data)
        chunk, self._data = self._data[:size], self._data[size:]
        return chunk


@contextmanager
def threshold_override(value: float):
    """Temporarily override the retrieval similarity threshold for a sweep."""
    original = settings.default_similarity_threshold
    settings.default_similarity_threshold = value
    try:
        yield
    finally:
        settings.default_similarity_threshold = original


async def build_corpus(
    db: AsyncSession,
    dataset: dict[str, Any],
    embedding_provider: EmbeddingProvider,
    storage,
    tmp_dir,
) -> Corpus:
    """Persist the synthetic corpus using the real ingestion/import paths."""
    from tests.pdf_factory import page_pdf

    corpus = Corpus(dataset_version=dataset["dataset_version"])

    for user_key, user in dataset["users"].items():
        existing = await db.scalar(select(User).where(User.email == user["email"]))
        if existing is None:
            record = User(
                email=user["email"],
                hashed_password="not-used-by-evaluator",
                display_name=user["display_name"],
            )
            db.add(record)
            await db.commit()
            await db.refresh(record)
            existing = record
        corpus.user_ids[user_key] = str(existing.id)

    for user_key, user in dataset["users"].items():
        user_id = corpus.user_ids[user_key]
        for space_key, space in user["spaces"].items():
            space_id = corpus.space_ids.get(space_key)
            if space_id is None:
                space_record = KnowledgeSpace(user_id=uuid.UUID(user_id), name=space["name"])
                db.add(space_record)
                await db.commit()
                await db.refresh(space_record)
                space_id = str(space_record.id)
            corpus.space_ids[space_key] = space_id
            corpus.space_users[space_key] = user_key
            for doc_key, doc in space["documents"].items():
                pdf_bytes = page_pdf([page["text"] for page in doc["pages"]])
                upload = cast(UploadFile, _PdfUpload(pdf_bytes, doc["filename"]))
                ingested = await ingest_document(
                    db, uuid.UUID(space_id), upload, storage, embedding_provider
                )
                corpus.documents[doc_key] = DocRecord(
                    semantic_id=doc_key,
                    kind="private",
                    database_id=str(ingested.id),
                    name=doc["filename"],
                    space_key=space_key,
                    user_key=user_key,
                )
                corpus.document_pages[doc_key] = doc["pages"]

    for doc_key, doc in dataset["reference_documents"].items():
        pdf_bytes = page_pdf([page["text"] for page in doc["pages"]])
        path = tmp_dir / doc["filename"]
        path.write_bytes(pdf_bytes)
        imported, _ = await import_reference_document(db, path, doc["title"], embedding_provider)
        corpus.documents[doc_key] = DocRecord(
            semantic_id=doc_key,
            kind="reference",
            database_id=str(imported.id),
            name=doc["title"],
            space_key=None,
            user_key=None,
        )
        corpus.document_pages[doc_key] = doc["pages"]

    for doc in corpus.documents.values():
        corpus.document_id_to_semantic[doc.database_id] = doc.semantic_id

    private_rows = (
        await db.execute(
            select(DocumentChunk, Document).join(Document, DocumentChunk.document_id == Document.id)
        )
    ).all()
    for chunk, document in private_rows:
        _register_document_chunks(corpus, chunk, str(document.id))

    reference_rows = (
        await db.execute(
            select(ReferenceDocumentChunk, ReferenceDocument).join(
                ReferenceDocument,
                ReferenceDocumentChunk.reference_document_id == ReferenceDocument.id,
            )
        )
    ).all()
    for chunk, reference_document in reference_rows:
        _register_document_chunks(corpus, chunk, str(reference_document.id))

    corpus.counts = {
        "private_documents": sum(1 for doc in corpus.documents.values() if doc.kind == "private"),
        "reference_documents": sum(
            1 for doc in corpus.documents.values() if doc.kind == "reference"
        ),
        "chunks": len(corpus.chunk_to_pages),
        "pages": sum(len(pages) for pages in corpus.document_pages.values()),
    }
    return corpus


def _register_document_chunks(corpus: Corpus, chunk, database_document_id: str) -> None:
    """Map a produced chunk to the semantic page id(s) of its source page.

    Each chunk records the 1-based page number it came from; the fixture page
    at that position carries the stable semantic id. This keeps evaluation
    identifiers OUT of the embedded text.
    """
    semantic_doc = corpus.document_id_to_semantic.get(database_document_id)
    pages = corpus.document_pages.get(semantic_doc) if semantic_doc else None
    if pages is None:
        return
    page_index = chunk.page_number - 1
    if page_index < 0 or page_index >= len(pages):
        return
    semantic_id = pages[page_index].get("semantic_id")
    if not semantic_id:
        return
    chunk_id = str(chunk.id)
    corpus.page_chunks.setdefault(semantic_id, []).append(chunk_id)
    corpus.chunk_to_pages.setdefault(chunk_id, []).append(semantic_id)


def _allowed_semantic_docs(corpus: Corpus, query: dict[str, Any]) -> set[str]:
    space_key = query["space"]
    scope = query["scope"]
    if scope == "private":
        return {
            semantic_id
            for semantic_id, doc in corpus.documents.items()
            if doc.space_key == space_key
        }
    if scope == "reference":
        return {
            semantic_id for semantic_id, doc in corpus.documents.items() if doc.kind == "reference"
        }
    requested_space = {
        semantic_id for semantic_id, doc in corpus.documents.items() if doc.space_key == space_key
    }
    reference = {
        semantic_id for semantic_id, doc in corpus.documents.items() if doc.kind == "reference"
    }
    return requested_space | reference


async def run_query(
    db: AsyncSession,
    corpus: Corpus,
    query: dict[str, Any],
    embedding_provider: EmbeddingProvider,
    top_k: int,
    threshold: float,
) -> QueryResult:
    space_key = query["space"]
    user_key = corpus.space_users[space_key]
    user_id = corpus.user_ids[user_key]
    space_id = corpus.space_ids[space_key]
    scope = KnowledgeScope(query["scope"])
    expected_chunks = set(query.get("expected_relevant_chunks") or [])
    expected_documents = set(query.get("expected_relevant_documents") or [])
    forbidden_documents = set(query.get("forbidden_documents") or [])
    required_kinds = set(query.get("expected_source_kinds") or [])
    if not required_kinds:
        required_kinds = (
            {query["scope"]} if query["scope"] != "combined" else {"private", "reference"}
        )
    allowed_docs = _allowed_semantic_docs(corpus, query)

    has_cross_user_forbidden = False
    has_cross_space_forbidden = False
    for forbidden in forbidden_documents:
        doc = corpus.documents.get(forbidden)
        if doc is None or doc.kind == "reference":
            continue
        if doc.user_key != user_key:
            has_cross_user_forbidden = True
        elif doc.space_key != space_key:
            has_cross_space_forbidden = True

    with threshold_override(threshold):
        candidates = await retrieve_chunks(
            db,
            uuid.UUID(space_id),
            uuid.UUID(user_id),
            query["question"],
            top_k,
            embedding_provider,
            scope,
        )

    relevant_ranks: list[int] = []
    document_relevant_ranks: list[int] = []
    forbidden_retrieved: list[str] = []
    scope_violations: list[str] = []
    candidate_documents: list[str] = []
    candidate_kinds: list[str] = []
    candidate_scores: list[float] = []
    candidate_relevant: list[bool] = []
    candidate_forbidden: list[bool] = []
    kinds_present: set[str] = set()

    for rank, candidate in enumerate(candidates, start=1):
        semantic_doc = corpus.document_id_to_semantic.get(
            candidate.document_id, candidate.document_id
        )
        candidate_documents.append(semantic_doc)
        candidate_kinds.append(candidate.source_kind)
        candidate_scores.append(round(candidate.score, 4))
        kinds_present.add(candidate.source_kind)

        is_relevant = False
        chunk_pages = corpus.chunk_to_pages.get(candidate.chunk_id, [])
        if any(page_id in expected_chunks for page_id in chunk_pages):
            is_relevant = True
            relevant_ranks.append(rank)
        candidate_relevant.append(is_relevant)

        is_forbidden = semantic_doc in forbidden_documents
        candidate_forbidden.append(is_forbidden)
        if is_forbidden:
            forbidden_retrieved.append(semantic_doc)
        if semantic_doc not in allowed_docs:
            scope_violations.append(semantic_doc)
        if semantic_doc in expected_documents:
            document_relevant_ranks.append(rank)

    return QueryResult(
        id=query["id"],
        scope=query["scope"],
        category=query["category"],
        space=space_key,
        answerable=query["answerable"],
        question=query["question"],
        expected_chunks=sorted(expected_chunks),
        expected_documents=sorted(expected_documents),
        forbidden_documents=sorted(forbidden_documents),
        required_source_kinds=sorted(required_kinds),
        relevant_ranks=relevant_ranks,
        document_relevant_ranks=document_relevant_ranks,
        first_relevant_rank=relevant_ranks[0] if relevant_ranks else None,
        retrieval_count=len(candidates),
        candidate_documents=candidate_documents,
        candidate_kinds=candidate_kinds,
        candidate_scores=candidate_scores,
        candidate_relevant=candidate_relevant,
        candidate_forbidden=candidate_forbidden,
        forbidden_retrieved=forbidden_retrieved,
        scope_violations=scope_violations,
        source_kinds_present=sorted(kinds_present),
        has_cross_user_forbidden=has_cross_user_forbidden,
        has_cross_space_forbidden=has_cross_space_forbidden,
    )


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _relevant_total(results: list[QueryResult]) -> int:
    return sum(len(r.expected_chunks) for r in results if r.answerable)


def summarize_results(results: list[QueryResult]) -> dict[str, Any]:
    """Baseline metrics at fixed K = 1/3/5 (context capped by the run's top_k)."""
    answerable = [r for r in results if r.answerable]
    unanswerable = [r for r in results if not r.answerable]
    leaked_queries = [r for r in results if r.forbidden_retrieved]
    scope_violations = [r for r in results if r.scope_violations]

    hit1 = _mean([float(metrics.hit_at_k(r.relevant_ranks, 1)) for r in answerable])
    hit3 = _mean([float(metrics.hit_at_k(r.relevant_ranks, 3)) for r in answerable])
    hit5 = _mean([float(metrics.hit_at_k(r.relevant_ranks, 5)) for r in answerable])
    recall1 = _mean(
        [metrics.recall_at_k(r.relevant_ranks, 1, len(r.expected_chunks)) for r in answerable]
    )
    recall3 = _mean(
        [metrics.recall_at_k(r.relevant_ranks, 3, len(r.expected_chunks)) for r in answerable]
    )
    recall5 = _mean(
        [metrics.recall_at_k(r.relevant_ranks, 5, len(r.expected_chunks)) for r in answerable]
    )
    mrr = _mean([metrics.mean_reciprocal_rank(r.relevant_ranks) for r in answerable])
    doc_hit5 = _mean(
        [float(metrics.document_hit_at_k(r.document_relevant_ranks, 5)) for r in answerable]
    )

    answerable_candidates = [r.retrieval_count for r in answerable]
    unanswerable_candidates = [r.retrieval_count for r in unanswerable]

    return {
        "query_count": len(results),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "total_relevant_chunks": _relevant_total(results),
        "hit_at_1": hit1,
        "hit_at_3": hit3,
        "hit_at_5": hit5,
        "recall_at_1": recall1,
        "recall_at_3": recall3,
        "recall_at_5": recall5,
        "mrr": mrr,
        "document_hit_at_5": doc_hit5,
        "unanswerable_rejection_rate": metrics.unanswerable_rejection_rate(
            [r.retrieval_count == 0 for r in unanswerable]
        ),
        "unanswerable_false_positives": sum(1 for r in unanswerable if r.retrieval_count > 0),
        "average_candidate_count_answerable": _mean([float(v) for v in answerable_candidates]),
        "average_candidate_count_unanswerable": _mean([float(v) for v in unanswerable_candidates]),
        "leaked_queries": len(leaked_queries),
        "scope_violations": len(scope_violations),
    }


def sweep_row(results: list[QueryResult], top_k: int) -> dict[str, Any]:
    """Sweep-row metrics evaluated at the row's own context window (top_k)."""
    answerable = [r for r in results if r.answerable]
    unanswerable = [r for r in results if not r.answerable]
    return {
        "query_count": len(results),
        "top_k": top_k,
        "hit_at_k": _mean([float(metrics.hit_at_k(r.relevant_ranks, top_k)) for r in answerable]),
        "recall_at_k": _mean(
            [
                metrics.recall_at_k(r.relevant_ranks, top_k, len(r.expected_chunks))
                for r in answerable
            ]
        ),
        "mrr": _mean([metrics.mean_reciprocal_rank(r.relevant_ranks) for r in answerable]),
        "unanswerable_rejection_rate": metrics.unanswerable_rejection_rate(
            [r.retrieval_count == 0 for r in unanswerable]
        ),
        "unanswerable_false_positives": sum(1 for r in unanswerable if r.retrieval_count > 0),
        "average_candidate_count_answerable": _mean([float(r.retrieval_count) for r in answerable]),
        "average_candidate_count_unanswerable": _mean(
            [float(r.retrieval_count) for r in unanswerable]
        ),
        "leaked_queries": sum(1 for r in results if r.forbidden_retrieved),
        "scope_violations": sum(1 for r in results if r.scope_violations),
    }


def compute_metrics(results: list[QueryResult]) -> dict[str, Any]:
    groups: dict[str, list[QueryResult]] = {"overall": results}
    for scope in ("private", "reference", "combined"):
        groups[scope] = [r for r in results if r.scope == scope]
    for category in sorted({r.category for r in results}):
        groups[f"category:{category}"] = [r for r in results if r.category == category]

    grouped: dict[str, Any] = {}
    for group_name, group_results in groups.items():
        if group_results:
            grouped[group_name] = summarize_results(group_results)

    security = {
        "cross_user_tested": sum(1 for r in results if r.has_cross_user_forbidden),
        "cross_user_leaked": sum(
            1 for r in results if r.has_cross_user_forbidden and r.forbidden_retrieved
        ),
        "cross_space_tested": sum(1 for r in results if r.has_cross_space_forbidden),
        "cross_space_leaked": sum(
            1 for r in results if r.has_cross_space_forbidden and r.forbidden_retrieved
        ),
        "scope_violations": [r.id for r in results if r.scope_violations],
    }
    security["cross_user_leakage_rate"] = metrics.leakage_rate(
        [r.has_cross_user_forbidden and bool(r.forbidden_retrieved) for r in results]
        if security["cross_user_tested"]
        else []
    )
    security["cross_space_leakage_rate"] = metrics.leakage_rate(
        [r.has_cross_space_forbidden and bool(r.forbidden_retrieved) for r in results]
        if security["cross_space_tested"]
        else []
    )

    multi_source = [r for r in results if set(r.required_source_kinds) == {"private", "reference"}]
    security["combined_source_coverage"] = metrics.combined_source_coverage(
        [set(r.source_kinds_present) for r in multi_source],
        {"private", "reference"},
    )
    grouped["security"] = security

    relevant_scores = [
        score
        for r in results
        for score, relevant in zip(r.candidate_scores, r.candidate_relevant, strict=True)
        if relevant
    ]
    irrelevant_scores = [
        score
        for r in results
        for score, relevant in zip(r.candidate_scores, r.candidate_relevant, strict=True)
        if not relevant
    ]
    unanswerable_top_scores = [
        max(r.candidate_scores) for r in results if not r.answerable and r.candidate_scores
    ]
    grouped["score_distributions"] = {
        "relevant": metrics.score_statistics(relevant_scores),
        "irrelevant": metrics.score_statistics(irrelevant_scores),
        "unanswerable_top": metrics.score_statistics(unanswerable_top_scores),
    }
    return grouped


async def run_evaluation(
    db: AsyncSession,
    corpus: Corpus,
    dataset: dict[str, Any],
    embedding_provider: EmbeddingProvider,
    top_k: int,
    threshold: float,
) -> EvaluationResults:
    queries = sorted(dataset["queries"], key=lambda q: q["id"])
    results = [
        await run_query(db, corpus, query, embedding_provider, top_k, threshold)
        for query in queries
    ]
    return EvaluationResults(
        top_k=top_k,
        threshold=threshold,
        results=results,
        metrics=compute_metrics(results),
    )


async def run_top_k_sweep(
    db: AsyncSession,
    corpus: Corpus,
    dataset: dict[str, Any],
    embedding_provider: EmbeddingProvider,
    threshold: float,
    values: list[int],
) -> list[dict[str, Any]]:
    sweep = []
    for top_k in values:
        evaluation = await run_evaluation(db, corpus, dataset, embedding_provider, top_k, threshold)
        sweep.append(sweep_row(evaluation.results, top_k))
    return sweep


async def run_threshold_sweep(
    db: AsyncSession,
    corpus: Corpus,
    dataset: dict[str, Any],
    embedding_provider: EmbeddingProvider,
    top_k: int,
    values: list[float],
) -> list[dict[str, Any]]:
    sweep = []
    for threshold in values:
        evaluation = await run_evaluation(db, corpus, dataset, embedding_provider, top_k, threshold)
        summary = sweep_row(evaluation.results, top_k)
        summary["threshold"] = threshold
        sweep.append(summary)
    return sweep


def hard_invariants(results: list[QueryResult]) -> list[str]:
    """Any non-empty entry is a hard failure (exit non-zero)."""
    failures: list[str] = []
    for result in results:
        if result.scope_violations:
            failures.append(f"{result.id}: scope violation candidates {result.scope_violations}")
        if result.forbidden_retrieved:
            failures.append(
                f"{result.id}: forbidden candidates retrieved {result.forbidden_retrieved}"
            )
    return failures
