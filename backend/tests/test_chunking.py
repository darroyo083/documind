import pytest

from app.application.chunking import chunk_pages
from app.domain.rag import ExtractedPage


def test_chunking_preserves_page_numbers_and_deterministic_positions():
    pages = [
        ExtractedPage(1, "alpha beta gamma delta"),
        ExtractedPage(2, "epsilon zeta"),
    ]

    chunks = chunk_pages(pages, target_size=12, overlap=3)

    assert [(chunk.page_number, chunk.chunk_index) for chunk in chunks] == [
        (1, 0),
        (1, 1),
        (1, 2),
        (2, 3),
    ]
    assert chunks[0].content == "alpha beta"
    assert chunks[-1].content == "epsilon zeta"


@pytest.mark.parametrize(
    ("target_size", "overlap"),
    [(0, 0), (10, -1), (10, 10)],
)
def test_chunking_rejects_invalid_configuration(target_size: int, overlap: int):
    with pytest.raises(ValueError):
        chunk_pages([], target_size, overlap)
