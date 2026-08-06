"""Tests for the PoC 3F-B fresh v2 verifier holdout.

Covers: v2 dataset schema and class/scope balance, freshness (no v1 identity
reuse), ground-truth and marker invariants, the frozen manifest contract
(checksum, prompt version, provider/model, embedding config, retrieval config),
and the external v2 gate that refuses to run before any network call. No real
model API is ever contacted; the retrieval preflight path is proven to perform
zero verifier calls.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.evaluation import verifier_dataset, verifier_manifest, verifier_preflight
from app.evaluation.dataset import load_dataset as load_v1

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATASET_PATH = BACKEND_DIR / "app" / "evaluation" / "datasets" / "verifier_holdout_v2.json"
V1_DATASET_PATH = BACKEND_DIR / "app" / "evaluation" / "datasets" / "retrieval_v1.json"
MANIFEST_PATH = BACKEND_DIR / "app" / "evaluation" / "datasets" / "verifier_v2_manifest.json"

V1_ENTITY_NAMES = ("Northstar", "Orion", "Meridian")
KNOWN_ANSWER_TOKENS = (
    "eight hundred fifty",
    "one hundred seventy-five",
    "twenty percent",
    "four business hours",
    "three to five business days",
)


@pytest.fixture(scope="module")
def v2_dataset():
    return verifier_dataset.load_verifier_holdout_dataset(DATASET_PATH)


@pytest.fixture(scope="module")
def v1_dataset():
    return load_v1(V1_DATASET_PATH)


@pytest.fixture(scope="module")
def manifest():
    return verifier_manifest.load_manifest(MANIFEST_PATH)


# ---------------------------------------------------------------------------
# Dataset schema and balance
# ---------------------------------------------------------------------------


class TestV2Schema:
    def test_v2_dataset_loads_and_validates(self, v2_dataset):
        assert v2_dataset["dataset_version"] == "2"

    def test_v2_query_count_is_24(self, v2_dataset):
        assert len(v2_dataset["queries"]) == verifier_dataset.V2_QUERY_COUNT == 24

    def test_v2_class_balance_12_12(self, v2_dataset):
        summary = verifier_dataset.dataset_summary(v2_dataset)
        assert summary["answerable"] == verifier_dataset.V2_ANSWERABLE_COUNT == 12
        assert summary["unanswerable"] == verifier_dataset.V2_UNSUPPORTED_COUNT == 12

    def test_v2_scope_balance_8_8_8(self, v2_dataset):
        summary = verifier_dataset.dataset_summary(v2_dataset)
        assert (
            summary["scopes"]
            == verifier_dataset.V2_SCOPE_COUNTS
            == {
                "private": 8,
                "reference": 8,
                "combined": 8,
            }
        )

    def test_v2_4_answerable_4_unsupported_per_scope(self, v2_dataset):
        scopes = ("private", "reference", "combined")
        by_scope = {scope: {"answerable": 0, "unsupported": 0} for scope in scopes}
        for query in v2_dataset["queries"]:
            key = "answerable" if query["answerable"] else "unsupported"
            by_scope[query["scope"]][key] += 1
        for scope in ("private", "reference", "combined"):
            assert by_scope[scope] == {"answerable": 4, "unsupported": 4}, scope

    def test_v2_split_is_fresh_holdout_only(self, v2_dataset):
        assert verifier_dataset.V2_SPLIT == "fresh_holdout"
        for query in v2_dataset["queries"]:
            assert query["evaluation_split"] == "fresh_holdout"
        assert v2_dataset.get("split") == "fresh_holdout"
        splits = {q["evaluation_split"] for q in v2_dataset["queries"]}
        assert splits == {"fresh_holdout"}

    def test_v2_no_dev_training_subsets(self, v2_dataset):
        for query in v2_dataset["queries"]:
            assert query["evaluation_split"] not in {"dev", "train", "test"}

    def test_v2_ground_truth_validity(self, v2_dataset):
        for query in v2_dataset["queries"]:
            if query["answerable"]:
                assert query["expected_relevant_chunks"]
                assert query["expected_relevant_documents"]
                assert query["expected_source_kinds"]
            else:
                assert not query["expected_relevant_chunks"]
                assert not query["expected_relevant_documents"]
                assert not query["expected_source_kinds"]

    def test_v2_ground_truth_scope_valid(self, v2_dataset):
        verifier_dataset.validate_verifier_holdout_dataset(v2_dataset)

    def test_v2_no_benchmark_markers_in_content(self, v2_dataset):
        texts = []
        for user in v2_dataset["users"].values():
            for space in user["spaces"].values():
                for doc in space["documents"].values():
                    texts.extend(page["text"] for page in doc["pages"])
        for doc in v2_dataset["reference_documents"].values():
            texts.extend(page["text"] for page in doc["pages"])
        for query in v2_dataset["queries"]:
            texts.append(query["question"])
        for marker in verifier_dataset.FORBIDDEN_MARKERS:
            assert not any(marker in text for text in texts), marker

    def test_v2_semantic_ids_never_leak_into_questions(self, v2_dataset):
        semantic_ids = set()
        for user in v2_dataset["users"].values():
            for space in user["spaces"].values():
                for doc in space["documents"].values():
                    semantic_ids.update(page["semantic_id"] for page in doc["pages"])
        for doc in v2_dataset["reference_documents"].values():
            semantic_ids.update(page["semantic_id"] for page in doc["pages"])
        for query in v2_dataset["queries"]:
            for semantic_id in semantic_ids:
                assert semantic_id not in query["question"]

    def test_v2_document_titles_do_not_encode_answers(self, v2_dataset):
        titles = [doc["title"] for doc in v2_dataset["reference_documents"].values()]
        titles += [
            doc["filename"]
            for user in v2_dataset["users"].values()
            for space in user["spaces"].values()
            for doc in space["documents"].values()
        ]
        for title in titles:
            for token in KNOWN_ANSWER_TOKENS:
                assert token not in title, (title, token)

    def test_v2_has_long_multi_chunk_design(self, v2_dataset):
        from app.application.chunking import chunk_pages
        from app.domain.rag import ExtractedPage

        rental_page = v2_dataset["users"]["user_c"]["spaces"]["user_c_rentals"]["documents"][
            "user_c_rental_agreement"
        ]["pages"][0]
        software_page = v2_dataset["reference_documents"]["reference_software"]["pages"][0]
        chunks_a = chunk_pages([ExtractedPage(1, rental_page["text"])], 800, 120)
        chunks_b = chunk_pages([ExtractedPage(1, software_page["text"])], 800, 120)
        assert len(chunks_a) >= 2
        assert len(chunks_b) >= 2
        delivery_index = next(i for i, c in enumerate(chunks_a) if "twelfth of May" in c.content)
        response_index = next(
            i for i, c in enumerate(chunks_b) if "four business hours" in c.content
        )
        assert delivery_index >= 1
        assert response_index >= 1

    def test_v2_answerable_required_class_mix_present(self, v2_dataset):
        categories = {q["category"] for q in v2_dataset["queries"] if q["answerable"]}
        required = {
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
        assert required == categories

    def test_v2_unsupported_difficulty_classes_present(self, v2_dataset):
        categories = {q["category"] for q in v2_dataset["queries"] if not q["answerable"]}
        assert "unsupported_related_topic" in categories
        assert "unsupported_wrong_fact" in categories
        assert "unsupported_specificity_mismatch" in categories
        assert "unsupported_temporal_mismatch" in categories
        assert "unsupported_numeric_mismatch" in categories
        assert "unsupported_combined_near_miss" in categories
        assert "unsupported_semantic_distractor" in categories
        assert "unsupported_cross_document" in categories

    def test_v2_cross_user_and_cross_space_decoy_present(self, v2_dataset):
        forbidden_by_scope = {"cross_user": False, "cross_space": False}
        documents = verifier_dataset.collect_documents(v2_dataset)
        space_user = {
            space_key: user_key
            for user_key, user in v2_dataset["users"].items()
            for space_key in user["spaces"]
        }
        for query in v2_dataset["queries"]:
            for forbidden in query.get("forbidden_documents") or []:
                doc = documents.get(forbidden)
                if doc is None or doc["kind"] == "reference":
                    continue
                if doc["user"] != space_user.get(query["space"]):
                    forbidden_by_scope["cross_user"] = True
                elif doc["space"] != query["space"]:
                    forbidden_by_scope["cross_space"] = True
        assert forbidden_by_scope["cross_user"]
        assert forbidden_by_scope["cross_space"]


# ---------------------------------------------------------------------------
# Freshness (v1 identity isolation)
# ---------------------------------------------------------------------------


class TestFreshness:
    def test_no_exact_v1_question_reuse(self, v2_dataset, v1_dataset):
        v2_questions = {
            verifier_dataset.normalized_text(q["question"]) for q in v2_dataset["queries"]
        }
        v1_questions = {
            verifier_dataset.normalized_text(q["question"]) for q in v1_dataset["queries"]
        }
        assert v2_questions & v1_questions == set()

    def test_no_v1_semantic_ids_reused(self, v2_dataset, v1_dataset):
        v2_ids = verifier_dataset.collect_v1_identities(v2_dataset)
        v1_ids = verifier_dataset.collect_v1_identities(v1_dataset)
        assert v2_ids["page_ids"] & v1_ids["page_ids"] == set()

    def test_no_v1_fixture_document_ids_reused(self, v2_dataset, v1_dataset):
        v2_ids = verifier_dataset.collect_v1_identities(v2_dataset)
        v1_ids = verifier_dataset.collect_v1_identities(v1_dataset)
        assert v2_ids["document_ids"] & v1_ids["document_ids"] == set()

    def test_no_v1_user_ids_reused(self, v2_dataset, v1_dataset):
        v2_ids = verifier_dataset.collect_v1_identities(v2_dataset)
        v1_ids = verifier_dataset.collect_v1_identities(v1_dataset)
        assert v2_ids["user_ids"] & v1_ids["user_ids"] == set()

    def test_no_exact_v1_page_text_reuse(self, v2_dataset, v1_dataset):
        assert verifier_dataset.freshness_errors(v2_dataset, v1_dataset) == []

    def test_v1_entity_names_absent_from_v2(self, v2_dataset):
        texts = []
        for user in v2_dataset["users"].values():
            for space in user["spaces"].values():
                for doc in space["documents"].values():
                    texts.extend(page["text"] for page in doc["pages"])
        for doc in v2_dataset["reference_documents"].values():
            texts.extend(page["text"] for page in doc["pages"])
        for query in v2_dataset["queries"]:
            texts.append(query["question"])
        combined = " ".join(texts)
        for name in V1_ENTITY_NAMES:
            assert name not in combined


# ---------------------------------------------------------------------------
# Frozen manifest contract
# ---------------------------------------------------------------------------


class TestManifest:
    def test_manifest_loads(self, manifest):
        assert manifest.experiment_name == "poc_3f_b_verifier_v2_fresh_holdout"

    def test_manifest_dataset_path(self, manifest):
        assert manifest.dataset_path == "app/evaluation/datasets/verifier_holdout_v2.json"
        assert manifest.dataset_name == "verifier_holdout_v2"

    def test_manifest_checksum_matches_dataset_content(self, manifest):
        actual = verifier_dataset.canonical_dataset_digest(DATASET_PATH)
        assert manifest.dataset_canonical_sha256 == actual
        assert len(manifest.dataset_canonical_sha256) == 64

    def test_manifest_checksum_round_trip_self_consistent(self, manifest):
        data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        computed = verifier_dataset.canonical_json_digest(data)
        assert manifest.dataset_canonical_sha256 == computed

    def test_manifest_prompt_version_matches_frozen(self, manifest):
        from app.evaluation.verifier_prompt import VERIFIER_PROMPT_VERSION

        assert manifest.verifier_prompt_version == VERIFIER_PROMPT_VERSION == "1"
        assert manifest.verifier_prompt_version == verifier_manifest.FROZEN_PROMPT_VERSION

    def test_manifest_provider_model_match(self, manifest):
        assert manifest.verifier_provider == verifier_manifest.FROZEN_VERIFIER_PROVIDER
        assert manifest.verifier_provider == "deepseek"
        assert manifest.verifier_model == verifier_manifest.FROZEN_VERIFIER_MODEL
        assert manifest.verifier_model == "deepseek-chat"

    def test_manifest_embedding_config_match(self, manifest):
        assert manifest.embedding_provider == "local"
        assert manifest.embedding_model == "BAAI/bge-small-en-v1.5"
        assert manifest.embedding_dimension == 384

    def test_manifest_retrieval_config(self, manifest):
        assert manifest.retrieval_top_k == verifier_manifest.FROZEN_TOP_K == 5
        assert manifest.retrieval_threshold == verifier_manifest.FROZEN_THRESHOLD == 0.5

    def test_manifest_frozen_and_counts(self, manifest):
        assert manifest.frozen is True
        assert manifest.dataset_split == "fresh_holdout"
        assert manifest.query_count == 24
        assert manifest.answerable_count == 12
        assert manifest.unsupported_count == 12
        assert manifest.expected_verifier_calls == 24

    def test_manifest_contains_no_secrets(self, manifest):
        serialized = json.dumps(manifest.to_dict())
        assert "api_key" not in serialized.lower()
        assert "DEEPSEEK_API_KEY" not in serialized


# ---------------------------------------------------------------------------
# Frozen v2 gate (pure, fails before network)
# ---------------------------------------------------------------------------


class TestFrozenGate:
    def _matching_kwargs(self, manifest):
        return dict(
            manifest=manifest,
            dataset_path=DATASET_PATH,
            prompt_version=manifest.verifier_prompt_version,
            verifier_provider=manifest.verifier_provider,
            verifier_model=manifest.verifier_model,
            embedding_provider=manifest.embedding_provider,
            embedding_model=manifest.embedding_model,
            embedding_dimension=manifest.embedding_dimension,
            top_k=manifest.retrieval_top_k,
            threshold=manifest.retrieval_threshold,
            allow_external_api=True,
            confirm_frozen_v2=True,
        )

    def test_gate_passes_for_matching_frozen_contract(self, manifest):
        violations = verifier_manifest.frozen_contract_violations(**self._matching_kwargs(manifest))
        assert violations == []

    def test_gate_refuses_semantic_dataset_mutation(self, manifest, tmp_path):
        data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        data["queries"][0]["question"] = "How much damage deposit do I owe if I rent twice?"
        mutated = tmp_path / "semantically_mutated_holdout.json"
        mutated.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        kwargs = self._matching_kwargs(manifest)
        kwargs["dataset_path"] = mutated
        violations = verifier_manifest.frozen_contract_violations(**kwargs)
        assert any("canonical checksum mismatch" in v for v in violations)

    def test_whitespace_only_dataset_change_keeps_canonical_digest(self, tmp_path):
        data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        lf_bytes = json.dumps(data, indent=2).encode("utf-8").replace(b"\r\n", b"\n")
        crlf_bytes = lf_bytes.replace(b"\n", b"\r\n")
        lf_path = tmp_path / "lf.json"
        crlf_path = tmp_path / "crlf.json"
        lf_path.write_bytes(lf_bytes)
        crlf_path.write_bytes(crlf_bytes)
        assert verifier_dataset.canonical_dataset_digest(lf_path) == (
            verifier_dataset.canonical_dataset_digest(crlf_path)
        )

    def test_line_ending_change_alters_raw_bytes_but_not_canonical_digest(self, tmp_path):
        data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        lf_bytes = json.dumps(data, indent=2).encode("utf-8").replace(b"\r\n", b"\n")
        crlf_bytes = lf_bytes.replace(b"\n", b"\r\n")
        lf_path = tmp_path / "lf.json"
        crlf_path = tmp_path / "crlf.json"
        lf_path.write_bytes(lf_bytes)
        crlf_path.write_bytes(crlf_bytes)
        assert verifier_dataset.raw_bytes_sha256(lf_path) != (
            verifier_dataset.raw_bytes_sha256(crlf_path)
        )
        assert verifier_dataset.canonical_dataset_digest(lf_path) == (
            verifier_dataset.canonical_dataset_digest(crlf_path)
        )

    def test_gate_refuses_changed_prompt_version(self, manifest):
        kwargs = self._matching_kwargs(manifest)
        kwargs["prompt_version"] = "2"
        violations = verifier_manifest.frozen_contract_violations(**kwargs)
        assert any("prompt version mismatch" in v for v in violations)

    def test_gate_refuses_wrong_model(self, manifest):
        kwargs = self._matching_kwargs(manifest)
        kwargs["verifier_model"] = "deepseek-reasoner"
        violations = verifier_manifest.frozen_contract_violations(**kwargs)
        assert any("model mismatch" in v for v in violations)

    def test_gate_refuses_wrong_provider(self, manifest):
        kwargs = self._matching_kwargs(manifest)
        kwargs["verifier_provider"] = "mock"
        violations = verifier_manifest.frozen_contract_violations(**kwargs)
        assert any("provider mismatch" in v for v in violations)

    def test_gate_refuses_mock_embeddings(self, manifest):
        kwargs = self._matching_kwargs(manifest)
        kwargs["embedding_provider"] = "mock"
        violations = verifier_manifest.frozen_contract_violations(**kwargs)
        assert any("embedding provider mismatch" in v for v in violations)

    def test_gate_refuses_wrong_embedding_model_or_dimension(self, manifest):
        kwargs = self._matching_kwargs(manifest)
        kwargs["embedding_model"] = "other-model"
        violations = verifier_manifest.frozen_contract_violations(**kwargs)
        assert any("embedding model mismatch" in v for v in violations)
        kwargs = self._matching_kwargs(manifest)
        kwargs["embedding_dimension"] = 768
        violations = verifier_manifest.frozen_contract_violations(**kwargs)
        assert any("embedding dimension mismatch" in v for v in violations)

    def test_gate_refuses_wrong_top_k_and_threshold(self, manifest):
        kwargs = self._matching_kwargs(manifest)
        kwargs["top_k"] = 10
        violations = verifier_manifest.frozen_contract_violations(**kwargs)
        assert any("top_k mismatch" in v for v in violations)
        kwargs = self._matching_kwargs(manifest)
        kwargs["threshold"] = 0.2
        violations = verifier_manifest.frozen_contract_violations(**kwargs)
        assert any("threshold mismatch" in v for v in violations)

    def test_gate_refuses_missing_external_opt_in(self, manifest):
        kwargs = self._matching_kwargs(manifest)
        kwargs["allow_external_api"] = False
        violations = verifier_manifest.frozen_contract_violations(**kwargs)
        assert any("allow-external-api" in v for v in violations)

    def test_gate_refuses_missing_confirmation_flag(self, manifest):
        kwargs = self._matching_kwargs(manifest)
        kwargs["confirm_frozen_v2"] = False
        violations = verifier_manifest.frozen_contract_violations(**kwargs)
        assert any("--run-frozen-v2" in v for v in violations)

    def test_gate_failure_requires_no_network(self, manifest, monkeypatch):

        def _boom(*args, **kwargs):
            raise AssertionError("network call attempted during the frozen gate")

        monkeypatch.setattr("httpx.AsyncClient.post", _boom)
        monkeypatch.setattr("httpx.AsyncClient.get", _boom)
        kwargs = self._matching_kwargs(manifest)
        kwargs["verifier_model"] = "wrong-model"
        kwargs["confirm_frozen_v2"] = False
        violations = verifier_manifest.frozen_contract_violations(**kwargs)
        assert violations  # computed without any network call


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def _load_cli_module():
    script = BACKEND_DIR / "scripts" / "evaluate_verifier.py"
    spec = importlib.util.spec_from_file_location("evaluate_verifier_cli_v2", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestCliV2:
    def test_cli_parses_new_flags(self):
        module = _load_cli_module()
        args = module.parse_args(["--retrieval-preflight"])
        assert args.retrieval_preflight is True
        args = module.parse_args(["--run-frozen-v2"])
        assert args.run_frozen_v2 is True

    def test_cli_load_dataset_dispatches_v2(self):
        module = _load_cli_module()
        data, is_v2 = module.load_dataset_data(DATASET_PATH)
        assert is_v2 is True
        assert data["dataset_version"] == "2"

    def test_cli_v2_external_without_confirmation_is_refused(self):
        module = _load_cli_module()
        args = module.parse_args(
            [
                "--dataset",
                str(DATASET_PATH),
                "--provider",
                "deepseek",
                "--allow-external-api",
                "--embedding-provider",
                "local",
            ]
        )
        assert module.enforce_frozen_v2_contract(args, dataset_is_v2=True) is False

    def test_cli_v2_external_full_gate_passes(self):
        module = _load_cli_module()
        args = module.parse_args(
            [
                "--dataset",
                str(DATASET_PATH),
                "--provider",
                "deepseek",
                "--allow-external-api",
                "--embedding-provider",
                "local",
                "--threshold",
                "0.5",
                "--top-k",
                "5",
                "--verifier-model",
                "deepseek-chat",
                "--run-frozen-v2",
            ]
        )
        assert module.enforce_frozen_v2_contract(args, dataset_is_v2=True) is True

    def test_cli_mock_mode_remains_available_on_v2(self):
        module = _load_cli_module()
        args = module.parse_args(
            [
                "--dataset",
                str(DATASET_PATH),
                "--provider",
                "mock",
                "--embedding-provider",
                "mock",
            ]
        )
        assert module.enforce_frozen_v2_contract(args, dataset_is_v2=True) is True

    def test_cli_preflight_requires_local_embeddings(self, tmp_path, monkeypatch):
        module = _load_cli_module()
        args = module.parse_args(
            [
                "--dataset",
                str(DATASET_PATH),
                "--embedding-provider",
                "mock",
                "--output-dir",
                str(tmp_path),
                "--retrieval-preflight",
            ]
        )
        source_url = __import__("sqlalchemy.engine", fromlist=["make_url"]).make_url(
            "postgresql+asyncpg://documind:documind@localhost:5436/documind"
        )

        async def _run():
            return await module.run_preflight(args, {"dataset_version": "2"}, source_url)

        import asyncio

        assert asyncio.run(_run()) == 2

    def test_cli_preflight_delegates_before_any_verifier(self, monkeypatch, tmp_path):
        module = _load_cli_module()
        called = []

        async def fake_preflight(args, dataset_data, source_url):
            called.append("preflight")
            return 0

        monkeypatch.setattr(module, "run_preflight", fake_preflight)
        monkeypatch.setattr(
            module.verifier_providers,
            "build_verifier_provider",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("verifier provider built during preflight")
            ),
        )
        monkeypatch.setattr(
            module.verifier_eval,
            "run_verifier_evaluation",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("verifier evaluation ran during preflight")
            ),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "evaluate_verifier.py",
                "--dataset",
                str(DATASET_PATH),
                "--retrieval-preflight",
                "--output-dir",
                str(tmp_path),
            ],
        )
        import asyncio

        assert asyncio.run(module.main()) == 0
        assert called == ["preflight"]


# ---------------------------------------------------------------------------
# Preflight module never touches the verifier
# ---------------------------------------------------------------------------


class TestPreflightIsolation:
    def test_preflight_module_has_no_verifier_dependency(self):
        source = Path(verifier_preflight.__file__).read_text(encoding="utf-8")
        tokens = (
            "verifier_providers",
            "DeepSeek",
            "MockEvidenceVerifier",
            "run_verifier_evaluation",
        )
        for token in tokens:
            assert token not in source
        assert "verifier_eval" not in source


# ---------------------------------------------------------------------------
# Dataset negative validation
# ---------------------------------------------------------------------------


class TestV2ValidationRejects:
    def _mutate_and_expect(self, mutation, match):
        data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        mutation(data)
        with pytest.raises(ValueError, match=match):
            verifier_dataset.validate_verifier_holdout_dataset(data)

    def test_reject_duplicate_query_id(self):
        def mutation(data):
            data["queries"][1]["id"] = data["queries"][0]["id"]

        self._mutate_and_expect(mutation, "duplicate query id")

    def test_reject_answerable_without_evidence(self):
        def mutation(data):
            data["queries"][0]["expected_relevant_chunks"] = []
            data["queries"][0]["expected_relevant_documents"] = []
            data["queries"][0]["expected_source_kinds"] = []

        self._mutate_and_expect(mutation, "answerable query has no relevant chunks")

    def test_reject_unsupported_with_evidence(self):
        def mutation(data):
            unsupported = next(q for q in data["queries"] if not q["answerable"])
            unsupported["expected_relevant_chunks"] = ["rental_agreement_handling"]

        self._mutate_and_expect(mutation, "unsupported query lists relevant chunks")

    def test_reject_non_fresh_holdout_split(self):
        def mutation(data):
            data["queries"][0]["evaluation_split"] = "dev"

        self._mutate_and_expect(mutation, "evaluation_split must be 'fresh_holdout'")

    def test_reject_wrong_class_balance(self):
        def mutation(data):
            data["queries"][0]["answerable"] = False

        self._mutate_and_expect(mutation, "expected 12 answerable queries")

    def test_reject_wrong_scope_balance(self):
        def mutation(data):
            data["queries"][0]["scope"] = "reference"

        self._mutate_and_expect(mutation, "scope reference: expected 8 queries")

    def test_reject_cross_scope_expected_evidence(self):
        def mutation(data):
            query = next(q for q in data["queries"] if q["id"] == "v2_priv_deposit_direct")
            query["expected_relevant_chunks"] = ["venue_contract_booking"]
            query["expected_relevant_documents"] = ["user_c_venue_contract"]

        self._mutate_and_expect(mutation, "not available in private scope")

    def test_reject_marker_token_in_text(self):
        def mutation(data):
            doc = data["users"]["user_c"]["spaces"]["user_c_rentals"]["documents"][
                "user_c_rental_agreement"
            ]
            doc["pages"][0]["text"] = doc["pages"][0]["text"] + " EVAL_FACT_99"

        self._mutate_and_expect(mutation, "forbidden marker")

    def test_reject_combined_multi_source_without_both_kinds(self):
        def mutation(data):
            query = next(q for q in data["queries"] if q["id"] == "v2_comb_daily_rate_and_deposit")
            query["expected_source_kinds"] = ["private"]

        self._mutate_and_expect(mutation, "combined_multi_source needs both source kinds")

    def test_reject_unknown_expected_document(self):
        def mutation(data):
            data["queries"][0]["expected_relevant_documents"] = ["ghost_document"]

        self._mutate_and_expect(mutation, "unknown relevant document")

    def test_sha256_is_stable_hex(self):
        digest = verifier_dataset.canonical_dataset_digest(DATASET_PATH)
        assert digest == verifier_dataset.canonical_dataset_digest(DATASET_PATH)
        assert len(digest) == 64
        int(digest, 16)


# ---------------------------------------------------------------------------
# Preflight eligibility computation
# ---------------------------------------------------------------------------


def _chunk(chunk_id: str, kind: str, name: str, score: float):
    from app.domain.rag import RetrievedChunk

    return RetrievedChunk(
        source_id=f"{kind}:{chunk_id}",
        source_kind=kind,
        document_id=f"doc-{chunk_id}",
        document_name=name,
        page_number=1,
        chunk_id=chunk_id,
        content="content",
        score=score,
    )


def _qresult(
    query_id: str,
    answerable: bool,
    scope: str,
    candidates: list,
    expected_chunks: list[str],
    relevant_ranks: list[int],
    required_kinds: list[str],
    kinds_present: list[str],
    forbidden_retrieved: list[str] | None = None,
    cross_user: bool = False,
    cross_space: bool = False,
):
    from app.evaluation.runner import QueryResult

    return QueryResult(
        id=query_id,
        scope=scope,
        category="test",
        space="user_c_rentals",
        answerable=answerable,
        question="question",
        expected_chunks=expected_chunks,
        expected_documents=[],
        forbidden_documents=[],
        required_source_kinds=required_kinds,
        relevant_ranks=relevant_ranks,
        document_relevant_ranks=[],
        first_relevant_rank=relevant_ranks[0] if relevant_ranks else None,
        retrieval_count=len(candidates),
        candidate_documents=[c.document_name for c in candidates],
        candidate_kinds=[c.source_kind for c in candidates],
        candidate_scores=[c.score for c in candidates],
        candidate_relevant=[False] * len(candidates),
        candidate_forbidden=[False] * len(candidates),
        candidate_contents=[c.content for c in candidates],
        candidate_chunks=list(candidates),
        forbidden_retrieved=forbidden_retrieved or [],
        scope_violations=[],
        source_kinds_present=kinds_present,
        has_cross_user_forbidden=cross_user,
        has_cross_space_forbidden=cross_space,
    )


class TestPreflightEligibility:
    def test_compute_eligibility_aggregates_correctly(self):
        from app.evaluation.runner import Corpus

        corpus = Corpus(dataset_version="2")
        corpus.chunk_to_pages = {"c1": ["page_a"], "c2": ["page_b"]}
        results = [
            _qresult(
                "a1",
                True,
                "private",
                [_chunk("c1", "private", "doc", 0.8)],
                ["page_a"],
                [1],
                ["private"],
                ["private"],
            ),
            _qresult(
                "a2",
                True,
                "private",
                [],
                ["page_b"],
                [],
                ["private"],
                [],
            ),
            _qresult(
                "u1",
                False,
                "private",
                [_chunk("c1", "private", "doc", 0.7)],
                [],
                [],
                [],
                ["private"],
            ),
            _qresult(
                "u2",
                False,
                "private",
                [],
                [],
                [],
                [],
                [],
            ),
            _qresult(
                "m1",
                True,
                "combined",
                [_chunk("c1", "private", "doc", 0.8), _chunk("c2", "reference", "ref", 0.7)],
                ["page_a"],
                [1],
                ["private", "reference"],
                ["private", "reference"],
            ),
            _qresult(
                "leak",
                False,
                "private",
                [_chunk("c1", "private", "doc", 0.8)],
                [],
                [],
                [],
                ["private"],
                forbidden_retrieved=["other_doc"],
                cross_user=True,
            ),
        ]
        eligibility = verifier_preflight.compute_eligibility(corpus, results)
        assert eligibility["run_mode"] == "retrieval_preflight"
        assert eligibility["query_count"] == 6
        assert eligibility["answerable_count"] == 3
        assert eligibility["unsupported_count"] == 3
        assert eligibility["answerable_with_all_expected_in_top5"] == 2
        assert eligibility["answerable_hit_at_5"] == 0.6667
        assert eligibility["unsupported_with_candidates"] == 2
        assert eligibility["security"]["cross_user_leaked"] == 1
        assert eligibility["security"]["cross_space_leaked"] == 0
        assert eligibility["combined_required"] == 1
        assert eligibility["combined_source_coverage"] == 1.0
        assert eligibility["eligible_to_freeze"] is False  # leakage + missing coverage

    def test_query_eligibility_marks_missing_expected_chunks(self):
        from app.evaluation.runner import Corpus

        corpus = Corpus(dataset_version="2")
        corpus.chunk_to_pages = {"c1": ["page_a"]}
        result = _qresult(
            "q1",
            True,
            "private",
            [_chunk("c1", "private", "doc", 0.8)],
            ["page_a", "page_z"],
            [1],
            ["private"],
            ["private"],
        )
        row = verifier_preflight.query_eligibility(corpus, result)
        assert row["all_expected_covered"] is False
        assert row["missing_expected_chunks"] == ["page_z"]

    def test_preflight_report_build_and_render(self, tmp_path):
        eligibility = {
            "run_mode": "retrieval_preflight",
            "query_count": 1,
            "answerable_count": 1,
            "unsupported_count": 0,
            "answerable_hit_at_1": 1.0,
            "answerable_hit_at_3": 1.0,
            "answerable_hit_at_5": 1.0,
            "answerable_with_all_expected_in_top5": 1,
            "unsupported_with_candidates": 0,
            "average_candidate_count": 1.0,
            "answerable_top_score_distribution": {
                "count": 1,
                "mean": 0.8,
                "min": 0.8,
                "max": 0.8,
            },
            "unsupported_top_score_distribution": {
                "count": 0,
                "mean": None,
                "min": None,
                "max": None,
            },
            "combined_required": 0,
            "combined_source_coverage": 0.0,
            "multi_source_candidate_kinds_matched": 0,
            "security": {
                "cross_user_tested": 0,
                "cross_user_leaked": 0,
                "cross_space_tested": 0,
                "cross_space_leaked": 0,
                "scope_violations": [],
            },
            "eligible_to_freeze": True,
            "queries": [],
        }
        report = verifier_preflight.build_preflight_json_report(
            dataset_path=str(DATASET_PATH),
            dataset_canonical_sha256=verifier_dataset.canonical_dataset_digest(DATASET_PATH),
            dataset_version="2",
            embedding_provider="local",
            embedding_model="BAAI/bge-small-en-v1.5",
            embedding_dimension=384,
            top_k=5,
            threshold=0.5,
            corpus_counts={"chunks": 3},
            runtime_seconds=1.5,
            git_commit="abc",
            eligibility=eligibility,
        )
        assert report["benchmark"]["run_mode"] == "retrieval_preflight"
        actual_sha = verifier_dataset.canonical_dataset_digest(DATASET_PATH)
        assert report["benchmark"]["dataset_canonical_sha256"] == actual_sha
        assert "No verifier" in report["note"]
        markdown = verifier_preflight.render_preflight_markdown(report)
        assert "Retrieval Preflight" in markdown
        assert "eligible_to_freeze: **True**" in markdown
        out = tmp_path / "preflight.json"
        verifier_preflight.write_preflight_report(report, out)
        assert json.loads(out.read_text(encoding="utf-8")) == report
