"""Document chunking with sentence-aware packing.

Fixed character windows cut text mid-thought, which hurts both embedding
quality and citation readability. This module packs complete sentences into
chunks up to ``target_size``, falls back to word windows only for individual
sentences longer than the target, and honors ``overlap`` by carrying trailing
context forward inside a page. Page provenance never crosses pages: each chunk
records the exact page it came from, so citations remain precise.
"""

import re

from app.domain.rag import ExtractedPage, TextChunk

_SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+(?=[^a-z])|\n+")


def split_sentences(text: str) -> list[str]:
    """Split normalized text into sentence-like units.

    Splits after terminal punctuation followed by whitespace, and on line
    breaks (PDF extraction breaks lines arbitrarily). Returns at least one
    unit for non-empty input.
    """
    units = [unit.strip() for unit in _SENTENCE_PATTERN.split(text) if unit and unit.strip()]
    return units or ([text.strip()] if text.strip() else [])


def _word_window(text: str, start: int, target_size: int) -> tuple[int, int]:
    """Word-boundary window used for oversized sentences."""
    end = min(start + target_size, len(text))
    if end < len(text):
        boundary = text.rfind(" ", start, end)
        if boundary > start:
            end = boundary
    return start, end


def _split_oversized(sentence: str, target_size: int, overlap: int) -> list[str]:
    pieces: list[str] = []
    start = 0
    while start < len(sentence):
        _, end = _word_window(sentence, start, target_size)
        content = sentence[start:end].strip()
        if content:
            pieces.append(content)
        if end >= len(sentence):
            break
        next_start = max(end - overlap, start + 1)
        while next_start < len(sentence) and sentence[next_start].isspace():
            next_start += 1
        start = next_start
    return pieces


def _tail_context(previous: str, overlap: int) -> str:
    """Trailing context (at a word boundary) carried into the next chunk."""
    if overlap <= 0 or not previous:
        return ""
    tail = previous[-overlap:]
    space = tail.find(" ")
    if space != -1:
        tail = tail[space + 1 :]
    return tail.strip()


def chunk_pages(
    pages: list[ExtractedPage],
    target_size: int,
    overlap: int,
) -> list[TextChunk]:
    if target_size <= 0:
        raise ValueError("target_size must be positive")
    if overlap < 0 or overlap >= target_size:
        raise ValueError("overlap must be non-negative and smaller than target_size")

    chunks: list[TextChunk] = []
    chunk_index = 0
    for page in pages:
        text = " ".join(line.strip() for line in page.text.splitlines() if line.strip())
        if not text:
            continue

        units: list[str] = []
        for sentence in split_sentences(text):
            if len(sentence) <= target_size:
                units.append(sentence)
            else:
                units.extend(_split_oversized(sentence, target_size, overlap))

        current: list[str] = []
        current_length = 0

        def flush() -> None:
            nonlocal current, current_length, chunk_index
            content = " ".join(current).strip()
            if content:
                chunks.append(
                    TextChunk(
                        page_number=page.page_number,
                        chunk_index=chunk_index,
                        content=content,
                    )
                )
                chunk_index += 1
            current = []
            current_length = 0

        for unit in units:
            projected = current_length + (1 if current else 0) + len(unit)
            if current and projected > target_size:
                flush()
                tail = _tail_context(chunks[-1].content if chunks else "", overlap)
                if tail and len(tail) + 1 + len(unit) <= target_size:
                    current.append(tail)
                    current_length = len(tail)
            current.append(unit)
            current_length += (1 if current_length else 0) + len(unit)
        flush()
    return chunks
