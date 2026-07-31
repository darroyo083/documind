import asyncio
import re
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.domain.errors import InvalidDocumentError, TextExtractionError
from app.domain.rag import ExtractedPage


def _normalize_page_text(text: str) -> str:
    normalized_lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in normalized_lines if line).strip()


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
        if not any(len(page.text) >= 10 for page in pages):
            raise TextExtractionError(
                "No meaningful text could be extracted. Scanned PDFs are not supported."
            )
        return pages
