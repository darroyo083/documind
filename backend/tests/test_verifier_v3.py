"""Frozen-contract tests for the fresh OpenCode Go verifier holdout v3."""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

from app.evaluation import verifier_dataset, verifier_manifest_v3, verifier_prompt

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATASET_PATH = BACKEND_DIR / "app" / "evaluation" / "datasets" / "verifier_holdout_v3.json"
V2_PATH = BACKEND_DIR / "app" / "evaluation" / "datasets" / "verifier_holdout_v2.json"
V1_PATH = BACKEND_DIR / "app" / "evaluation" / "datasets" / "retrieval_v1.json"


@pytest.fixture(scope="module")
def dataset_data():
    return verifier_dataset.load_verifier_holdout_v3_dataset(DATASET_PATH)


@pytest.fixture(scope="module")
def manifest():
    return verifier_manifest_v3.load_manifest()


class TestV3Structure:
    def test_version_split_and_balance(self, dataset_data):
        assert dataset_data["dataset_version"] == "3"
        assert dataset_data["split"] == "fresh_holdout"
        assert {query["evaluation_split"] for query in dataset_data["queries"]} == {"fresh_holdout"}
        assert len(dataset_data["queries"]) == 24
        assert Counter(query["answerable"] for query in dataset_data["queries"]) == {
            True: 12,
            False: 12,
        }

    def test_scope_balance(self, dataset_data):
        scopes = Counter(query["scope"] for query in dataset_data["queries"])
        assert scopes == {"private": 8, "reference": 8, "combined": 8}
        for scope in scopes:
            scoped = [query for query in dataset_data["queries"] if query["scope"] == scope]
            assert Counter(query["answerable"] for query in scoped) == {True: 4, False: 4}

    def test_fixture_counts_and_security_shape(self, dataset_data):
        summary = verifier_dataset.dataset_summary(dataset_data)
        assert summary["users"] == 2
        assert summary["private_spaces"] == 4
        assert summary["private_documents"] == 6
        assert summary["reference_documents"] == 5
        assert summary["total_pages"] == 16
        assert len(dataset_data["users"]["user_e"]["spaces"]) >= 2
        assert len(dataset_data["users"]["user_f"]["spaces"]) >= 1

    def test_answerable_and_unsupported_gold_contract(self, dataset_data):
        for query in dataset_data["queries"]:
            if query["answerable"]:
                assert query["expected_relevant_chunks"]
                assert query["expected_relevant_documents"]
                assert query["expected_source_kinds"]
            else:
                assert query["expected_relevant_chunks"] == []
                assert query["expected_relevant_documents"] == []
                assert query["expected_source_kinds"] == []

    def test_query_and_semantic_ids_are_unique(self, dataset_data):
        query_ids = [query["id"] for query in dataset_data["queries"]]
        documents = verifier_dataset.collect_documents(dataset_data)
        semantic_ids = [page["semantic_id"] for doc in documents.values() for page in doc["pages"]]
        assert len(query_ids) == len(set(query_ids))
        assert len(semantic_ids) == len(set(semantic_ids))

    def test_nonempty_questions_pages_and_valid_source_kinds(self, dataset_data):
        assert all(query["question"].strip() for query in dataset_data["queries"])
        documents = verifier_dataset.collect_documents(dataset_data)
        assert all(page["text"].strip() for doc in documents.values() for page in doc["pages"])
        assert all(
            set(query["expected_source_kinds"]) <= {"private", "reference"}
            for query in dataset_data["queries"]
        )

    def test_no_marker_leakage(self, dataset_data):
        texts = []
        for document in verifier_dataset.collect_documents(dataset_data).values():
            texts.extend(page["text"] for page in document["pages"])
        texts.extend(query["question"] for query in dataset_data["queries"])
        combined = "\n".join(texts)
        for marker in verifier_dataset.V3_FORBIDDEN_MARKERS:
            assert marker not in combined

    def test_required_design_classes_present(self, dataset_data):
        difficulties = {query["difficulty"] for query in dataset_data["queries"]}
        assert {
            "direct_numeric_fact",
            "date_fact",
            "lexical_mismatch_notice",
            "multi_page_private",
            "later_production_chunk",
            "combined_multi_source",
            "specificity_mismatch",
            "temporal_missing_fact",
            "period_specificity_numeric",
            "cross_document_date_confusion",
        } <= difficulties


class TestV3Freshness:
    @pytest.mark.parametrize("prior_path", [V1_PATH, V2_PATH])
    def test_no_exact_identity_reuse(self, dataset_data, prior_path):
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        current_ids = verifier_dataset.collect_v1_identities(dataset_data)
        prior_ids = verifier_dataset.collect_v1_identities(prior)
        for namespace in ("questions", "page_ids", "document_ids", "user_ids", "page_texts"):
            assert current_ids[namespace].isdisjoint(prior_ids[namespace])


class TestV3Manifest:
    def test_canonical_digest_and_cross_platform_hash(self, manifest, tmp_path):
        assert manifest.dataset_canonical_sha256 == verifier_dataset.canonical_dataset_digest(
            DATASET_PATH
        )
        data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        lf = tmp_path / "lf.json"
        crlf = tmp_path / "crlf.json"
        lf.write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\n")
        crlf.write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\r\n")
        assert verifier_dataset.canonical_dataset_digest(lf) == (
            verifier_dataset.canonical_dataset_digest(crlf)
        )

    def test_frozen_provider_transport_and_prompt(self, manifest):
        assert manifest.verifier_provider == "opencode-go"
        assert manifest.verifier_model == "deepseek-v4-flash"
        assert manifest.verifier_base_url == "https://opencode.ai/zen/go/v1"
        assert manifest.verifier_endpoint == "/chat/completions"
        assert manifest.verifier_prompt_version == verifier_prompt.VERIFIER_PROMPT_VERSION == "1"

    def test_frozen_retrieval_and_counts(self, manifest):
        assert manifest.embedding_provider == "local"
        assert manifest.embedding_model == "BAAI/bge-small-en-v1.5"
        assert manifest.embedding_dimension == 384
        assert manifest.retrieval_top_k == 5
        assert manifest.retrieval_threshold == 0.5
        assert manifest.frozen is True
        assert manifest.query_count == 24
        assert manifest.answerable_count == 12
        assert manifest.unsupported_count == 12
        assert manifest.expected_verifier_calls == 24

    def test_manifest_contains_no_secret(self, manifest):
        serialized = json.dumps(manifest.to_dict())
        assert "api_key" not in serialized.lower()
        assert "OPENCODE_GO_API_KEY" not in serialized


class TestV3Gate:
    def matching(self, manifest):
        return dict(
            manifest=manifest,
            dataset_path=DATASET_PATH,
            prompt_version="1",
            verifier_provider="opencode-go",
            verifier_model="deepseek-v4-flash",
            verifier_base_url="https://opencode.ai/zen/go/v1",
            verifier_endpoint="/chat/completions",
            embedding_provider="local",
            embedding_model="BAAI/bge-small-en-v1.5",
            embedding_dimension=384,
            top_k=5,
            threshold=0.5,
            allow_external_api=True,
            confirm_frozen_v3=True,
            api_key_available=True,
        )

    def test_matching_contract_passes(self, manifest):
        assert verifier_manifest_v3.frozen_contract_violations(**self.matching(manifest)) == []

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("prompt_version", "2", "prompt version"),
            ("verifier_provider", "deepseek", "provider mismatch"),
            ("verifier_model", "deepseek-chat", "model mismatch"),
            ("verifier_base_url", "https://api.deepseek.com", "base URL mismatch"),
            ("verifier_endpoint", "/responses", "endpoint mismatch"),
            ("embedding_provider", "mock", "embedding provider"),
            ("embedding_model", "other", "embedding model"),
            ("embedding_dimension", 768, "embedding dimension"),
            ("top_k", 10, "top_k"),
            ("threshold", 0.2, "threshold"),
            ("allow_external_api", False, "allow-external-api"),
            ("confirm_frozen_v3", False, "run-frozen-v3"),
            ("api_key_available", False, "OPENCODE_GO_API_KEY"),
        ],
    )
    def test_mismatch_fails_without_network(self, manifest, monkeypatch, field, value, message):
        async def fail_network(*args, **kwargs):
            raise AssertionError("network attempted during gate")

        monkeypatch.setattr("httpx.AsyncClient.post", fail_network)
        kwargs = self.matching(manifest)
        kwargs[field] = value
        violations = verifier_manifest_v3.frozen_contract_violations(**kwargs)
        assert any(message in violation for violation in violations)

    def test_semantic_mutation_changes_digest(self, manifest, tmp_path):
        data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        data["queries"][0]["question"] += " tomorrow"
        mutated = tmp_path / "mutated.json"
        mutated.write_text(json.dumps(data), encoding="utf-8")
        kwargs = self.matching(manifest)
        kwargs["dataset_path"] = mutated
        violations = verifier_manifest_v3.frozen_contract_violations(**kwargs)
        assert any("canonical checksum mismatch" in violation for violation in violations)


def load_cli_module():
    path = BACKEND_DIR / "scripts" / "evaluate_verifier.py"
    spec = importlib.util.spec_from_file_location("evaluate_verifier_cli_v3", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestV3Cli:
    def test_v3_dataset_dispatch_and_flag(self):
        module = load_cli_module()
        data, is_v2 = module.load_dataset_data(DATASET_PATH)
        assert data["dataset_version"] == "3"
        assert is_v2 is False
        assert module.parse_args(["--run-frozen-v3"]).run_frozen_v3 is True

    def test_full_gate_passes_with_key(self, monkeypatch):
        module = load_cli_module()
        monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
        args = module.parse_args(
            [
                "--dataset",
                str(DATASET_PATH),
                "--provider",
                "opencode-go",
                "--allow-external-api",
                "--embedding-provider",
                "local",
                "--embedding-model",
                "BAAI/bge-small-en-v1.5",
                "--top-k",
                "5",
                "--threshold",
                "0.5",
                "--verifier-model",
                "deepseek-v4-flash",
                "--run-frozen-v3",
            ]
        )
        assert module.enforce_frozen_v3_contract(args, dataset_is_v3=True) is True

    def test_missing_confirmation_refused_before_provider(self, monkeypatch):
        module = load_cli_module()
        monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
        args = module.parse_args(
            [
                "--dataset",
                str(DATASET_PATH),
                "--provider",
                "opencode-go",
                "--allow-external-api",
                "--embedding-provider",
                "local",
                "--top-k",
                "5",
                "--threshold",
                "0.5",
            ]
        )
        assert module.enforce_frozen_v3_contract(args, dataset_is_v3=True) is False
