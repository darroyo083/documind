"""Tests for the PoC 3E evidence-sufficiency evaluation framework.

Covers classification metrics, dev/holdout split validation, the deterministic
tokenizer, candidate strategies, grid search, report generation, and the rule
that the experimental comparison never depends on an answer provider or LLM.
"""

import copy
import inspect
import json
from pathlib import Path

import pytest

from app.evaluation import dataset as ds
from app.evaluation import strategies, sufficiency_eval, sufficiency_metrics, sufficiency_reporting
from app.evaluation import sufficiency as suff

DATASET_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "evaluation" / "datasets" / "retrieval_v1.json"
)


@pytest.fixture(scope="module")
def committed_dataset():
    return ds.load_dataset(DATASET_PATH)


# ---------------------------------------------------------------------------
# Classification metrics
# ---------------------------------------------------------------------------


class TestClassificationMetrics:
    def test_perfect_separation(self):
        metrics = sufficiency_metrics.classification_metrics(
            [True, True, False, False], [True, True, False, False]
        )
        assert metrics["answerable_retention"] == 1.0
        assert metrics["unsupported_detection"] == 1.0
        assert metrics["supported_precision"] == 1.0
        assert metrics["unsupported_precision"] == 1.0
        assert metrics["false_support_rate"] == 0.0
        assert metrics["false_rejection_rate"] == 0.0
        assert metrics["balanced_accuracy"] == 1.0

    def test_reject_everything_detects_all_but_keeps_nothing(self):
        metrics = sufficiency_metrics.classification_metrics(
            [True, True, False, False], [False, False, False, False]
        )
        assert metrics["answerable_retention"] == 0.0
        assert metrics["unsupported_detection"] == 1.0
        assert metrics["supported_precision"] == 0.0
        assert metrics["unsupported_precision"] == 0.5  # 2 of 4 rejected are truly unanswerable
        assert metrics["balanced_accuracy"] == 0.5

    def test_accept_everything_keeps_all_but_detects_nothing(self):
        metrics = sufficiency_metrics.classification_metrics(
            [True, True, False, False], [True, True, True, True]
        )
        assert metrics["answerable_retention"] == 1.0
        assert metrics["unsupported_detection"] == 0.0
        assert metrics["false_support_rate"] == 1.0
        assert metrics["balanced_accuracy"] == 0.5

    def test_balanced_accuracy_is_mean_of_two_rates(self):
        metrics = sufficiency_metrics.classification_metrics(
            [True, True, True, True, False, False], [True, True, True, False, False, False]
        )
        assert metrics["answerable_retention"] == 0.75
        assert metrics["unsupported_detection"] == 1.0
        assert metrics["balanced_accuracy"] == 0.875

    def test_mismatched_lengths_rejected(self):
        with pytest.raises(ValueError):
            sufficiency_metrics.classification_metrics([True], [True, False])

    def test_counts_are_correct(self):
        metrics = sufficiency_metrics.classification_metrics(
            [True, True, True, False, False, False], [True, True, False, False, False, True]
        )
        assert metrics["true_positive"] == 2
        assert metrics["false_negative"] == 1
        assert metrics["true_negative"] == 2
        assert metrics["false_positive"] == 1


# ---------------------------------------------------------------------------
# Dataset split
# ---------------------------------------------------------------------------


class TestSplitValidation:
    def test_committed_dataset_has_valid_split(self, committed_dataset):
        summary = ds.dataset_summary(committed_dataset)
        splits = summary["splits"]
        assert splits["dev"]["answerable"] >= 15
        assert splits["dev"]["unanswerable"] >= 5
        assert splits["holdout"]["answerable"] >= 8
        assert splits["holdout"]["unanswerable"] >= 1

    def test_every_query_has_a_split(self, committed_dataset):
        for query in committed_dataset["queries"]:
            assert query.get("evaluation_split") in {"dev", "holdout"}

    def test_splits_cover_all_scopes(self, committed_dataset):
        for split in ("dev", "holdout"):
            scopes = {
                query["scope"]
                for query in committed_dataset["queries"]
                if query.get("evaluation_split") == split
            }
            assert scopes == {"private", "reference", "combined"}, f"{split} lacks a scope"

    def test_split_rejects_query_without_field(self, committed_dataset):
        mutated = copy.deepcopy(committed_dataset)
        for query in mutated["queries"]:
            query.pop("evaluation_split", None)
        with pytest.raises(ValueError, match="evaluation_split"):
            ds.validate_dataset(mutated)

    def test_split_rejects_unanswerable_only_split(self, committed_dataset):
        mutated = copy.deepcopy(committed_dataset)
        for query in mutated["queries"]:
            query["evaluation_split"] = "dev" if query["answerable"] else "holdout"
        with pytest.raises(ValueError, match="no answerable queries"):
            ds.validate_dataset(mutated)

    def test_no_query_in_both_splits(self, committed_dataset):
        dev = {q["id"] for q in committed_dataset["queries"] if q["evaluation_split"] == "dev"}
        holdout = {
            q["id"] for q in committed_dataset["queries"] if q["evaluation_split"] == "holdout"
        }
        assert not (dev & holdout)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


class TestTokenizer:
    def test_casefold_and_punctuation(self):
        assert suff.tokenize("Cancellation fee: $500.00!") == ["cancellation", "fee", "500", "00"]

    def test_numeric_tokens_preserved(self):
        assert "30" in suff.tokenize("30 days written notice")
        assert "15" in suff.tokenize("due by 15 December")
        assert "500000" in suff.tokenize("up to 500000 francs")

    def test_unicode_aware(self):
        tokens = suff.tokenize("Garantie d'évacuation Züri")
        assert "züri" in tokens
        assert "évacuation" in tokens

    def test_content_tokens_remove_stopwords(self):
        assert "the" not in suff.content_tokens("What is the cancellation fee?")
        assert "cancellation" in suff.content_tokens("What is the cancellation fee?")
        assert "fee" in suff.content_tokens("What is the cancellation fee?")

    def test_content_tokens_keep_question_subject(self):
        tokens = suff.content_tokens("How much notice is required to cancel the policy?")
        assert "notice" in tokens
        assert "cancel" in tokens
        assert "policy" in tokens

    def test_deterministic(self):
        text = "Cancellation requires 30 days written notice before the renewal date."
        assert suff.tokenize(text) == suff.tokenize(text)

    def test_empty_query_coverage_is_one(self):
        signals = suff.compute_signals("", [0.7], ["anything"])
        assert signals.query_content_tokens == 0
        assert signals.lexical_coverage_top1 == 1.0


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


class TestSignals:
    def test_top_scores_and_margin(self):
        signals = suff.compute_signals("What is the cancellation fee?", [0.8, 0.6, 0.4], ["a", "b"])
        assert signals.top1 == 0.8
        assert signals.top2 == 0.6
        assert signals.top3 == 0.4
        assert signals.margin == pytest.approx(0.2)

    def test_lexical_coverage_top1_vs_topk(self):
        # Query content tokens: [cancellation, fee]. The top chunk contains
        # "cancellation" but not "fee", so top1 coverage is 0.5.
        signals = suff.compute_signals(
            "What is the cancellation fee?",
            [0.9],
            ["Cancellation requires written notice."],
        )
        assert signals.lexical_coverage_top1 == 0.5
        assert signals.query_content_tokens == 2
        signals = suff.compute_signals(
            "What is the cancellation fee?",
            [0.9, 0.5],
            ["Cancellation requires written notice.", "The fee is payable in advance."],
        )
        assert signals.lexical_coverage_topk == 1.0  # both tokens in the union

    def test_high_semantic_low_lexical_example(self):
        # The milestone's motivating example: semantic similarity is high but the
        # requested attribute is absent. Query content tokens [cancellation, fee];
        # the evidence contains "cancellation" but not "fee".
        signals = suff.compute_signals(
            "What is the cancellation fee?",
            [0.79],
            ["Cancellation requires 30 days written notice."],
        )
        assert signals.top1 == 0.79
        assert signals.lexical_coverage_top1 == 0.5
        assert signals.lexical_coverage_topk == 0.5

    def test_no_candidates(self):
        signals = suff.compute_signals("any question", [], [])
        assert signals.top1 is None
        assert signals.retrieval_count == 0


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


class TestStrategies:
    def test_max_score_decision(self):
        decision = strategies.evaluate_max_score("q", [0.7], ["x"], threshold=0.65)
        assert decision.supported is True
        assert decision.reason == "sufficient_evidence"
        decision = strategies.evaluate_max_score("q", [0.5], ["x"], threshold=0.65)
        assert decision.supported is False
        assert decision.reason == "low_semantic_support"

    def test_max_score_no_candidates(self):
        decision = strategies.evaluate_max_score("q", [], [], threshold=0.5)
        assert decision.supported is False
        assert decision.reason == "no_candidates"

    def test_score_margin_requires_gap(self):
        decision = strategies.evaluate_score_margin(
            "q", [0.8, 0.79], ["x", "y"], min_score=0.5, margin=0.05
        )
        assert decision.supported is False
        assert decision.reason == "narrow_score_margin"
        decision = strategies.evaluate_score_margin(
            "q", [0.8, 0.7], ["x", "y"], min_score=0.5, margin=0.05
        )
        assert decision.supported is True

    def test_lexical_strategy_requires_coverage(self):
        # Query content tokens: [cancellation, fee]; evidence has cancellation
        # but not fee -> coverage 0.5, below the 0.8 floor.
        decision = strategies.evaluate_lexical_topk(
            "What is the cancellation fee?",
            [0.9],
            ["Cancellation requires written notice."],
            min_coverage=0.8,
        )
        assert decision.supported is False
        assert decision.reason == "insufficient_query_coverage"

    def test_combined_requires_both_floors(self):
        # Semantic score clears the floor but lexical coverage (0.5) does not
        # clear its floor, so the query is rejected.
        decision = strategies.evaluate_combined(
            "What is the cancellation fee?",
            [0.5],
            ["Cancellation requires written notice."],
            min_score=0.5,
            min_coverage=0.8,
        )
        assert decision.supported is False
        assert decision.reason == "insufficient_query_coverage"

    def test_strategies_are_deterministic(self):
        config = strategies.StrategyConfig(
            name="combined", params={"min_score": 0.5, "min_coverage": 0.2}
        )
        first = strategies.evaluate_strategy(config, "q", [0.8], ["evidence here"])
        second = strategies.evaluate_strategy(config, "q", [0.8], ["evidence here"])
        assert first.supported == second.supported
        assert first.reason == second.reason

    def test_unknown_strategy_rejected(self):
        with pytest.raises(ValueError):
            strategies.evaluate_strategy(
                strategies.StrategyConfig(name="nope", params={}), "q", [0.8], ["x"]
            )

    def test_all_strategies_handle_no_candidates(self):
        configs = [
            strategies.StrategyConfig(name="max_score", params={"threshold": 0.5}),
            strategies.StrategyConfig(
                name="score_margin", params={"min_score": 0.5, "margin": 0.1}
            ),
            strategies.StrategyConfig(
                name="score_concentration", params={"min_score": 0.5, "min_lead": 0.1}
            ),
            strategies.StrategyConfig(name="lexical_top1", params={"min_coverage": 0.2}),
            strategies.StrategyConfig(name="lexical_topk", params={"min_coverage": 0.2}),
            strategies.StrategyConfig(
                name="combined", params={"min_score": 0.5, "min_coverage": 0.2}
            ),
        ]
        for config in configs:
            decision = strategies.evaluate_strategy(config, "q", [], [])
            assert decision.supported is False, config.name
            assert decision.reason == "no_candidates", config.name

    def test_score_margin_and_concentration_reject_low_score(self):
        margin = strategies.evaluate_score_margin("q", [0.3], ["x"], min_score=0.5, margin=0.1)
        assert margin.supported is False
        assert margin.reason == "low_semantic_support"
        concentration = strategies.evaluate_score_concentration(
            "q", [0.3], ["x"], min_score=0.5, min_lead=0.1
        )
        assert concentration.supported is False
        assert concentration.reason == "low_semantic_support"

    def test_score_concentration_rejects_narrow_lead(self):
        decision = strategies.evaluate_score_concentration(
            "q", [0.8, 0.7], ["x", "y"], min_score=0.5, min_lead=0.2
        )
        assert decision.supported is False
        assert decision.reason == "low_score_concentration"

    def test_combined_rejects_when_both_weak(self):
        decision = strategies.evaluate_combined(
            "q", [0.4], ["unrelated"], min_score=0.5, min_coverage=0.5
        )
        assert decision.supported is False
        assert decision.reason == "weak_semantic_and_lexical_support"

    def test_combined_rejects_on_semantic_only(self):
        decision = strategies.evaluate_combined(
            "q", [0.4], ["a word here"], min_score=0.5, min_coverage=0.0
        )
        assert decision.supported is False
        assert decision.reason == "low_semantic_support"

    def test_available_strategies_are_stable_and_complete(self):
        names = strategies.available_strategies()
        assert names == [
            "max_score",
            "score_margin",
            "score_concentration",
            "lexical_top1",
            "lexical_topk",
            "combined",
        ]
        assert names == sorted(names, key=strategies.available_strategies().index)


# ---------------------------------------------------------------------------
# Grid search and selection
# ---------------------------------------------------------------------------


def _fake_results(answers):
    """Build minimal QueryResult-like objects with the fields sufficiency uses."""

    from app.evaluation.runner import QueryResult

    results = []
    for entry in answers:
        result = QueryResult(
            id=entry["id"],
            scope=entry.get("scope", "private"),
            category=entry.get("category", "private_direct"),
            space="user_a_insurance",
            answerable=entry["answerable"],
            question=entry["question"],
            expected_chunks=[],
            expected_documents=[],
            forbidden_documents=[],
            required_source_kinds=["private"],
            relevant_ranks=[],
            document_relevant_ranks=[],
            first_relevant_rank=None,
            retrieval_count=len(entry["scores"]),
            candidate_documents=["d"] * len(entry["scores"]),
            candidate_kinds=["private"] * len(entry["scores"]),
            candidate_scores=entry["scores"],
            candidate_relevant=[False] * len(entry["scores"]),
            candidate_forbidden=[False] * len(entry["scores"]),
            candidate_contents=entry["contents"],
        )
        results.append(result)
    return results


class TestGridSearch:
    def test_grid_search_is_deterministic(self):
        results = _fake_results(
            [
                {
                    "id": "q1",
                    "answerable": True,
                    "question": "What notice is required?",
                    "scores": [0.8, 0.7],
                    "contents": ["Notice of 30 days is required.", "other"],
                },
                {
                    "id": "q2",
                    "answerable": False,
                    "question": "What is the cancellation fee?",
                    "scores": [0.79],
                    "contents": ["Cancellation requires 30 days written notice."],
                },
            ]
        )
        split_by_id = {"q1": "dev", "q2": "dev"}
        first = json.dumps(sufficiency_eval.grid_search_dev(results, split_by_id), sort_keys=True)
        second = json.dumps(sufficiency_eval.grid_search_dev(results, split_by_id), sort_keys=True)
        assert first == second

    def test_selector_prefers_simple_high_detection(self):
        rows = [
            {
                # max_score is the baseline; must never be auto-selected
                "name": "max_score",
                "strategy": "max_score(t=0.65)",
                "params": {},
                "answerable_retention": 0.9,
                "unsupported_detection": 0.5,
                "balanced_accuracy": 0.7,
                "supported_precision": 0.9,
                "unsupported_precision": 0.5,
                "false_rejection_rate": 0.1,
                "false_support_rate": 0.5,
                "accuracy": 0.8,
            },
            {
                "name": "lexical_topk",
                "strategy": "lexical_topk(c=0.5)",
                "params": {},
                "answerable_retention": 0.5,
                "unsupported_detection": 1.0,
                "balanced_accuracy": 0.75,
                "supported_precision": 0.5,
                "unsupported_precision": 1.0,
                "false_rejection_rate": 0.5,
                "false_support_rate": 0.0,
                "accuracy": 0.6,
            },
            {
                "name": "combined",
                "strategy": "combined(s=0.5,c=0.1)",
                "params": {},
                "answerable_retention": 0.92,
                "unsupported_detection": 0.6,
                "balanced_accuracy": 0.76,
                "supported_precision": 0.95,
                "unsupported_precision": 0.5,
                "false_rejection_rate": 0.08,
                "false_support_rate": 0.4,
                "accuracy": 0.88,
            },
        ]
        selected = sufficiency_eval.select_strategy(rows)
        assert selected["name"] == "combined"  # max_score baseline excluded

    def test_selector_never_selects_max_score_baseline(self):
        rows = [
            {
                "name": "max_score",
                "strategy": "max_score(t=0.65)",
                "params": {},
                "answerable_retention": 0.95,
                "unsupported_detection": 0.8,
                "balanced_accuracy": 0.875,
                "supported_precision": 0.95,
                "unsupported_precision": 0.6,
                "false_rejection_rate": 0.05,
                "false_support_rate": 0.2,
                "accuracy": 0.9,
            },
        ]
        assert sufficiency_eval.select_strategy(rows) is None

    def test_selector_returns_none_when_nothing_clears_bar(self):
        rows = [
            {
                "name": "max_score",
                "strategy": "max_score(t=0.5)",
                "params": {},
                "answerable_retention": 1.0,
                "unsupported_detection": 0.0,
                "balanced_accuracy": 0.5,
                "supported_precision": 0.8,
                "unsupported_precision": 0.0,
                "false_rejection_rate": 0.0,
                "false_support_rate": 1.0,
                "accuracy": 0.8,
            },
        ]
        assert sufficiency_eval.select_strategy(rows) is None


class TestIntegrationVerdict:
    def test_holdout_collapse_is_rejected(self):
        metrics = {"split:holdout": {"answerable_retention": 0.9, "unsupported_detection": 0.0}}
        verdict = sufficiency_eval.integration_verdict(metrics)
        assert verdict["integrate"] is False
        assert verdict["reason"] == "holdout_detection_collapse"

    def test_holdout_confirmation_accepts(self):
        metrics = {"split:holdout": {"answerable_retention": 0.9, "unsupported_detection": 0.5}}
        verdict = sufficiency_eval.integration_verdict(metrics)
        assert verdict["integrate"] is True

    def test_holdout_retention_loss_is_rejected(self):
        metrics = {"split:holdout": {"answerable_retention": 0.5, "unsupported_detection": 0.5}}
        verdict = sufficiency_eval.integration_verdict(metrics)
        assert verdict["integrate"] is False
        assert verdict["reason"] == "holdout_retention_loss"

    def test_no_selection_is_not_integrated(self):
        verdict = sufficiency_eval.integration_verdict(None)
        assert verdict["integrate"] is False


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


class TestReportGeneration:
    def test_report_with_selected_strategy_renders_holdout_section(self):
        """A selected strategy's full report must render the selected-strategy,
        per-scope, false-rejection, and false-support sections."""
        results = _fake_results(
            [
                {
                    "id": "q1",
                    "answerable": True,
                    "question": "What notice is required?",
                    "scores": [0.8, 0.7],
                    "contents": ["Notice of 30 days is required.", "other"],
                },
                {
                    "id": "q2",
                    "answerable": True,
                    "question": "When is my deposit returned?",
                    "scores": [0.75],
                    "contents": ["Unrelated statement with no keywords."],
                },
                {
                    "id": "q3",
                    "answerable": False,
                    "question": "What is the cancellation fee?",
                    "scores": [0.6],
                    "contents": ["General cancellation policy applies."],
                },
                {
                    "id": "q4",
                    "answerable": False,
                    "question": "What is the cancellation fee?",
                    "scores": [0.79],
                    "contents": ["The cancellation fee is listed in the schedule."],
                },
            ]
        )
        split_by_id = {"q1": "dev", "q2": "dev", "q3": "dev", "q4": "holdout"}
        grid = sufficiency_eval.grid_search_dev(results, split_by_id)
        selected_row = sufficiency_eval.select_strategy(grid)
        assert selected_row is not None, "fixture must yield a selected strategy"
        config = strategies.StrategyConfig(name=selected_row["name"], params=selected_row["params"])
        selected = sufficiency_eval.evaluate_config(config, results, split_by_id)
        verdict = sufficiency_eval.integration_verdict(selected["metrics"])
        report = sufficiency_reporting.build_sufficiency_json_report(
            dataset_version="1",
            embedding_provider="mock",
            embedding_model="deterministic-test",
            embedding_dimension=384,
            top_k=5,
            threshold=0.5,
            baseline={"overall": {"answerable_retention": 1.0, "unsupported_detection": 0.0}},
            grid_search=grid,
            feature_diagnostics=sufficiency_eval.feature_diagnostics(results, split_by_id),
            selected=selected,
            verdict=verdict,
            corpus_counts={"chunks": 3},
            runtime_seconds=1.0,
            git_commit=None,
        )
        markdown = sufficiency_reporting.render_sufficiency_markdown(report)
        assert "## Selected strategy" in markdown
        assert "### Holdout" in markdown
        assert "### Per scope" in markdown
        assert "## False rejections" in markdown
        assert "## False supports" in markdown
        assert "## Integration verdict" in markdown
        assert "Integrate:" in markdown

    def test_report_is_deterministic_and_complete(self):
        results = _fake_results(
            [
                {
                    "id": "q1",
                    "answerable": True,
                    "question": "What notice is required?",
                    "scores": [0.8, 0.7],
                    "contents": ["Notice of 30 days is required.", "other"],
                },
                {
                    "id": "q2",
                    "answerable": False,
                    "question": "What is the cancellation fee?",
                    "scores": [0.79],
                    "contents": ["Cancellation requires 30 days written notice."],
                },
            ]
        )
        split_by_id = {"q1": "dev", "q2": "holdout"}
        grid = sufficiency_eval.grid_search_dev(results, split_by_id)
        diagnostics = sufficiency_eval.feature_diagnostics(results, split_by_id)
        selected_row = sufficiency_eval.select_strategy(grid)
        selected = None
        if selected_row is not None:
            config = strategies.StrategyConfig(
                name=selected_row["name"], params=selected_row["params"]
            )
            selected = sufficiency_eval.evaluate_config(config, results, split_by_id)
        verdict = sufficiency_eval.integration_verdict(selected["metrics"] if selected else None)
        report = sufficiency_reporting.build_sufficiency_json_report(
            dataset_version="1",
            embedding_provider="mock",
            embedding_model="deterministic-test",
            embedding_dimension=384,
            top_k=5,
            threshold=0.5,
            baseline={"overall": {"answerable_retention": 1.0, "unsupported_detection": 0.0}},
            grid_search=grid,
            feature_diagnostics=diagnostics,
            selected=selected,
            verdict=verdict,
            corpus_counts={"chunks": 2},
            runtime_seconds=1.0,
            git_commit=None,
        )
        first = json.dumps(report, sort_keys=True, ensure_ascii=False)
        second = json.dumps(report, sort_keys=True, ensure_ascii=False)
        assert first == second
        markdown = sufficiency_reporting.render_sufficiency_markdown(report)
        assert "Evidence Sufficiency Experiment" in markdown
        assert "DEV strategy comparison" in markdown
        assert "Integration verdict" in markdown
        assert "Recommendation" in markdown
        assert "false_support_rate" in markdown or "Retention" in markdown

    def test_write_json_report_round_trips(self, tmp_path):
        import json

        report = {"benchmark": {"dataset_version": "1"}, "grid_search_dev": []}
        path = tmp_path / "sufficiency.json"
        sufficiency_reporting.write_json_report(report, path)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded == report


# ---------------------------------------------------------------------------
# Holdout isolation methodology
# ---------------------------------------------------------------------------


class TestHoldoutIsolation:
    def test_grid_search_dev_never_consumes_holdout(self):
        """grid_search_dev must only ever evaluate DEV queries."""
        results = _fake_results(
            [
                {
                    "id": "dev_question",
                    "answerable": True,
                    "question": "What notice is required?",
                    "scores": [0.8],
                    "contents": ["Notice of 30 days is required."],
                },
                {
                    "id": "holdout_question",
                    "answerable": False,
                    "question": "What is the cancellation fee?",
                    "scores": [0.79],
                    "contents": ["Cancellation requires 30 days written notice."],
                },
            ]
        )
        split_by_id = {"dev_question": "dev", "holdout_question": "holdout"}
        grid = sufficiency_eval.grid_search_dev(results, split_by_id)
        # DEV metrics must reflect only the dev query (1 answerable, 0 unanswerable).
        assert grid[0]["answerable_retention"] == 1.0
        assert grid[0]["unsupported_detection"] == 0.0
        for row in grid:
            assert row["answerable_retention"] >= 0.0
        # selection from DEV-only grid must never pick based on the holdout query.
        selected = sufficiency_eval.select_strategy(grid)
        assert selected is None or selected["name"] != "max_score"

    def test_evaluate_config_only_applied_to_frozen_strategy(self):
        """Evaluate a single frozen config; it may touch holdout, but no other
        candidate is allowed to be evaluated on holdout by the CLI flow."""
        results = _fake_results(
            [
                {
                    "id": "q1",
                    "answerable": True,
                    "question": "What notice is required?",
                    "scores": [0.8],
                    "contents": ["Notice of 30 days is required."],
                },
                {
                    "id": "q2",
                    "answerable": False,
                    "question": "What is the cancellation fee?",
                    "scores": [0.79],
                    "contents": ["Cancellation requires 30 days written notice."],
                },
            ]
        )
        split_by_id = {"q1": "dev", "q2": "holdout"}
        config = strategies.StrategyConfig(name="lexical_topk", params={"min_coverage": 0.1})
        evaluation = sufficiency_eval.evaluate_config(config, results, split_by_id)
        assert "split:holdout" in evaluation["metrics"]
        assert evaluation["metrics"]["split:holdout"]["unsupported_detection"] == 0.0

    def test_report_has_no_full_grid_of_unselected_strategies(self):
        """The report must not expose holdout metrics for candidate configs."""
        results = _fake_results(
            [
                {
                    "id": "q1",
                    "answerable": True,
                    "question": "What notice is required?",
                    "scores": [0.8],
                    "contents": ["Notice of 30 days is required."],
                },
                {
                    "id": "q2",
                    "answerable": False,
                    "question": "What is the cancellation fee?",
                    "scores": [0.79],
                    "contents": ["Cancellation requires 30 days written notice."],
                },
            ]
        )
        split_by_id = {"q1": "dev", "q2": "holdout"}
        grid = sufficiency_eval.grid_search_dev(results, split_by_id)
        diagnostics = sufficiency_eval.feature_diagnostics(results, split_by_id)
        selected_row = sufficiency_eval.select_strategy(grid)
        selected = None
        if selected_row is not None:
            config = strategies.StrategyConfig(
                name=selected_row["name"], params=selected_row["params"]
            )
            selected = sufficiency_eval.evaluate_config(config, results, split_by_id)
        verdict = sufficiency_eval.integration_verdict(selected["metrics"] if selected else None)
        report = sufficiency_reporting.build_sufficiency_json_report(
            dataset_version="1",
            embedding_provider="mock",
            embedding_model="deterministic-test",
            embedding_dimension=384,
            top_k=5,
            threshold=0.5,
            baseline={"overall": {"answerable_retention": 1.0, "unsupported_detection": 0.0}},
            grid_search=grid,
            feature_diagnostics=diagnostics,
            selected=selected,
            verdict=verdict,
            corpus_counts={"chunks": 2},
            runtime_seconds=1.0,
            git_commit=None,
        )
        assert "full_grid" not in report
        markdown = sufficiency_reporting.render_sufficiency_markdown(report)
        assert "Generalization table" not in markdown
        assert "HOLDOUT ret" not in markdown


def test_no_function_evaluates_every_config_on_holdout():
    """No helper may sweep all candidate configs across the holdout split."""
    source = inspect.getsource(sufficiency_eval)
    assert "full_grid_rows" not in source


# ---------------------------------------------------------------------------
# No provider / no LLM dependency
# ---------------------------------------------------------------------------


def test_sufficiency_evaluation_has_no_provider_dependency():
    sources = [
        inspect.getsource(sufficiency_eval),
        inspect.getsource(strategies),
        inspect.getsource(suff),
        inspect.getsource(sufficiency_metrics),
    ]
    for source in sources:
        assert "AnswerProvider" not in source
        assert "answer_question" not in source
        assert "deepseek" not in source
        assert "httpx" not in source


def test_committed_dataset_counts(committed_dataset):
    summary = ds.dataset_summary(committed_dataset)
    assert summary["answerable"] == 34
    assert summary["unanswerable"] == 9
    assert summary["queries"] == 43
