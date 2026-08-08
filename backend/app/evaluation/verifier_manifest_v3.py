"""Frozen one-shot contract for the OpenCode Go DeepSeek V4 Flash v3 holdout."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.evaluation.verifier_dataset import canonical_dataset_digest

DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parent / "datasets" / "verifier_v3_manifest.json"

FROZEN_PROMPT_VERSION = "1"
FROZEN_VERIFIER_PROVIDER = "opencode-go"
FROZEN_VERIFIER_MODEL = "deepseek-v4-flash"
FROZEN_VERIFIER_BASE_URL = "https://opencode.ai/zen/go/v1"
FROZEN_VERIFIER_ENDPOINT = "/chat/completions"
FROZEN_EMBEDDING_PROVIDER = "local"
FROZEN_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
FROZEN_EMBEDDING_DIMENSION = 384
FROZEN_TOP_K = 5
FROZEN_THRESHOLD = 0.5
DECISION_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class VerifierV3Manifest:
    experiment_name: str
    dataset_path: str
    dataset_name: str
    dataset_version: str
    dataset_canonical_sha256: str
    dataset_split: str
    verifier_prompt_version: str
    verifier_provider: str
    verifier_model: str
    verifier_base_url: str
    verifier_endpoint: str
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int
    retrieval_top_k: int
    retrieval_threshold: float
    decision_schema_version: str
    frozen: bool
    query_count: int
    answerable_count: int
    unsupported_count: int
    expected_verifier_calls: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_manifest(path: str | Path = DEFAULT_MANIFEST_PATH) -> VerifierV3Manifest:
    with open(path, encoding="utf-8") as handle:
        return VerifierV3Manifest(**json.load(handle))


def frozen_contract_violations(
    manifest: VerifierV3Manifest,
    *,
    dataset_path: str | Path,
    prompt_version: str,
    schema_version: str | None = None,
    verifier_provider: str,
    verifier_model: str,
    verifier_base_url: str,
    verifier_endpoint: str,
    embedding_provider: str,
    embedding_model: str,
    embedding_dimension: int,
    top_k: int,
    threshold: float,
    allow_external_api: bool,
    confirm_frozen_v3: bool,
    api_key_available: bool,
) -> list[str]:
    """Return every frozen-contract violation without performing network I/O.

    ``schema_version`` is compared only when explicitly provided (``None``
    skips the comparison): the CLI derives the effective decision schema
    version from the manifest itself, so the gate refuses only on explicit
    conflicting CLI values.
    """
    failures: list[str] = []
    if not manifest.frozen:
        failures.append("manifest is not marked frozen")
    actual_sha = canonical_dataset_digest(dataset_path)
    if actual_sha != manifest.dataset_canonical_sha256:
        failures.append(
            "dataset canonical checksum mismatch: "
            f"manifest={manifest.dataset_canonical_sha256} actual={actual_sha}"
        )
    comparisons = (
        (prompt_version, manifest.verifier_prompt_version, "verifier prompt version"),
        (verifier_provider, manifest.verifier_provider, "verifier provider"),
        (verifier_model, manifest.verifier_model, "verifier model"),
        (verifier_base_url.rstrip("/"), manifest.verifier_base_url, "verifier base URL"),
        (verifier_endpoint, manifest.verifier_endpoint, "verifier endpoint"),
        (embedding_provider, manifest.embedding_provider, "embedding provider"),
        (embedding_model, manifest.embedding_model, "embedding model"),
        (embedding_dimension, manifest.embedding_dimension, "embedding dimension"),
        (top_k, manifest.retrieval_top_k, "retrieval top_k"),
        (threshold, manifest.retrieval_threshold, "retrieval threshold"),
    )
    for actual, expected, label in comparisons:
        if actual != expected:
            failures.append(f"{label} mismatch: manifest={expected} requested={actual}")
    if schema_version is not None and schema_version != manifest.decision_schema_version:
        failures.append(
            f"decision schema version mismatch: manifest={manifest.decision_schema_version} "
            f"requested={schema_version}"
        )
    if not allow_external_api:
        failures.append("external API opt-in missing: pass --allow-external-api")
    if not confirm_frozen_v3:
        failures.append("frozen v3 confirmation missing: pass --run-frozen-v3")
    if not api_key_available:
        failures.append("OPENCODE_GO_API_KEY is unavailable")
    return failures
