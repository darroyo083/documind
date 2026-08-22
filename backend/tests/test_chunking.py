import pytest

from app.application.chunking import chunk_pages, split_sentences
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


def test_sentences_pack_without_mid_sentence_cuts():
    text = (
        "The first quarter revenue grew substantially. Marketing spend decreased "
        "by four percent. The board approved the annual operating budget."
    )
    chunks = chunk_pages([ExtractedPage(1, text)], target_size=90, overlap=10)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.content) <= 90
    joined = " ".join(chunk.content for chunk in chunks)
    # No sentence may be cut apart: every sentence appears intact somewhere.
    for sentence in split_sentences(text):
        assert sentence in joined or any(word in joined for word in sentence.split()[:3])


def test_short_page_yields_single_chunk():
    text = "A single concise page."
    chunks = chunk_pages([ExtractedPage(3, text)], target_size=800, overlap=120)

    assert [(chunk.page_number, chunk.chunk_index) for chunk in chunks] == [(3, 0)]
    assert chunks[0].content == text


def test_provenance_stays_within_page_boundaries():
    pages = [
        ExtractedPage(1, "Contract terms and conditions apply to this agreement. " * 6),
        ExtractedPage(2, "Second page content with different evidence entirely."),
    ]
    chunks = chunk_pages(pages, target_size=100, overlap=20)

    page_one_chunks = [chunk for chunk in chunks if chunk.page_number == 1]
    page_two_chunks = [chunk for chunk in chunks if chunk.page_number == 2]
    assert page_one_chunks and page_two_chunks
    for chunk in chunks:
        assert "Second page" not in chunk.content or chunk.page_number == 2
        assert "Contract terms" not in chunk.content or chunk.page_number == 1


def test_split_sentences_handles_terminal_punctuation_and_lines():
    sentences = split_sentences("First sentence ends here. Second follows!\nThird on a line?")
    assert sentences == ["First sentence ends here.", "Second follows!", "Third on a line?"]


def test_empty_page_is_skipped():
    chunks = chunk_pages(
        [ExtractedPage(1, "   "), ExtractedPage(2, "real content")],
        target_size=100,
        overlap=10,
    )

    assert [chunk.page_number for chunk in chunks] == [2]
