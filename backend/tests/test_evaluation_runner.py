"""Integration tests for the evaluation runner over the committed dataset."""

import inspect
import json
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.evaluation import dataset as ds
from app.evaluation import reporting, runner
from app.infrastructure.models import ReferenceDocument, User
from app.infrastructure.providers import DeterministicEmbeddingProvider
from app.infrastructure.storage import LocalDocumentStorage

DATASET_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "evaluation" / "datasets" / "retrieval_v1.json"
)
EMBEDDING = DeterministicEmbeddingProvider(384)


async def _build_and_run(db_session: AsyncSession, tmp_path):
    dataset_data = ds.load_dataset(DATASET_PATH)
    storage = LocalDocumentStorage(tmp_path / "uploads")
    corpus = await runner.build_corpus(db_session, dataset_data, EMBEDDING, storage, tmp_path)
    baseline = await runner.run_evaluation(
        db_session, corpus, dataset_data, EMBEDDING, top_k=5, threshold=0.2
    )
    return dataset_data, corpus, baseline


async def _cleanup(db_session: AsyncSession):
    await db_session.execute(
        delete(User).where(User.email.in_(["eval-user-a@example.com", "eval-user-b@example.com"]))
    )
    await db_session.execute(delete(ReferenceDocument))
    await db_session.commit()


@pytest.mark.asyncio
async def test_committed_corpus_builds_and_runs_without_invariants(
    db_session: AsyncSession, tmp_path
):
    try:
        dataset_data, corpus, baseline = await _build_and_run(db_session, tmp_path)
        assert corpus.counts["private_documents"] == 8
        assert corpus.counts["reference_documents"] == 3
        assert corpus.counts["chunks"] == len(corpus.chunk_to_pages)
        assert corpus.counts["pages"] == 21

        failures = runner.hard_invariants(baseline.results)
        assert failures == []
        assert baseline.metrics["security"]["scope_violations"] == []
        assert baseline.metrics["security"]["cross_user_leaked"] == 0
        assert baseline.metrics["security"]["cross_space_leaked"] == 0
        assert baseline.metrics["overall"]["query_count"] == len(dataset_data["queries"])
        assert baseline.metrics["overall"]["answerable"] == 34
        assert baseline.metrics["overall"]["unanswerable"] == 9
    finally:
        await _cleanup(db_session)


@pytest.mark.asyncio
async def test_persisted_chunks_contain_no_evaluation_markers(db_session: AsyncSession, tmp_path):
    from sqlalchemy import select as sa_select

    from app.infrastructure.models import DocumentChunk, ReferenceDocumentChunk

    try:
        dataset_data, corpus, _ = await _build_and_run(db_session, tmp_path)
        private_contents = list(
            (await db_session.execute(sa_select(DocumentChunk.content))).scalars()
        )
        reference_contents = list(
            (await db_session.execute(sa_select(ReferenceDocumentChunk.content))).scalars()
        )
        for content in [*private_contents, *reference_contents]:
            assert "EVAL_FACT_" not in content
    finally:
        await _cleanup(db_session)


@pytest.mark.asyncio
async def test_runner_exercises_production_retrieval_and_reports_scores(
    db_session: AsyncSession, tmp_path
):
    try:
        dataset_data, corpus, baseline = await _build_and_run(db_session, tmp_path)
        for result in baseline.results:
            scores = result.candidate_scores
            assert scores == sorted(scores, reverse=True), "scores must be ranked best-first"
            for candidate_doc, kind in zip(
                result.candidate_documents, result.candidate_kinds, strict=True
            ):
                doc = corpus.documents[candidate_doc]
                assert kind == doc.kind, "source_kind must match database origin"
        for page_id, chunk_ids in corpus.page_chunks.items():
            assert page_id.startswith(("private_", "reference_", "user_b_"))
            assert chunk_ids
    finally:
        await _cleanup(db_session)


@pytest.mark.asyncio
async def test_report_json_is_deterministic(db_session: AsyncSession, tmp_path):
    try:
        dataset_data, corpus, baseline = await _build_and_run(db_session, tmp_path)
        report = reporting.build_json_report(
            dataset_version=dataset_data["dataset_version"],
            embedding_provider="mock",
            embedding_model="deterministic-test",
            embedding_dimension=384,
            top_k=5,
            threshold=0.2,
            corpus_counts=corpus.counts,
            evaluation=baseline,
            top_k_sweep=None,
            threshold_sweep=None,
            runtime_seconds=1.0,
            git_commit=None,
        )
        assert [query["id"] for query in report["queries"]] == sorted(
            query["id"] for query in report["queries"]
        )
        assert all("question" in query for query in report["queries"])
        first = json.dumps(report, sort_keys=True, ensure_ascii=False)
        second = json.dumps(report, sort_keys=True, ensure_ascii=False)
        assert first == second
        markdown = reporting.render_markdown(report)
        assert "# DocuMind Retrieval Benchmark" in markdown
        assert "Failed answerable retrievals" in markdown
        assert "Recall@1" in markdown
    finally:
        await _cleanup(db_session)


def test_evaluation_does_not_require_answer_provider():
    source = inspect.getsource(runner)
    assert "answer_question" not in source
    assert "get_answer_provider" not in source
    assert "AnswerProvider" not in source


@pytest.mark.asyncio
async def test_sweeps_run_over_committed_dataset(db_session: AsyncSession, tmp_path):
    try:
        dataset_data, corpus, _ = await _build_and_run(db_session, tmp_path)
        top_k_sweep = await runner.run_top_k_sweep(
            db_session, corpus, dataset_data, EMBEDDING, 0.2, [1, 3, 5]
        )
        assert [row["top_k"] for row in top_k_sweep] == [1, 3, 5]
        threshold_sweep = await runner.run_threshold_sweep(
            db_session, corpus, dataset_data, EMBEDDING, 5, [0.1, 0.3]
        )
        assert [row["threshold"] for row in threshold_sweep] == [0.1, 0.3]
    finally:
        await _cleanup(db_session)


@pytest.mark.asyncio
async def test_answerable_queries_have_ground_truth_mapped(db_session: AsyncSession, tmp_path):
    try:
        dataset_data, corpus, baseline = await _build_and_run(db_session, tmp_path)
        for result in baseline.results:
            if not result.answerable:
                continue
            assert result.expected_chunks, "answerable query must map to expected chunks"
            assert len(result.expected_chunks) == len(set(result.expected_chunks))
    finally:
        await _cleanup(db_session)
