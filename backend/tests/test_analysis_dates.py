import pytest

from app.infrastructure.analysis_providers import (
    important_date_normalized,
    parse_exact_date,
)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("31 January 2027", "2027-01-31"),
        ("January 31 2027", "2027-01-31"),
        ("Jan 31, 2027", "2027-01-31"),
        ("1 September 2026", "2026-09-01"),
        ("2027-01-31", "2027-01-31"),
        ("31/01/2027", "2027-01-31"),
        ("31-01-2027", "2027-01-31"),
    ],
)
def test_parse_exact_date_accepts_full_dates(expression: str, expected: str):
    assert parse_exact_date(expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "January 2027",
        "within 30 days of receipt",
        "Q3 2027",
        "12/03/2027",
        "2027-02-30",
        "31/13/2027",
        "",
    ],
)
def test_parse_exact_date_rejects_partial_or_invalid(expression: str):
    assert parse_exact_date(expression) is None


def test_important_date_normalized_accepts_matching_suggestion():
    assert important_date_normalized("31 January 2027", "2027-01-31") == "2027-01-31"


def test_important_date_normalized_derives_when_no_suggestion():
    assert important_date_normalized("31 January 2027", None) == "2027-01-31"


def test_important_date_normalized_discards_unsupported_suggestion():
    assert important_date_normalized("January 2027", "2027-01-31") is None


def test_important_date_normalized_keeps_partial_null():
    assert important_date_normalized("January 2027", None) is None


def test_important_date_normalized_rejects_contradiction():
    with pytest.raises(ValueError):
        important_date_normalized("31 January 2027", "2027-01-01")


def test_important_date_normalized_rejects_malformed():
    with pytest.raises(ValueError):
        important_date_normalized("31 January 2027", "not-a-date")
