from app.domain.rag import ExtractedPage, TextChunk


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
        text = page.text.strip()
        start = 0
        while start < len(text):
            end = min(start + target_size, len(text))
            if end < len(text):
                boundary = text.rfind(" ", start, end)
                if boundary > start:
                    end = boundary
            content = text[start:end].strip()
            if content:
                chunks.append(
                    TextChunk(
                        page_number=page.page_number,
                        chunk_index=chunk_index,
                        content=content,
                    )
                )
                chunk_index += 1
            if end >= len(text):
                break
            next_start = max(end - overlap, start + 1)
            while next_start < len(text) and text[next_start].isspace():
                next_start += 1
            start = next_start
    return chunks
