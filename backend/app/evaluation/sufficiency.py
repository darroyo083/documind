"""Deterministic evidence-sufficiency signals and candidate strategies.

This module is purely computational: it converts a question plus the already
retrieved candidate chunks into a set of cheap, explainable signals and then
applies one of several candidate abstention strategies.

It never performs retrieval, never queries a database, never calls a model, and
never inspects anything beyond the question and the candidates it is given.

Lexical signals use a small, generic English stopword list and a deterministic
Unicode-aware tokenizer. The first production version of lexical coverage is
English-oriented; multilingual robustness is out of scope.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "what",
        "which",
        "who",
        "how",
        "when",
        "where",
        "does",
        "do",
        "did",
        "of",
        "to",
        "in",
        "on",
        "for",
        "and",
        "or",
        "i",
        "my",
        "me",
        "we",
        "our",
        "you",
        "your",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "with",
        "from",
        "by",
        "at",
        "be",
        "can",
        "will",
        "would",
        "should",
        "have",
        "has",
        "had",
        "not",
        "no",
        "yes",
        "about",
        "there",
        "their",
        "they",
        "them",
        "if",
        "as",
        "so",
        "than",
        "then",
        "into",
        "after",
        "before",
        "during",
        "between",
        "over",
        "under",
        "much",
        "many",
        "more",
        "most",
        "out",
        "up",
        "down",
        "back",
        "also",
        "just",
        "some",
        "such",
        "each",
        "every",
        "both",
        "again",
        "away",
        "same",
        "only",
        "other",
        "another",
        "get",
        "got",
        "go",
        "like",
        "via",
        "per",
    }
)

_TOKEN_PATTERN = re.compile(r"[\w]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Deterministic Unicode-aware tokenization.

    - ``casefold`` for lowercase comparison
    - punctuation removed (word characters only, Unicode aware)
    - letters and numbers are preserved, so ``30``, ``1.5`` and ``500000``
      survive as numeric tokens
    - NFC-normalized so composed accents are handled consistently
    """
    normalized = unicodedata.normalize("NFC", text)
    return _TOKEN_PATTERN.findall(normalized.casefold())


def content_tokens(text: str) -> list[str]:
    """Tokens after removing the small generic English stopword set."""
    return [token for token in tokenize(text) if token not in STOPWORDS]


@dataclass(frozen=True)
class SufficiencySignals:
    """Cheap statistics over a question and its retrieved candidates."""

    top1: float | None
    top2: float | None
    top3: float | None
    margin: float | None
    mean_top3: float | None
    mean_top5: float | None
    top1_minus_mean_rest: float | None
    retrieval_count: int
    query_content_tokens: int
    lexical_coverage_top1: float
    lexical_coverage_topk: float


@dataclass(frozen=True)
class SufficiencyDecision:
    supported: bool
    reason: str
    signals: SufficiencySignals


def compute_signals(
    question: str, scores: list[float], evidence_texts: list[str]
) -> SufficiencySignals:
    """Compute signals from retrieval candidates already ordered best-first.

    ``scores`` and ``evidence_texts`` must be aligned (same index). The top
    candidate is scores[0]. Lexical coverage compares the meaningful query
    tokens against the top chunk (top1) and against the union of all provided
    evidence (topK).
    """
    query_tokens = content_tokens(question)
    top1 = scores[0] if scores else None
    top2 = scores[1] if len(scores) > 1 else None
    top3 = scores[2] if len(scores) > 2 else None
    margin = (top1 - top2) if top1 is not None and top2 is not None else None
    mean_top3 = _mean(scores[:3])
    mean_top5 = _mean(scores[:5])
    rest = scores[1:]
    rest_mean = _mean(rest)
    top1_minus_mean_rest = (
        (top1 - rest_mean) if top1 is not None and rest_mean is not None else None
    )

    evidence_token_sets = [set(tokenize(text)) for text in evidence_texts]
    top1_tokens = set(evidence_token_sets[0]) if evidence_token_sets else set()
    union_tokens: set[str] = set()
    for token_set in evidence_token_sets:
        union_tokens |= token_set

    lexical_coverage_top1 = _coverage(query_tokens, top1_tokens)
    lexical_coverage_topk = _coverage(query_tokens, union_tokens)
    return SufficiencySignals(
        top1=top1,
        top2=top2,
        top3=top3,
        margin=margin,
        mean_top3=mean_top3,
        mean_top5=mean_top5,
        top1_minus_mean_rest=top1_minus_mean_rest,
        retrieval_count=len(scores),
        query_content_tokens=len(query_tokens),
        lexical_coverage_top1=lexical_coverage_top1,
        lexical_coverage_topk=lexical_coverage_topk,
    )


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _coverage(query_tokens: list[str], evidence_tokens: set[str]) -> float:
    """Fraction of meaningful query tokens present in the evidence token set."""
    if not query_tokens:
        return 1.0
    matched = sum(1 for token in query_tokens if token in evidence_tokens)
    return round(matched / len(query_tokens), 4)


class SufficiencyStrategy(Protocol):
    """A candidate evidence-sufficiency strategy.

    ``evaluate`` is pure and deterministic given the same inputs.
    """

    name: str

    def evaluate(
        self, question: str, scores: list[float], evidence_texts: list[str]
    ) -> SufficiencyDecision: ...
