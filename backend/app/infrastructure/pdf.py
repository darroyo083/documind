import asyncio
import re
from collections import Counter
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.domain.errors import InvalidDocumentError, TextExtractionError
from app.domain.rag import ExtractedPage

_CHROME_MIN_PAGES = 3
_CHROME_LINE_MAX_CHARS = 100
_PAGE_NUMBER_PATTERN = re.compile(
    r"^(?:page\s+|p\.)?\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?$",
    re.IGNORECASE,
)


def _normalize_page_text(text: str) -> str:
    normalized_lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in normalized_lines if line).strip()


def _strip_repeated_chrome(pages: list[ExtractedPage]) -> list[ExtractedPage]:
    """Drop header/footer lines repeated across most pages of a document.

    Running headers, footers, and page numbers pollute every chunk with
    boilerplate that dilutes embeddings and wastes context. A short line is
    treated as document chrome when it appears on at least half of the pages
    (and at least 3 pages); standalone page-number lines ("12", "Page 3 of 9")
    are chrome on any multi-page document. Unique or substantive content is
    never touched.
    """
    if len(pages) < _CHROME_MIN_PAGES:
        return pages

    line_page_counts: Counter[str] = Counter()
    for page in pages:
        for line in set(page.text.splitlines()):
            stripped = line.strip()
            if 0 < len(stripped) <= _CHROME_LINE_MAX_CHARS:
                line_page_counts[stripped] += 1

    threshold = max(_CHROME_MIN_PAGES, (len(pages) + 1) // 2)
    chrome_lines = {line for line, count in line_page_counts.items() if count >= threshold}

    stripped_pages: list[ExtractedPage] = []
    for page in pages:
        remaining = "\n".join(
            line
            for line in page.text.splitlines()
            if line.strip() not in chrome_lines and not _PAGE_NUMBER_PATTERN.match(line.strip())
        ).strip()
        stripped_pages.append(ExtractedPage(page_number=page.page_number, text=remaining))
    return stripped_pages


class PdfPageExtractor:
    async def extract(self, path: Path) -> list[ExtractedPage]:
        return await asyncio.to_thread(self._extract_sync, path)

    def _extract_sync(self, path: Path) -> list[ExtractedPage]:
        try:
            reader = PdfReader(path, strict=False)
            if reader.is_encrypted:
                raise InvalidDocumentError("Encrypted PDFs are not supported")
            pages = [
                ExtractedPage(
                    page_number=index,
                    text=_normalize_page_text(page.extract_text() or ""),
                )
                for index, page in enumerate(reader.pages, start=1)
            ]
        except InvalidDocumentError:
            raise
        except (PdfReadError, OSError, ValueError, TypeError, KeyError) as exc:
            raise InvalidDocumentError("The uploaded file is not a readable PDF") from exc

        if not pages:
            raise InvalidDocumentError("The PDF contains no pages")
        pages = _strip_repeated_chrome(pages)
        if not any(len(page.text) >= 10 for page in pages):
            raise TextExtractionError(
                "No meaningful text could be extracted. Scanned PDFs are not supported."
            )
        return pages
