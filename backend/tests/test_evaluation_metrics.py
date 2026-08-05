"""Unit tests for pure evaluation metrics."""

import pytest

from app.evaluation import metrics


class TestHitAtK:
    def test_relevant_at_rank_one(self):
        assert metrics.hit_at_k([1], 1) == 1
        assert metrics.hit_at_k([1], 3) == 1
        assert metrics.hit_at_k([1], 5) == 1

    def test_relevant_beyond_k(self):
        assert metrics.hit_at_k([2], 1) == 0
        assert metrics.hit_at_k([6], 5) == 0
        assert metrics.hit_at_k([4], 3) == 0

    def test_no_relevant(self):
        assert metrics.hit_at_k([], 5) == 0

    def test_multiple_relevant_first_within_k(self):
        assert metrics.hit_at_k([3, 8], 5) == 1
        assert metrics.hit_at_k([8, 9], 5) == 0


class TestRecallAtK:
    def test_one_relevant_retrieved(self):
        assert metrics.recall_at_k([1], 1, 1) == 1.0

    def test_multiple_relevant_partial(self):
        assert metrics.recall_at_k([1, 5], 3, 3) == pytest.approx(1 / 3)

    def test_all_relevant_retrieved(self):
        assert metrics.recall_at_k([1, 2, 3], 5, 3) == 1.0

    def test_zero_retrieval(self):
        assert metrics.recall_at_k([], 5, 3) == 0.0

    def test_zero_total_relevant(self):
        assert metrics.recall_at_k([1], 5, 0) == 0.0


class TestMeanReciprocalRank:
    def test_rank_one(self):
        assert metrics.mean_reciprocal_rank([1]) == 1.0
        assert metrics.mean_reciprocal_rank([1, 4]) == 1.0

    def test_rank_two(self):
        assert metrics.mean_reciprocal_rank([2]) == pytest.approx(0.5)
        assert metrics.mean_reciprocal_rank([2, 3]) == pytest.approx(0.5)

    def test_rank_five(self):
        assert metrics.mean_reciprocal_rank([5]) == pytest.approx(0.2)

    def test_miss(self):
        assert metrics.mean_reciprocal_rank([]) == 0.0


class TestMeanRelevantRank:
    def test_successful(self):
        assert metrics.mean_relevant_rank([2]) == 2.0

    def test_unsuccessful(self):
        assert metrics.mean_relevant_rank([]) is None


class TestUnanswerableRejection:
    def test_all_empty(self):
        assert metrics.unanswerable_rejection_rate([True, True]) == 1.0

    def test_mixed(self):
        assert metrics.unanswerable_rejection_rate([True, False, True]) == pytest.approx(2 / 3)

    def test_all_false_positive(self):
        assert metrics.unanswerable_rejection_rate([False, False]) == 0.0

    def test_empty_input(self):
        assert metrics.unanswerable_rejection_rate([]) == 0.0


class TestLeakageRate:
    def test_no_leakage(self):
        assert metrics.leakage_rate([False, False]) == 0.0

    def test_some_leakage(self):
        assert metrics.leakage_rate([False, True, True]) == pytest.approx(2 / 3)

    def test_all_leakage(self):
        assert metrics.leakage_rate([True]) == 1.0


class TestDocumentHitAtK:
    def test_right_doc_wrong_chunk(self):
        assert metrics.document_hit_at_k([1], 1) == 1

    def test_wrong_doc(self):
        assert metrics.document_hit_at_k([], 5) == 0


class TestCombinedSourceCoverage:
    def test_both_kinds_present(self):
        assert (
            metrics.combined_source_coverage([{"private", "reference"}], {"private", "reference"})
            == 1.0
        )

    def test_missing_kind(self):
        assert metrics.combined_source_coverage([{"private"}], {"private", "reference"}) == 0.0

    def test_partial_coverage(self):
        kinds = [{"private", "reference"}, {"private"}]
        assert metrics.combined_source_coverage(kinds, {"private", "reference"}) == pytest.approx(
            0.5
        )


class TestRecallAndHitRemainDistinct:
    """Hand-calculated cases ensuring Hit@K and macro Recall@K are not conflated."""

    def test_query_a_single_relevant_at_rank_one(self):
        # relevant = [A1], retrieved = [A1]
        assert metrics.recall_at_k([1], 1, 1) == 1.0
        assert metrics.hit_at_k([1], 1) == 1

    def test_query_b_two_relevant_retrieved_across_window(self):
        # relevant = [B1, B2], retrieved = [B1, X, B2] -> ranks [1, 3]
        assert metrics.recall_at_k([1, 3], 1, 2) == 0.5
        assert metrics.recall_at_k([1, 3], 2, 2) == 0.5
        assert metrics.recall_at_k([1, 3], 3, 2) == 1.0
        assert metrics.hit_at_k([1, 3], 1) == 1

    def test_query_c_one_relevant_late(self):
        # relevant = [C1, C2], retrieved = [X, C1] -> ranks [2]
        assert metrics.recall_at_k([2], 1, 2) == 0.0
        assert metrics.recall_at_k([2], 2, 2) == 0.5
        assert metrics.hit_at_k([2], 1) == 0
        assert metrics.hit_at_k([2], 2) == 1

    def test_hit_one_with_recall_half_regression(self):
        # Mandatory regression: Hit@1 = 1.0 while macro Recall@1 = 0.5.
        ranks = [1, 4]
        total_relevant = 2
        assert metrics.hit_at_k(ranks, 1) == 1
        assert metrics.recall_at_k(ranks, 1, total_relevant) == 0.5
        assert metrics.hit_at_k(ranks, 1) != metrics.recall_at_k(ranks, 1, total_relevant)


class TestScoreStatistics:
    def test_empty(self):
        assert metrics.score_statistics([]) == {"count": 0, "mean": None, "min": None, "max": None}

    def test_basic(self):
        stats = metrics.score_statistics([0.2, 0.3, 0.1])
        assert stats["count"] == 3
        assert stats["mean"] == pytest.approx(0.2)
        assert stats["min"] == 0.1
        assert stats["max"] == 0.3
