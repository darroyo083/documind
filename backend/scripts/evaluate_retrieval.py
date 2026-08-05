"""Run the DocuMind retrieval benchmark.

Creates a disposable PostgreSQL evaluation database, builds the synthetic corpus
through the real ingestion/import paths, and evaluates the production retrieval
service against explicit ground truth.

Usage:

    python scripts/evaluate_retrieval.py
    python scripts/evaluate_retrieval.py --embedding-provider mock --no-sweeps
    python scripts/evaluate_retrieval.py --top-k 5 --threshold 0.5

The default embedding provider is the real local FastEmbed model
(BAAI/bge-small-en-v1.5). No paid LLM API is ever called.
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

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from app.config import settings  # noqa: E402
from app.evaluation import dataset, reporting, runner  # noqa: E402
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
    parser = argparse.ArgumentParser(description="Run the DocuMind retrieval benchmark.")
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
    parser.add_argument("--no-sweeps", action="store_true", help="Skip top_k/threshold sweeps")
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


def model_previously_cached(model_name: str) -> bool | None:
    try:
        cache_root = Path.home() / ".cache" / "fastembed"
        if not cache_root.is_dir():
            return False
        return any(model_name.lower() in child.name.lower() for child in cache_root.iterdir())
    except OSError:
        return None


def build_embedding_provider(choice: str, model_name: str):
    if choice == "mock":
        return DeterministicEmbeddingProvider(settings.embedding_dimension)
    if choice == "config":
        from app.application.dependencies import get_embedding_provider

        return get_embedding_provider()
    return FastEmbedProvider(model_name, settings.embedding_dimension)


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

    engine = None
    database_name = None
    try:
        engine, database_name = await create_disposable_database(source_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        embedding_provider = build_embedding_provider(args.embedding_provider, args.embedding_model)
        embed_model = getattr(embedding_provider, "model_name", "unknown")
        embed_dimension = getattr(embedding_provider, "dimension", settings.embedding_dimension)
        cached = model_previously_cached(embed_model)

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
                top_k_sweep = None
                threshold_sweep = None
                if not args.no_sweeps:
                    top_k_sweep = await runner.run_top_k_sweep(
                        db, corpus, dataset_data, embedding_provider, threshold, [1, 3, 5, 8, 10]
                    )
                    threshold_sweep = await runner.run_threshold_sweep(
                        db,
                        corpus,
                        dataset_data,
                        embedding_provider,
                        top_k,
                        [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
                    )

        runtime_seconds = time.perf_counter() - started
        report = reporting.build_json_report(
            dataset_version=dataset_data["dataset_version"],
            embedding_provider=args.embedding_provider,
            embedding_model=embed_model,
            embedding_dimension=embed_dimension,
            top_k=top_k,
            threshold=threshold,
            corpus_counts=corpus.counts,
            evaluation=baseline,
            top_k_sweep=top_k_sweep,
            threshold_sweep=threshold_sweep,
            runtime_seconds=runtime_seconds,
            git_commit=git_commit(),
        )
        if cached is not None:
            report["benchmark"]["model_previously_cached"] = cached

        args.output_dir.mkdir(parents=True, exist_ok=True)
        json_path = args.output_dir / "report.json"
        md_path = args.output_dir / "report.md"
        reporting.write_json_report(report, json_path)
        (md_path).write_text(reporting.render_markdown(report), encoding="utf-8")

        reporting.print_console_summary(report)
        print("")
        print("Reports:")
        print(f"  {json_path}")
        print(f"  {md_path}")

        failures = runner.hard_invariants(baseline.results)
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
