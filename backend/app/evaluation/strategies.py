"""Candidate evidence-sufficiency strategies.

Each strategy is a pure function of the question and the retrieved candidates.
Strategies are parameterized so a bounded grid search can tune them on a
development split. No strategy performs retrieval, DB access, or model calls.

Strategies:

- ``max_score``: supported iff top result similarity >= threshold. This is the
  baseline and reproduces why a single global threshold is insufficient.
- ``score_margin``: score floor plus a gap between the best and second-best
  result (a small margin may indicate ambiguous context OR multiple relevant
  chunks, so this is evaluated but not assumed to be strong).
- ``score_concentration``: score floor plus the top result's lead over the mean
  of the remaining results.
- ``lexical_top1``: meaningful query-token coverage of the top chunk.
- ``lexical_topk``: meaningful query-token coverage of the union of all selected
  evidence.
- ``combined``: permissive score floor AND lexical coverage floor. This is the
  only multi-signal deterministic strategy tested here.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.evaluation.sufficiency import (
    SufficiencyDecision,
    SufficiencySignals,
    compute_signals,
)


def _decision(supported: bool, reason: str, signals: SufficiencySignals) -> SufficiencyDecision:
    return SufficiencyDecision(supported=supported, reason=reason, signals=signals)


def _base_signals(
    question: str, scores: list[float], evidence_texts: list[str]
) -> SufficiencySignals:
    return compute_signals(question, scores, evidence_texts)


def evaluate_max_score(
    question: str, scores: list[float], evidence_texts: list[str], threshold: float
) -> SufficiencyDecision:
    signals = _base_signals(question, scores, evidence_texts)
    if signals.top1 is None:
        return _decision(False, "no_candidates", signals)
    if signals.top1 >= threshold:
        return _decision(True, "sufficient_evidence", signals)
    return _decision(False, "low_semantic_support", signals)


def evaluate_score_margin(
    question: str,
    scores: list[float],
    evidence_texts: list[str],
    min_score: float,
    margin: float,
) -> SufficiencyDecision:
    signals = _base_signals(question, scores, evidence_texts)
    if signals.top1 is None:
        return _decision(False, "no_candidates", signals)
    if signals.top1 < min_score:
        return _decision(False, "low_semantic_support", signals)
    if signals.margin is not None and signals.margin < margin:
        return _decision(False, "narrow_score_margin", signals)
    return _decision(True, "sufficient_evidence", signals)


def evaluate_score_concentration(
    question: str,
    scores: list[float],
    evidence_texts: list[str],
    min_score: float,
    min_lead: float,
) -> SufficiencyDecision:
    signals = _base_signals(question, scores, evidence_texts)
    if signals.top1 is None:
        return _decision(False, "no_candidates", signals)
    if signals.top1 < min_score:
        return _decision(False, "low_semantic_support", signals)
    if signals.top1_minus_mean_rest is not None and signals.top1_minus_mean_rest < min_lead:
        return _decision(False, "low_score_concentration", signals)
    return _decision(True, "sufficient_evidence", signals)


def evaluate_lexical_top1(
    question: str, scores: list[float], evidence_texts: list[str], min_coverage: float
) -> SufficiencyDecision:
    signals = _base_signals(question, scores, evidence_texts)
    if signals.top1 is None:
        return _decision(False, "no_candidates", signals)
    if signals.lexical_coverage_top1 < min_coverage:
        return _decision(False, "insufficient_query_coverage", signals)
    return _decision(True, "sufficient_evidence", signals)


def evaluate_lexical_topk(
    question: str, scores: list[float], evidence_texts: list[str], min_coverage: float
) -> SufficiencyDecision:
    signals = _base_signals(question, scores, evidence_texts)
    if signals.top1 is None:
        return _decision(False, "no_candidates", signals)
    if signals.lexical_coverage_topk < min_coverage:
        return _decision(False, "insufficient_query_coverage", signals)
    return _decision(True, "sufficient_evidence", signals)


def evaluate_combined(
    question: str,
    scores: list[float],
    evidence_texts: list[str],
    min_score: float,
    min_coverage: float,
) -> SufficiencyDecision:
    signals = _base_signals(question, scores, evidence_texts)
    if signals.top1 is None:
        return _decision(False, "no_candidates", signals)
    weak_semantic = signals.top1 < min_score
    weak_lexical = signals.lexical_coverage_topk < min_coverage
    if weak_semantic and weak_lexical:
        return _decision(False, "weak_semantic_and_lexical_support", signals)
    if weak_semantic:
        return _decision(False, "low_semantic_support", signals)
    if weak_lexical:
        return _decision(False, "insufficient_query_coverage", signals)
    return _decision(True, "sufficient_evidence", signals)


def available_strategies() -> list[str]:
    """Names of all implemented strategies, in a stable order."""
    return [
        "max_score",
        "score_margin",
        "score_concentration",
        "lexical_top1",
        "lexical_topk",
        "combined",
    ]


@dataclass(frozen=True)
class StrategyConfig:
    name: str
    params: dict[str, float]

    def display(self) -> str:
        ordered = ", ".join(f"{key}={value:g}" for key, value in self.params.items())
        return f"{self.name}({ordered})"


def evaluate_strategy(
    config: StrategyConfig, question: str, scores: list[float], evidence_texts: list[str]
) -> SufficiencyDecision:
    """Dispatch to the right evaluator for a strategy config."""
    name = config.name
    params = config.params
    if name == "max_score":
        return evaluate_max_score(question, scores, evidence_texts, params["threshold"])
    if name == "score_margin":
        return evaluate_score_margin(
            question, scores, evidence_texts, params["min_score"], params["margin"]
        )
    if name == "score_concentration":
        return evaluate_score_concentration(
            question, scores, evidence_texts, params["min_score"], params["min_lead"]
        )
    if name == "lexical_top1":
        return evaluate_lexical_top1(question, scores, evidence_texts, params["min_coverage"])
    if name == "lexical_topk":
        return evaluate_lexical_topk(question, scores, evidence_texts, params["min_coverage"])
    if name == "combined":
        return evaluate_combined(
            question, scores, evidence_texts, params["min_score"], params["min_coverage"]
        )
    raise ValueError(f"Unknown strategy {name!r}")


def strategy_grids() -> dict[str, list[dict[str, float]]]:
    """Bounded parameter grids for each strategy (used for DEV tuning)."""
    return {
        "max_score": [{"threshold": value} for value in (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8)],
        "score_margin": [
            {"min_score": min_score, "margin": margin}
            for min_score in (0.5, 0.6, 0.7)
            for margin in (0.0, 0.05, 0.1, 0.15, 0.2)
        ],
        "score_concentration": [
            {"min_score": min_score, "min_lead": min_lead}
            for min_score in (0.5, 0.6, 0.7)
            for min_lead in (0.0, 0.05, 0.1, 0.15, 0.2)
        ],
        "lexical_top1": [
            {"min_coverage": value} for value in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7)
        ],
        "lexical_topk": [
            {"min_coverage": value} for value in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7)
        ],
        "combined": [
            {"min_score": min_score, "min_coverage": min_coverage}
            for min_score in (0.5, 0.6)
            for min_coverage in (0.1, 0.2, 0.3, 0.4)
        ],
    }
