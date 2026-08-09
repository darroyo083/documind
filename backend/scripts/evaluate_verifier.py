"""Run the DocuMind evidence-verifier evaluation harness (PoC 3F-A / 3F-B).

Flow: load dataset -> build the existing synthetic corpus -> run real
production retrieval (reused from runner) -> build verifier-safe evidence
payload -> verifier decision (zero-evidence queries short-circuit without
calling the verifier) -> strict output validation -> compare with answerable
ground truth -> classification metrics.

This harness tests a dedicated evidence-verification model. It does NOT
integrate any verifier into production and makes no production changes.

Run modes:

1. Infrastructure test (default) -- zero network/model calls:

       python scripts/evaluate_verifier.py

   Defaults are mock verifier + mock embeddings, so the plain invocation is
   fully offline. Mock embeddings + mock verifier = infrastructure test only;
   results have NO semantic meaning.

2. Real semantic verifier benchmark -- requires explicit opt-in and local
   FastEmbed retrieval (the real production retrieval stack):

       python scripts/evaluate_verifier.py \
           --provider deepseek \
           --allow-external-api \
           --embedding-provider local \
           --threshold 0.5

   - embedding-provider local = FastEmbed BAAI/bge-small-en-v1.5 (384 dims)
   - top_k 5 (the benchmark top_k; settings.default_top_k is already 5, pass
     --top-k 5 explicitly to be unambiguous)
   - threshold 0.5 = the PoC 3C/3E BENCHMARK threshold (NOT the config.py
     application default of 0.2)
   - --verifier-model <name> selects the external model explicitly.

   Requires DEEPSEEK_API_KEY and makes one paid external call per query that
   retrieved at least one candidate. The tool never prints API keys. Do not
   run it unless you intend to pay for external calls.

3. Frozen v2 one-shot holdout -- the fresh PoC 3F-B holdout may only be
   evaluated under the exact frozen inputs recorded in the manifest, with
   explicit confirmation:

       python scripts/evaluate_verifier.py \
           --dataset app/evaluation/datasets/verifier_holdout_v2.json \
           --provider deepseek \
           --allow-external-api \
           --embedding-provider local \
           --threshold 0.5 \
           --top-k 5 \
           --verifier-model deepseek-chat \
           --run-frozen-v2

   The command refuses to run BEFORE any HTTP/model call when the dataset
   checksum, prompt version, provider/model, or retrieval configuration
   disagrees with the frozen manifest, or when --allow-external-api or
   --run-frozen-v2 is missing.

 4. Retrieval preflight (no verifier at all) -- certifies v2 retrieval
    eligibility without invoking any verifier (zero verifier calls):

       python scripts/evaluate_verifier.py \
           --dataset app/evaluation/datasets/verifier_holdout_v2.json \
           --embedding-provider local \
           --retrieval-preflight

 5. Direct-drive verifier-contract dev cases (no retrieval, evidence inline):

       python scripts/evaluate_verifier.py \
           --direct-cases experiments/verifier_contract/dev_cases.json \
           --provider opencode-go \
           --allow-external-api \
           --case-ids dev_near_annual_storage,dev_inject_override \
           --output-name verifier_dev_report

    Prompt/schema versions default to v2 (the hardened minimal contract);
    frozen v2/v3 datasets derive their effective versions from the manifest
    and refuse explicit conflicting CLI values (--prompt-version /
    --schema-version). --query-ids selects a targeted subset of dataset
    queries without extra verifier calls; --output-name names the report.

    Direct-cases safety semantics:
    - A real provider/transport failure (HTTP/network error, unreadable
      response envelope) mapped to VerifierProviderError STOPS the run
      immediately (stop_on_provider_error=True): the partial evaluation is
      persisted as a JSON+MD report with a ``partial_failure`` block and the
      command exits with code 3. No later case is called after the failure.
    - Ordinary invalid model outputs (missing field, wrong type, unknown
      source id, supported/evidence inconsistencies) are MEASUREMENTS: they
      are recorded as invalid, consume exactly one call, are never repaired
      or retried, and execution continues with the next case.
    - --expected-verifier-calls N (optional) exits with code 2 after the run
      when evaluation.verifier_calls != N. Zero-evidence short-circuit cases
      never count as calls. Never hardcoded: the orchestrator passes 14 and 8
      per invocation.

Never present mock-retrieval results as verifier quality.
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
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
from app.evaluation import (  # noqa: E402
    dataset,
    runner,
    verifier,
    verifier_dataset,
    verifier_dev_cases,
    verifier_eval,
    verifier_manifest,
    verifier_manifest_v3,
    verifier_preflight,
    verifier_prompt,
    verifier_providers,
    verifier_reporting,
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
BENCHMARK_TOP_K = 5
BENCHMARK_THRESHOLD = 0.5


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the DocuMind evidence-verifier evaluation harness."
    )
    parser.add_argument(
        "--provider",
        choices=["mock", "deepseek", "opencode-go"],
        default="mock",
        help="Verifier provider. Default 'mock' performs zero network calls.",
    )
    parser.add_argument(
        "--run-frozen-v3",
        action="store_true",
        help="Explicit confirmation for the one-shot OpenCode Go v3 holdout.",
    )
    parser.add_argument(
        "--allow-external-api",
        action="store_true",
        help="Explicit opt-in to external model API calls (e.g. DeepSeek).",
    )
    parser.add_argument(
        "--verifier-model",
        default=None,
        help=(
            "External verifier model (e.g. deepseek-chat or deepseek-v4-flash). "
            "Explicit selection; the frozen v2 holdout requires exactly the manifest model."
        ),
    )
    parser.add_argument(
        "--embedding-provider",
        choices=["local", "mock", "config"],
        default="mock",
        help="Embedding provider. 'local' = real FastEmbed retrieval stack "
        "(BAAI/bge-small-en-v1.5); 'mock' = infrastructure test only. "
        "Default: mock, so a bare invocation makes zero network calls.",
    )
    parser.add_argument(
        "--embedding-model",
        default="BAAI/bge-small-en-v1.5",
        help="FastEmbed model for the local provider (production default).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help=f"Retrieval top_k. Benchmark uses {BENCHMARK_TOP_K}.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help=f"Retrieval similarity threshold. Benchmark uses {BENCHMARK_THRESHOLD} "
        "(not the config.py default 0.2).",
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--retrieval-preflight",
        action="store_true",
        help="Retrieval-only v2 preflight: build corpus, run production retrieval, "
        "certify eligibility, and stop BEFORE any verifier is invoked.",
    )
    parser.add_argument(
        "--run-frozen-v2",
        action="store_true",
        help="Explicit confirmation that this is the one-shot frozen v2 holdout "
        "evaluation. Required (with --allow-external-api) for the external v2 run.",
    )
    parser.add_argument(
        "--direct-cases",
        type=Path,
        default=None,
        help="Run verifier-level dev cases WITHOUT retrieval (evidence provided "
        "inline). Path to a dev dataset like experiments/verifier_contract/dev_cases.json.",
    )
    parser.add_argument(
        "--case-ids",
        default=None,
        help="Comma-separated subset of dev case ids to run in --direct-cases mode.",
    )
    parser.add_argument(
        "--query-ids",
        default=None,
        help="Comma-separated subset of dataset query ids to run (queries outside "
        "the subset are skipped without calling the verifier).",
    )
    parser.add_argument(
        "--prompt-version",
        choices=["1", "2"],
        default=None,
        help="Verifier prompt version. Default: '2' for dev/direct runs; frozen "
        "v2/v3 datasets derive the effective version from their manifest.",
    )
    parser.add_argument(
        "--schema-version",
        choices=["1", "2"],
        default=None,
        help="Verifier decision schema version. Default: '2' for dev/direct runs; "
        "frozen v2/v3 datasets derive the effective version from their manifest.",
    )
    parser.add_argument(
        "--output-name",
        default="verifier_report",
        help="Report file name without extension (writes <name>.json and <name>.md).",
    )
    parser.add_argument(
        "--expected-verifier-calls",
        type=int,
        default=None,
        help="Direct-cases only: expected external verifier call count. After the run, "
        "exit with code 2 when evaluation.verifier_calls differs. Zero-evidence "
        "short-circuit cases never count as calls (verifier_calls semantics exclude "
        "them), so pass the number of cases that actually invoke the provider. "
        "Optional: when omitted no count check runs.",
    )
    return parser.parse_args(argv)


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


def load_dataset_data(path: str | Path) -> tuple[dict, bool]:
    """Load and validate a dataset, dispatching on dataset_version.

    Returns ``(dataset, is_v2)``. v2 uses the strict verifier-holdout
    validator; everything else uses the v1 loader.
    """
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    is_v2 = data.get("dataset_version") == verifier_dataset.V2_DATASET_VERSION
    is_v3 = data.get("dataset_version") == verifier_dataset.V3_DATASET_VERSION
    if is_v2:
        verifier_dataset.validate_verifier_holdout_dataset(data)
    elif is_v3:
        verifier_dataset.validate_verifier_holdout_v3_dataset(data)
    else:
        dataset.validate_dataset(data)
    return data, is_v2


def effective_retrieval_config(args) -> tuple[int, float]:
    top_k = args.top_k or settings.default_top_k
    threshold = (
        args.threshold if args.threshold is not None else settings.default_similarity_threshold
    )
    return top_k, threshold


def parse_id_list(value: str | None) -> list[str] | None:
    """Parse a comma-separated id list argument; None stays None."""
    if value is None:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def enforce_frozen_v2_contract(args, dataset_is_v2: bool) -> bool:
    """Run the frozen-v2 gate. Returns True when the gate was applied and passed.

    Prints violations and returns False when the gate was applied and failed.
    When the run is not a v2 external run, returns True without checking.

    Effective prompt/schema versions are derived from the manifest (same
    pattern as ``effective_model``); the gate refuses only on explicit
    conflicting CLI values.
    """
    external_requested = args.provider in verifier_providers.EXTERNAL_PROVIDERS
    if not (dataset_is_v2 and (external_requested or args.run_frozen_v2)):
        return True

    manifest = verifier_manifest.load_manifest()
    top_k, threshold = effective_retrieval_config(args)
    effective_model = args.verifier_model or manifest.verifier_model
    effective_prompt = args.prompt_version or manifest.verifier_prompt_version
    effective_schema = args.schema_version or manifest.decision_schema_version
    violations = verifier_manifest.frozen_contract_violations(
        manifest,
        dataset_path=args.dataset,
        prompt_version=effective_prompt,
        schema_version=effective_schema,
        verifier_provider=args.provider,
        verifier_model=effective_model,
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
        embedding_dimension=settings.embedding_dimension,
        top_k=top_k,
        threshold=threshold,
        allow_external_api=args.allow_external_api,
        confirm_frozen_v2=args.run_frozen_v2,
    )
    if violations:
        print("FROZEN V2 CONTRACT VIOLATIONS (refusing to run; no external call was made):")
        for violation in violations:
            print(f"  - {violation}")
        return False
    args.verifier_model = effective_model
    args.prompt_version = effective_prompt
    args.schema_version = effective_schema
    return True


def enforce_frozen_v3_contract(args, dataset_is_v3: bool) -> bool:
    """Apply the frozen v3 contract before provider construction or HTTP."""
    if args.run_frozen_v3 and not dataset_is_v3:
        print("--run-frozen-v3 requires the verifier holdout v3 dataset.")
        return False
    external_requested = args.provider in verifier_providers.EXTERNAL_PROVIDERS
    if not (dataset_is_v3 and (external_requested or args.run_frozen_v3)):
        return True

    manifest = verifier_manifest_v3.load_manifest()
    top_k, threshold = effective_retrieval_config(args)
    effective_model = args.verifier_model or manifest.verifier_model
    effective_prompt = args.prompt_version or manifest.verifier_prompt_version
    effective_schema = args.schema_version or manifest.decision_schema_version
    violations = verifier_manifest_v3.frozen_contract_violations(
        manifest,
        dataset_path=args.dataset,
        prompt_version=effective_prompt,
        schema_version=effective_schema,
        verifier_provider=args.provider,
        verifier_model=effective_model,
        verifier_base_url=verifier_providers.DEFAULT_OPENCODE_GO_BASE_URL,
        verifier_endpoint=verifier_providers.OPENCODE_GO_CHAT_ENDPOINT,
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
        embedding_dimension=settings.embedding_dimension,
        top_k=top_k,
        threshold=threshold,
        allow_external_api=args.allow_external_api,
        confirm_frozen_v3=args.run_frozen_v3,
        api_key_available=bool(os.environ.get("OPENCODE_GO_API_KEY", "").strip()),
    )
    if violations:
        print("FROZEN V3 CONTRACT VIOLATIONS (refusing to run; no external call was made):")
        for violation in violations:
            print(f"  - {violation}")
        return False
    args.verifier_model = effective_model
    args.prompt_version = effective_prompt
    args.schema_version = effective_schema
    return True


async def run_preflight(args, dataset_data: dict, source_url) -> int:
    """Retrieval-only preflight: real FastEmbed, no verifier invocation at all."""
    if args.embedding_provider != "local":
        print("Retrieval preflight requires --embedding-provider local (real FastEmbed).")
        return 2

    started = time.perf_counter()
    top_k, threshold = effective_retrieval_config(args)
    embedding_provider = build_embedding_provider(args.embedding_provider, args.embedding_model)
    embed_model = getattr(embedding_provider, "model_name", "unknown")
    embed_dimension = getattr(embedding_provider, "dimension", settings.embedding_dimension)

    engine = None
    database_name = None
    try:
        engine, database_name = await create_disposable_database(source_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
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
                retrieval = await runner.run_evaluation(
                    db, corpus, dataset_data, embedding_provider, top_k, threshold
                )
                runtime_seconds = time.perf_counter() - started
                eligibility = verifier_preflight.compute_eligibility(corpus, retrieval.results)
                report = verifier_preflight.build_preflight_json_report(
                    dataset_path=str(args.dataset),
                    dataset_canonical_sha256=verifier_dataset.canonical_dataset_digest(
                        args.dataset
                    ),
                    dataset_version=dataset_data["dataset_version"],
                    embedding_provider=args.embedding_provider,
                    embedding_model=embed_model,
                    embedding_dimension=embed_dimension,
                    top_k=top_k,
                    threshold=threshold,
                    corpus_counts=corpus.counts,
                    runtime_seconds=runtime_seconds,
                    git_commit=git_commit(),
                    eligibility=eligibility,
                )
    finally:
        if engine is not None:
            await engine.dispose()
        if database_name is not None:
            await drop_disposable_database(source_url, database_name)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    version = dataset_data["dataset_version"]
    json_path = args.output_dir / f"verifier_v{version}_preflight.json"
    md_path = args.output_dir / f"verifier_v{version}_preflight.md"
    verifier_preflight.write_preflight_report(report, json_path)
    md_path.write_text(verifier_preflight.render_preflight_markdown(report), encoding="utf-8")

    security = eligibility["security"]
    print("")
    print(f"Verifier v{version} retrieval preflight (no verifier invoked)")
    print("Run mode: retrieval_preflight")
    print(f"Dataset canonical SHA-256: {report['benchmark']['dataset_canonical_sha256']}")
    print(
        f"Answerable Hit@1={eligibility['answerable_hit_at_1']} "
        f"Hit@3={eligibility['answerable_hit_at_3']} "
        f"Hit@5={eligibility['answerable_hit_at_5']}"
    )
    print(
        f"Answerable with ALL expected evidence in top5: "
        f"{eligibility['answerable_with_all_expected_in_top5']} / "
        f"{eligibility['answerable_count']}"
    )
    print(
        f"Unsupported with >=1 candidate: "
        f"{eligibility['unsupported_with_candidates']} / {eligibility['unsupported_count']}"
    )
    print(f"Average candidate count: {eligibility['average_candidate_count']}")
    print(
        f"Combined source coverage: {eligibility['combined_source_coverage']} "
        f"({eligibility['combined_required']} required)"
    )
    print(
        f"Cross-user leakage: {security['cross_user_leaked']}, "
        f"cross-space leakage: {security['cross_space_leaked']}, "
        f"scope violations: {security['scope_violations']}"
    )
    print(f"Eligible to freeze: {eligibility['eligible_to_freeze']}")
    print("Reports:")
    print(f"  {json_path}")
    print(f"  {md_path}")
    return 0 if eligibility["eligible_to_freeze"] else 1


async def run_direct_cases(args) -> int:
    """Direct-drive verifier-level evaluation: no retrieval, evidence inline.

    Provider/transport failures (``VerifierProviderError``) abort the run via
    ``stop_on_provider_error=True``; the partial evaluation is persisted with
    a ``partial_failure`` block and the function returns 3. Invalid semantic
    outputs never abort: they are recorded and execution continues. An
    optional ``--expected-verifier-calls`` mismatch returns 2 after the report
    is persisted.
    """
    dataset_data = verifier_dev_cases.load_dev_cases(args.direct_cases)
    cases = dataset_data["cases"]
    case_ids = parse_id_list(args.case_ids)
    if case_ids:
        wanted = set(case_ids)
        unknown = sorted(wanted - {case["id"] for case in cases})
        if unknown:
            print(f"Unknown dev case id(s): {unknown}")
            return 2
        cases = [case for case in cases if case["id"] in wanted]

    verifier_providers.ensure_external_api_opt_in(args.provider, args.allow_external_api)
    prompt_version = args.prompt_version or verifier_prompt.DEFAULT_PROMPT_VERSION
    schema_version = args.schema_version or verifier.DEFAULT_SCHEMA_VERSION
    verifier_instance, provider_name, external_api = verifier_providers.build_verifier_provider(
        args.provider,
        args.verifier_model,
        prompt_version=prompt_version,
        schema_version=schema_version,
    )

    started = time.perf_counter()
    provider_abort = None
    try:
        evaluation = await verifier_eval.run_direct_cases_evaluation(
            cases,
            verifier_instance,
            stop_on_provider_error=True,
            schema_version=schema_version,
        )
    except verifier_eval.VerifierProviderAbortError as exc:
        provider_abort = exc
        evaluation = exc.evaluation
    runtime_seconds = time.perf_counter() - started

    args.output_dir.mkdir(parents=True, exist_ok=True)
    total_evidence = sum(len(case["evidence"]) for case in cases)
    report = verifier_reporting.build_verifier_json_report(
        dataset_version=dataset_data["dataset_version"],
        embedding_provider="direct",
        embedding_model="inline-evidence",
        embedding_dimension=0,
        top_k=0,
        threshold=0.0,
        verifier_provider=provider_name,
        verifier_model=verifier_instance.model_name,
        verifier_prompt_version=prompt_version,
        decision_schema_version=schema_version,
        external_api=external_api,
        corpus_counts={"chunks": total_evidence},
        runtime_seconds=runtime_seconds,
        git_commit=git_commit(),
        evaluation=evaluation,
    )
    if provider_abort is not None:
        report["benchmark"]["partial_failure"] = {
            "first_failing_query": provider_abort.query_id,
            "attempted_calls": evaluation.verifier_calls,
            "successful_calls": evaluation.verifier_calls - 1,
            "failure_type": "provider_error",
            "planned_cases": len(cases),
            "unexecuted_cases": len(cases) - evaluation.verifier_calls,
        }
    json_path = args.output_dir / f"{args.output_name}.json"
    md_path = args.output_dir / f"{args.output_name}.md"
    verifier_reporting.write_json_report(report, json_path)
    md_path.write_text(verifier_reporting.render_verifier_markdown(report), encoding="utf-8")

    print("")
    print("Verifier contract dev evaluation (direct cases, no retrieval)")
    print(f"Dataset: {args.direct_cases}")
    print(f"Cases: {len(cases)}")
    print(f"Provider: {provider_name} (external_api={external_api})")
    print(f"Verifier prompt version: {prompt_version}")
    print(f"Decision schema version: {schema_version}")
    print(f"Verifier calls: {evaluation.verifier_calls}")
    valid_count = sum(1 for outcome in evaluation.outcomes if not outcome.invalid)
    print(f"Valid verifier outputs: {valid_count}/{len(evaluation.outcomes)}")
    print(f"Invalid outputs: {len(evaluation.invalid_outputs)}")
    print(f"Evidence-source validation failures: {len(evaluation.evidence_validation_failures)}")
    provider_failures = sum(
        1 for outcome in evaluation.invalid_outputs if outcome.error_kind == "provider_error"
    )
    print(f"Provider failures: {provider_failures}")
    print(f"False supports: {len(evaluation.false_supports)}")
    print(f"False rejections: {len(evaluation.false_rejections)}")
    overall = report["metrics"].get("overall", {})
    if overall:
        print(
            f"Dev metrics: accuracy={overall.get('accuracy')} "
            f"retention={overall.get('answerable_retention')} "
            f"detection={overall.get('unsupported_detection')} "
            f"balanced_accuracy={overall.get('balanced_accuracy')}"
        )
    print("Reports:")
    print(f"  {json_path}")
    print(f"  {md_path}")

    if provider_abort is not None:
        print("Direct cases stopped after the first provider failure; no later case was called.")
        print(f"First failing case: {provider_abort.query_id}")
        print(
            f"Partial run: {evaluation.verifier_calls} attempted, "
            f"{evaluation.verifier_calls - 1} successful, "
            f"{len(cases) - evaluation.verifier_calls} unexecuted "
            f"(of {len(cases)} planned). The partial report above was persisted."
        )
        return 3

    expected_calls = args.expected_verifier_calls
    if expected_calls is not None and evaluation.verifier_calls != expected_calls:
        print(
            f"Expected verifier call count mismatch: "
            f"expected {expected_calls}, observed {evaluation.verifier_calls}. "
            f"Zero-evidence short-circuit cases never count as calls."
        )
        return 2
    return 0


async def main() -> int:
    args = parse_args()

    if args.direct_cases:
        return await run_direct_cases(args)

    source_url = make_url(settings.database_url)
    assert_safe_database_server(source_url)

    dataset_data, dataset_is_v2 = load_dataset_data(args.dataset)
    dataset_is_v3 = dataset_data.get("dataset_version") == verifier_dataset.V3_DATASET_VERSION

    if args.retrieval_preflight:
        return await run_preflight(args, dataset_data, source_url)

    if not enforce_frozen_v2_contract(args, dataset_is_v2):
        return 2
    if not enforce_frozen_v3_contract(args, dataset_is_v3):
        return 2

    prompt_version = args.prompt_version or verifier_prompt.DEFAULT_PROMPT_VERSION
    schema_version = args.schema_version or verifier.DEFAULT_SCHEMA_VERSION

    verifier_providers.ensure_external_api_opt_in(args.provider, args.allow_external_api)
    verifier_instance, provider_name, external_api = verifier_providers.build_verifier_provider(
        args.provider,
        args.verifier_model,
        prompt_version=prompt_version,
        schema_version=schema_version,
    )

    started = time.perf_counter()
    top_k, threshold = effective_retrieval_config(args)
    split_by_id = build_split_by_id(dataset_data)

    engine = None
    database_name = None
    try:
        engine, database_name = await create_disposable_database(source_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        embedding_provider = build_embedding_provider(args.embedding_provider, args.embedding_model)
        embed_model = getattr(embedding_provider, "model_name", "unknown")
        embed_dimension = getattr(embedding_provider, "dimension", settings.embedding_dimension)

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

                retrieval = await runner.run_evaluation(
                    db, corpus, dataset_data, embedding_provider, top_k, threshold
                )
                print(
                    f"Retrieval: Hit@1={retrieval.metrics['overall'].get('hit_at_1')} "
                    f"Hit@3={retrieval.metrics['overall'].get('hit_at_3')} "
                    f"Hit@5={retrieval.metrics['overall'].get('hit_at_5')} "
                    f"MRR={retrieval.metrics['overall'].get('mrr')}"
                )

                provider_abort = None
                try:
                    results = retrieval.results
                    query_ids = parse_id_list(args.query_ids)
                    if query_ids:
                        wanted = set(query_ids)
                        available = {result.id for result in results}
                        unknown = sorted(wanted - available)
                        if unknown:
                            print(f"Unknown dataset query id(s): {unknown}")
                            return 2
                        results = [result for result in results if result.id in wanted]
                    evaluation = await verifier_eval.run_verifier_evaluation(
                        results,
                        verifier_instance,
                        split_by_id,
                        stop_on_provider_error=bool(dataset_is_v3 and args.run_frozen_v3),
                        schema_version=schema_version,
                    )
                except verifier_eval.VerifierProviderAbortError as exc:
                    provider_abort = exc
                    evaluation = exc.evaluation
                runtime_seconds = time.perf_counter() - started
                report = verifier_reporting.build_verifier_json_report(
                    dataset_version=dataset_data["dataset_version"],
                    embedding_provider=args.embedding_provider,
                    embedding_model=embed_model,
                    embedding_dimension=embed_dimension,
                    top_k=top_k,
                    threshold=threshold,
                    verifier_provider=provider_name,
                    verifier_model=verifier_instance.model_name,
                    verifier_prompt_version=prompt_version,
                    decision_schema_version=schema_version,
                    external_api=external_api,
                    corpus_counts=corpus.counts,
                    runtime_seconds=runtime_seconds,
                    git_commit=git_commit(),
                    evaluation=evaluation,
                    dataset_canonical_sha256=(
                        verifier_dataset.canonical_dataset_digest(args.dataset)
                        if dataset_is_v2 or dataset_is_v3
                        else None
                    ),
                    frozen_v2_holdout=bool(dataset_is_v2 and args.run_frozen_v2),
                    frozen_holdout_version="3" if dataset_is_v3 and args.run_frozen_v3 else None,
                )
                if provider_abort is not None:
                    report["benchmark"]["partial_failure"] = {
                        "first_failing_query": provider_abort.query_id,
                        "attempted_calls": evaluation.verifier_calls,
                        "successful_calls": evaluation.verifier_calls - 1,
                        "failure_type": "provider_error",
                    }

        args.output_dir.mkdir(parents=True, exist_ok=True)
        json_path = args.output_dir / f"{args.output_name}.json"
        md_path = args.output_dir / f"{args.output_name}.md"
        verifier_reporting.write_json_report(report, json_path)
        md_path.write_text(verifier_reporting.render_verifier_markdown(report), encoding="utf-8")

        print("")
        print("Evidence-verifier evaluation harness")
        mode = verifier_reporting.run_mode(args.embedding_provider, provider_name)
        print(f"Run mode: {mode}")
        print(f"Provider: {provider_name} (external_api={external_api})")
        print(f"Verifier prompt version: {prompt_version}")
        print(f"Decision schema version: {schema_version}")
        print(f"Verifier calls (queries with >=1 candidate): {evaluation.verifier_calls}")
        overall = report["metrics"].get("overall", {})
        dev = report["metrics"].get("split:dev", {})
        regression = report["metrics"].get("split:regression", {})
        print(
            f"Overall: retention={overall.get('answerable_retention')} "
            f"detection={overall.get('unsupported_detection')} "
            f"balanced_accuracy={overall.get('balanced_accuracy')}"
        )
        if dev:
            print(
                f"DEV: retention={dev.get('answerable_retention')} "
                f"detection={dev.get('unsupported_detection')}"
            )
        if regression:
            print(
                f"REGRESSION: retention={regression.get('answerable_retention')} "
                f"detection={regression.get('unsupported_detection')}"
            )
        print(f"Invalid verifier outputs: {len(report['invalid_outputs'])}")
        print(f"Evidence-source validation failures: {len(report['evidence_validation_failures'])}")
        print("Reports:")
        print(f"  {json_path}")
        print(f"  {md_path}")

        if provider_abort is not None:
            print("Frozen v3 stopped after the first provider failure; no later query was called.")
            print(f"First failing query: {provider_abort.query_id}")
            return 3

        failures = runner.hard_invariants(retrieval.results)
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
