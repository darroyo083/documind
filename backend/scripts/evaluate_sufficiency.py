"""Run the DocuMind evidence-sufficiency experiment (PoC 3E).

Reuses the committed PoC 3C synthetic corpus and queries. For every query it
runs current production retrieval, computes candidate sufficiency signals, and
classifies supported/unsupported using several candidate strategies. Strategies
are tuned on the DEV split only; the selected strategy is then evaluated once
on the HOLDOUT split.

No paid LLM API is ever called; DeepSeek is never contacted.

Usage:

    python scripts/evaluate_sufficiency.py
    python scripts/evaluate_sufficiency.py --embedding-provider mock
"""

import argparse
import asyncio
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from typing import Any  # noqa: E402

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from app.config import settings  # noqa: E402
from app.evaluation import (  # noqa: E402  # noqa: E402
    dataset,
    runner,
    strategies,
    sufficiency_eval,
    sufficiency_reporting,
)
from app.infrastructure import models as _models  # noqa: E402, F401
from app.infrastructure.database import Base  # noqa: E402
from app.infrastructure.providers import (  # noqa: E402
    DeterministicEmbeddingProvider,
    FastEmbedProvider,
)
from app.infrastructure.storage import LocalDocumentStorage  # noqa: E402

DISPOSABLE_DATABASE_PREFIX = "documind_eval_"
LOCAL_DATABASE_HOSTS = {"127.0.0.1", "::1", "db", "localhost"}
PROTECTED_DATABASE_NAMES = {"postgres", "template0", "template1"}
DEFAULT_DATASET = BACKEND_DIR / "app" / "evaluation" / "datasets" / "retrieval_v1.json"
DEFAULT_OUTPUT_DIR = BACKEND_DIR / "evaluation" / "results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the DocuMind evidence-sufficiency experiment."
    )
    parser.add_argument(
        "--embedding-provider",
        choices=["local", "mock", "config"],
        default="local",
        help="Embedding provider. Default: local FastEmbed model.",
    )
    parser.add_argument(
        "--embedding-model",
        default="BAAI/bge-small-en-v1.5",
        help="FastEmbed model for the local provider (production default).",
    )
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def assert_safe_database_server(source_url) -> None:
    if source_url.host not in LOCAL_DATABASE_HOSTS:
        raise RuntimeError("Evaluation refuses to create databases on a non-local server")


def assert_disposable_database_name(database_name: str, source_database: str) -> None:
    expected_pattern = rf"{re.escape(DISPOSABLE_DATABASE_PREFIX)}[0-9a-f]{{32}}"
    if not re.fullmatch(expected_pattern, database_name):
        raise RuntimeError("Refusing to manage a database without the evaluation prefix")
    if database_name in PROTECTED_DATABASE_NAMES or database_name == source_database:
        raise RuntimeError("Refusing to manage a protected or configured database")


async def create_disposable_database(source_url) -> tuple[AsyncEngine, str]:
    database_name = f"{DISPOSABLE_DATABASE_PREFIX}{uuid.uuid4().hex}"
    assert_disposable_database_name(database_name, source_url.database)
    admin_url = source_url.set(database="postgres")
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        await admin_engine.dispose()

    eval_url = source_url.set(database=database_name)
    engine = create_async_engine(eval_url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.create_all)
    return engine, database_name


async def drop_disposable_database(source_url, database_name: str) -> None:
    assert_disposable_database_name(database_name, source_url.database)
    admin_url = source_url.set(database="postgres")
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
    finally:
        await admin_engine.dispose()


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except OSError:
        pass
    return None


def build_embedding_provider(choice: str, model_name: str):
    if choice == "mock":
        return DeterministicEmbeddingProvider(settings.embedding_dimension)
    if choice == "config":
        from app.application.dependencies import get_embedding_provider

        return get_embedding_provider()
    return FastEmbedProvider(model_name, settings.embedding_dimension)


def build_split_by_id(dataset_data: dict) -> dict[str, str]:
    return {query["id"]: query["evaluation_split"] for query in dataset_data["queries"]}


def baseline_outcomes(results: list, split_by_id: dict[str, str]) -> dict:
    """Reproduce the current production behavior: supported iff candidates exist.

    The production pipeline calls the answer provider whenever retrieval returns
    at least one candidate; the deterministic mock provider then answers. This
    baseline is therefore threshold-independent: supported == (retrieval_count > 0),
    matching the committed 0/9 unsupported-detection baseline at the production
    threshold.
    """
    outcomes = []
    for result in sorted(results, key=lambda r: r.id):
        supported = len(result.candidate_scores) > 0
        outcomes.append(
            {
                "query_id": result.id,
                "split": split_by_id.get(result.id, "dev"),
                "scope": result.scope,
                "category": result.category,
                "answerable": result.answerable,
                "supported": supported,
                "reason": "sufficient_evidence" if supported else "no_candidates",
            }
        )
    from app.evaluation import sufficiency_metrics

    metrics: dict[str, dict[str, Any]] = {
        "overall": sufficiency_metrics.classification_metrics(
            [o["answerable"] for o in outcomes], [o["supported"] for o in outcomes]
        )
    }
    for split in ("dev", "holdout"):
        group = [o for o in outcomes if o["split"] == split]
        if group:
            metrics[f"split:{split}"] = sufficiency_metrics.classification_metrics(
                [o["answerable"] for o in group], [o["supported"] for o in group]
            )
    for scope in ("private", "reference", "combined"):
        group = [o for o in outcomes if o["scope"] == scope]
        if group:
            metrics[scope] = sufficiency_metrics.classification_metrics(
                [o["answerable"] for o in group], [o["supported"] for o in group]
            )
    return metrics


async def main() -> int:
    args = parse_args()
    source_url = make_url(settings.database_url)
    assert_safe_database_server(source_url)

    started = time.perf_counter()
    top_k = args.top_k or settings.default_top_k
    threshold = (
        args.threshold if args.threshold is not None else settings.default_similarity_threshold
    )
    dataset_data = dataset.load_dataset(args.dataset)
    split_by_id = build_split_by_id(dataset_data)

    engine = None
    database_name = None
    try:
        engine, database_name = await create_disposable_database(source_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        embedding_provider = build_embedding_provider(args.embedding_provider, args.embedding_model)
        embed_model = getattr(embedding_provider, "model_name", "unknown")
        embed_dimension = getattr(embedding_provider, "dimension", settings.embedding_dimension)

        import tempfile

        with tempfile.TemporaryDirectory(prefix="documind-eval-") as tmp_dir:
            storage = LocalDocumentStorage(Path(tmp_dir) / "uploads")
            async with factory() as db:
                corpus = await runner.build_corpus(
                    db, dataset_data, embedding_provider, storage, Path(tmp_dir)
                )
                print(
                    f"Corpus: {corpus.counts['private_documents']} private docs, "
                    f"{corpus.counts['reference_documents']} reference docs, "
                    f"{corpus.counts['chunks']} chunks"
                )

                baseline = await runner.run_evaluation(
                    db, corpus, dataset_data, embedding_provider, top_k, threshold
                )
                print(
                    f"Retrieval baseline: Hit@1={baseline.metrics['overall'].get('hit_at_1')} "
                    f"Hit@3={baseline.metrics['overall'].get('hit_at_3')} "
                    f"Hit@5={baseline.metrics['overall'].get('hit_at_5')} "
                    f"MRR={baseline.metrics['overall'].get('mrr')}"
                )

                results = baseline.results
                grid = sufficiency_eval.grid_search_dev(results, split_by_id)
                diagnostics = sufficiency_eval.feature_diagnostics(results, split_by_id)
                selected_row = sufficiency_eval.select_strategy(grid)
                selected = None
                if selected_row is not None:
                    config = strategies.StrategyConfig(
                        name=selected_row["name"], params=selected_row["params"]
                    )
                    selected = sufficiency_eval.evaluate_config(config, results, split_by_id)
                verdict = sufficiency_eval.integration_verdict(
                    selected["metrics"] if selected else None
                )

        runtime_seconds = time.perf_counter() - started
        base_metrics = baseline_outcomes(results, split_by_id)
        report = sufficiency_reporting.build_sufficiency_json_report(
            dataset_version=dataset_data["dataset_version"],
            embedding_provider=args.embedding_provider,
            embedding_model=embed_model,
            embedding_dimension=embed_dimension,
            top_k=top_k,
            threshold=threshold,
            baseline=base_metrics,
            grid_search=grid,
            feature_diagnostics=diagnostics,
            selected=selected,
            verdict=verdict,
            corpus_counts=corpus.counts,
            runtime_seconds=runtime_seconds,
            git_commit=git_commit(),
        )

        args.output_dir.mkdir(parents=True, exist_ok=True)
        json_path = args.output_dir / "sufficiency_report.json"
        md_path = args.output_dir / "sufficiency_report.md"
        sufficiency_reporting.write_json_report(report, json_path)
        (md_path).write_text(
            sufficiency_reporting.render_sufficiency_markdown(report), encoding="utf-8"
        )

        print("")
        print("Evidence-sufficiency experiment")
        overall = base_metrics.get("overall", {})
        print(
            f"Baseline: answerable retention={overall.get('answerable_retention')} "
            f"unsupported detection={overall.get('unsupported_detection')}"
        )
        if selected:
            overall = selected["metrics"]["overall"]
            holdout = selected["metrics"]["split:holdout"]
            print(
                f"Selected: {selected['strategy']} "
                f"retention={overall.get('answerable_retention')} "
                f"detection={overall.get('unsupported_detection')}"
            )
            print(
                f"  holdout retention={holdout.get('answerable_retention')} "
                f"holdout detection={holdout.get('unsupported_detection')}"
            )
        else:
            print("Selected: NONE (no deterministic strategy cleared the DEV bar)")
        print(f"Integration verdict: integrate={verdict['integrate']} ({verdict['reason']})")
        print("")
        print("Reports:")
        print(f"  {json_path}")
        print(f"  {md_path}")

        failures = runner.hard_invariants(results)
        if failures:
            print("")
            print("SECURITY/INVARIANT FAILURES:")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        return 0
    finally:
        if engine is not None:
            await engine.dispose()
        if database_name is not None:
            await drop_disposable_database(source_url, database_name)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
