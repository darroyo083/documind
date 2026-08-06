"""Frozen manifest for the one-shot v2 verifier holdout.

The manifest freezes every experiment input that a real verifier run must honor:

- dataset path, version, and canonical JSON content SHA-256
  (``dataset_canonical_sha256``; line-ending/whitespace insensitive, semantic
  edits change it)
- verifier prompt version
- verifier provider and model
- embedding provider/model/dimension
- retrieval top_k and threshold

A real v2 semantic run is refused whenever the live configuration disagrees
with the manifest. This protects the "fresh frozen holdout" methodology: v2 may
only ever be evaluated under exactly the frozen inputs, and any other use is a
regression/comparison run that must be labeled as such.

No secrets are stored here. The manifest does not contain a checksum of itself;
dataset hashing never depends on the manifest (no circularity).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.evaluation.verifier_dataset import canonical_dataset_digest

DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parent / "datasets" / "verifier_v2_manifest.json"

FROZEN_PROMPT_VERSION = "1"
FROZEN_VERIFIER_PROVIDER = "deepseek"
FROZEN_VERIFIER_MODEL = "deepseek-chat"
FROZEN_EMBEDDING_PROVIDER = "local"
FROZEN_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
FROZEN_EMBEDDING_DIMENSION = 384
FROZEN_TOP_K = 5
FROZEN_THRESHOLD = 0.5
DECISION_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class VerifierManifest:
    experiment_name: str
    dataset_path: str
    dataset_name: str
    dataset_version: str
    dataset_canonical_sha256: str
    dataset_split: str
    verifier_prompt_version: str
    verifier_provider: str
    verifier_model: str
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


def load_manifest(path: str | Path = DEFAULT_MANIFEST_PATH) -> VerifierManifest:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return VerifierManifest(**data)


def write_manifest(manifest: VerifierManifest, path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(manifest.to_dict(), handle, indent=2, sort_keys=True, ensure_ascii=False)


def frozen_contract_violations(
    manifest: VerifierManifest,
    *,
    dataset_path: str | Path,
    prompt_version: str,
    verifier_provider: str,
    verifier_model: str,
    embedding_provider: str,
    embedding_model: str,
    embedding_dimension: int,
    top_k: int,
    threshold: float,
    allow_external_api: bool,
    confirm_frozen_v2: bool,
) -> list[str]:
    """Return every violation of the frozen v2 contract, or [] when all clear.

    This is the single gate a real v2 external run must pass BEFORE any network
    or model call. Each entry is a human-readable failure description.
    """
    failures: list[str] = []

    if not manifest.frozen:
        failures.append("manifest is not marked frozen")

    actual_sha = canonical_dataset_digest(dataset_path)
    if actual_sha != manifest.dataset_canonical_sha256:
        failures.append(
            f"dataset canonical checksum mismatch: "
            f"manifest={manifest.dataset_canonical_sha256} actual={actual_sha}"
        )

    if prompt_version != manifest.verifier_prompt_version:
        failures.append(
            f"verifier prompt version mismatch: manifest={manifest.verifier_prompt_version} "
            f"live={prompt_version}"
        )

    if verifier_provider != manifest.verifier_provider:
        failures.append(
            f"verifier provider mismatch: manifest={manifest.verifier_provider} "
            f"requested={verifier_provider}"
        )
    if verifier_model != manifest.verifier_model:
        failures.append(
            f"verifier model mismatch: manifest={manifest.verifier_model} "
            f"requested={verifier_model}"
        )

    if embedding_provider != manifest.embedding_provider:
        failures.append(
            f"embedding provider mismatch: manifest={manifest.embedding_provider} "
            f"requested={embedding_provider}"
        )
    if embedding_model != manifest.embedding_model:
        failures.append(
            f"embedding model mismatch: manifest={manifest.embedding_model} "
            f"requested={embedding_model}"
        )
    if embedding_dimension != manifest.embedding_dimension:
        failures.append(
            f"embedding dimension mismatch: manifest={manifest.embedding_dimension} "
            f"requested={embedding_dimension}"
        )

    if top_k != manifest.retrieval_top_k:
        failures.append(
            f"retrieval top_k mismatch: manifest={manifest.retrieval_top_k} requested={top_k}"
        )
    if threshold != manifest.retrieval_threshold:
        failures.append(
            f"retrieval threshold mismatch: manifest={manifest.retrieval_threshold} "
            f"requested={threshold}"
        )

    if verifier_provider in ("deepseek",) and not allow_external_api:
        failures.append("external API opt-in missing: pass --allow-external-api")
    if verifier_provider in ("deepseek",) and not confirm_frozen_v2:
        failures.append(
            "frozen v2 confirmation missing: pass --run-frozen-v2 for the one-shot holdout"
        )

    return failures
