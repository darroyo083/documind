"""Frozen one-shot contract for the AB2 attribute-binding V4 holdout.

The fresh V4 holdout is evaluated exactly once under a frozen AB2 contract:
architecture, provider, model, and prompt bytes are pinned before the first
inference. The gate refuses to run when any frozen input differs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.evaluation.verifier_dataset import canonical_dataset_digest

DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parent / "datasets" / "verifier_v4_manifest.json"

FROZEN_ARCHITECTURE = "AB2"
FROZEN_VERIFIER_PROVIDER = "opencode-go"
FROZEN_VERIFIER_MODEL = "deepseek-v4-flash"
FROZEN_VERIFIER_BASE_URL = "https://opencode.ai/zen/go/v1"
FROZEN_VERIFIER_ENDPOINT = "/chat/completions"

PROMPT_NAMES = ("requested_fact_v1", "selector_v1", "extractor_v1")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


@dataclass(frozen=True)
class VerifierV4Manifest:
    experiment_name: str
    dataset_path: str
    dataset_name: str
    dataset_version: str
    dataset_canonical_sha256: str
    architecture: str
    verifier_provider: str
    verifier_model: str
    verifier_base_url: str
    verifier_endpoint: str
    prompt_digests: dict[str, str]
    frozen: bool
    query_count: int
    answerable_count: int
    unsupported_count: int
    expected_verifier_calls: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_manifest(path: str | Path = DEFAULT_MANIFEST_PATH) -> VerifierV4Manifest:
    with open(path, encoding="utf-8") as handle:
        return VerifierV4Manifest(**json.load(handle))


def current_prompt_digests() -> dict[str, str]:
    from app.evaluation.verifier_attribute_binding_prompts import EXTRACTOR_PROMPT_V1
    from app.evaluation.verifier_requested_fact_prompts import (
        REQUESTED_FACT_PROMPT_V1,
        REQUESTED_FACT_SELECTOR_PROMPT_V1,
    )

    return {
        "requested_fact_v1": _sha256(REQUESTED_FACT_PROMPT_V1),
        "selector_v1": _sha256(REQUESTED_FACT_SELECTOR_PROMPT_V1),
        "extractor_v1": _sha256(EXTRACTOR_PROMPT_V1),
    }


def frozen_contract_violations(
    manifest: VerifierV4Manifest,
    *,
    dataset_path: str | Path,
    architecture: str,
    verifier_provider: str,
    verifier_model: str,
    verifier_base_url: str,
    verifier_endpoint: str,
    allow_external_api: bool,
    confirm_frozen_v4: bool,
    api_key_available: bool,
) -> list[str]:
    failures: list[str] = []
    if not manifest.frozen:
        failures.append("manifest is not marked frozen")
    actual_sha = canonical_dataset_digest(dataset_path)
    if actual_sha != manifest.dataset_canonical_sha256:
        failures.append(
            "dataset canonical checksum mismatch: "
            f"manifest={manifest.dataset_canonical_sha256} actual={actual_sha}"
        )
    actual_prompts = current_prompt_digests()
    for name, expected in manifest.prompt_digests.items():
        actual = actual_prompts.get(name)
        if actual != expected:
            failures.append(f"prompt {name!r} digest mismatch: manifest={expected} actual={actual}")
    if actual_prompts.keys() != manifest.prompt_digests.keys():
        failures.append("prompt digest name set changed since freeze")
    comparisons = (
        (architecture, manifest.architecture, "architecture"),
        (verifier_provider, manifest.verifier_provider, "verifier provider"),
        (verifier_model, manifest.verifier_model, "verifier model"),
        (verifier_base_url.rstrip("/"), manifest.verifier_base_url, "verifier base URL"),
        (verifier_endpoint, manifest.verifier_endpoint, "verifier endpoint"),
    )
    for actual, expected, label in comparisons:
        if actual != expected:
            failures.append(f"{label} mismatch: manifest={expected} requested={actual}")
    if not allow_external_api:
        failures.append("external API opt-in missing: pass --allow-external-api")
    if not confirm_frozen_v4:
        failures.append("frozen v4 confirmation missing: pass --run-frozen-v4")
    if not api_key_available:
        failures.append("OPENCODE_GO_API_KEY is unavailable")
    return failures
