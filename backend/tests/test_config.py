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
