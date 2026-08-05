"""Pure classification metrics for evidence-sufficiency experiments.

Ground truth is *answerability* (does the selected knowledge scope contain the
requested evidence). A query is classified *supported* when the strategy accepts
its retrieved evidence, and *unsupported* when it abstains.

These functions have no I/O and are fully deterministic.

Terminology:

- ``answerable_retention``: among truly answerable queries, how many stay
  accepted (true-positive recall on answerability).
- ``unsupported_detection``: among truly unanswerable queries, how many are
  rejected (true-negative recall on answerability).
- ``supported_precision``: among queries classified supported, how many are
  actually answerable.
- ``unsupported_precision``: among queries classified unsupported, how many are
  actually unanswerable.
- ``false_support``: fraction of unanswerable queries incorrectly accepted.
- ``false_rejection``: fraction of answerable queries incorrectly rejected.
- ``balanced_accuracy``: mean of answerable retention and unsupported detection.
"""

from __future__ import annotations

from collections.abc import Sequence


def classification_counts(
    answerable_flags: Sequence[bool], supported_flags: Sequence[bool]
) -> dict[str, int]:
    """Confusion-style counts from parallel answerable/supported sequences."""
    if len(answerable_flags) != len(supported_flags):
        raise ValueError("answerable and supported sequences must have equal length")
    counts = {"true_positive": 0, "true_negative": 0, "false_positive": 0, "false_negative": 0}
    for answerable, supported in zip(answerable_flags, supported_flags, strict=True):
        if supported:
            if answerable:
                counts["true_positive"] += 1
            else:
                counts["false_positive"] += 1
        else:
            if answerable:
                counts["false_negative"] += 1
            else:
                counts["true_negative"] += 1
    return counts


def _safe(ratio: float) -> float:
    return round(ratio, 4)


def classification_metrics(
    answerable_flags: Sequence[bool], supported_flags: Sequence[bool]
) -> dict[str, float | int]:
    """Compute the full sufficiency classification metric set.

    A strategy that classifies everything unsupported gets perfect unsupported
    detection but zero answerable retention; the caller should always inspect
    both recall-like rates together.
    """
    counts = classification_counts(answerable_flags, supported_flags)
    total = len(answerable_flags)
    tp = counts["true_positive"]
    tn = counts["true_negative"]
    fp = counts["false_positive"]
    fn = counts["false_negative"]

    answerable_total = tp + fn
    unanswerable_total = tn + fp
    supported_total = tp + fp
    unsupported_total = tn + fn

    answerable_retention = tp / answerable_total if answerable_total else 0.0
    unsupported_detection = tn / unanswerable_total if unanswerable_total else 0.0
    supported_precision = tp / supported_total if supported_total else 0.0
    unsupported_precision = tn / unsupported_total if unsupported_total else 0.0
    false_support = fp / unanswerable_total if unanswerable_total else 0.0
    false_rejection = fn / answerable_total if answerable_total else 0.0
    balanced_accuracy = (answerable_retention + unsupported_detection) / 2
    accuracy = (tp + tn) / total if total else 0.0

    return {
        "query_count": total,
        "answerable": answerable_total,
        "unanswerable": unanswerable_total,
        "supported": supported_total,
        "unsupported": unsupported_total,
        "true_positive": tp,
        "true_negative": tn,
        "false_positive": fp,
        "false_negative": fn,
        "answerable_retention": _safe(answerable_retention),
        "unsupported_detection": _safe(unsupported_detection),
        "supported_precision": _safe(supported_precision),
        "unsupported_precision": _safe(unsupported_precision),
        "false_support_rate": _safe(false_support),
        "false_rejection_rate": _safe(false_rejection),
        "balanced_accuracy": _safe(balanced_accuracy),
        "accuracy": _safe(accuracy),
    }
