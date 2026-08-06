import pytest
from pydantic import ValidationError

from app.config import Settings, settings


def test_generation_stale_after_seconds_default_is_positive():
    assert settings.generation_stale_after_seconds == 900
    assert settings.generation_stale_after_seconds > 0


@pytest.mark.parametrize("invalid", [0, -1, -900])
def test_generation_stale_after_seconds_rejects_non_positive(invalid: int):
    with pytest.raises(ValidationError):
        Settings(generation_stale_after_seconds=invalid)


def test_generation_stale_after_seconds_accepts_positive():
    assert Settings(generation_stale_after_seconds=1).generation_stale_after_seconds == 1


def test_comparison_settings_defaults_are_safe():
    assert settings.comparison_provider == "mock"
    assert settings.comparison_max_context_chars > 0
    assert settings.comparison_max_focus_length == 500
    assert settings.comparison_max_sources_per_item > 0
    assert settings.comparison_excerpt_chars > 0


@pytest.mark.parametrize("invalid", [0, -1, -120000])
def test_comparison_max_context_rejects_non_positive(invalid: int):
    with pytest.raises(ValidationError):
        Settings(comparison_max_context_chars=invalid)


@pytest.mark.parametrize("invalid", [0, -1])
@pytest.mark.parametrize(
    "field",
    [
        "comparison_max_focus_length",
        "comparison_max_sources_per_item",
        "comparison_excerpt_chars",
    ],
)
def test_comparison_integer_settings_reject_non_positive(field: str, invalid: int):
    with pytest.raises(ValidationError):
        Settings(**{field: invalid})  # type: ignore[arg-type]


def test_comparison_max_focus_length_accepts_positive():
    assert Settings(comparison_max_focus_length=1).comparison_max_focus_length == 1
