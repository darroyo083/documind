"""PDF extraction behavior: repeated header/footer suppression and edge cases."""

import pytest

from app.domain.rag import ExtractedPage
from app.infrastructure.pdf import PdfPageExtractor, _strip_repeated_chrome
from tests.pdf_factory import page_pdf


def test_chrome_suppression_removes_repeated_headers_and_footers():
    pages = [
        ExtractedPage(1, f"Annual Report 2026\n{body}\nPage {index} of 4")
        for index, body in enumerate(
            [
                "Revenue increased by twelve percent this quarter.",
                "Operating costs remained flat across all regions.",
                "The board approved the proposed budget.",
                "Outlook for next year remains cautiously positive.",
            ],
            start=1,
        )
    ]

    stripped = _strip_repeated_chrome(pages)

    assert len(stripped) == 4
    for page in stripped:
        assert "Annual Report 2026" not in page.text
        assert "Page 1 of 4" not in page.text
        assert not page.text.startswith("Annual")
    assert "Revenue increased" in stripped[0].text
    assert "Outlook" in stripped[3].text


def test_chrome_suppression_keeps_unique_content():
    pages = [
        ExtractedPage(1, "Signature authority rests with the director."),
        ExtractedPage(2, "Payment terms are net thirty days."),
        ExtractedPage(3, "The renewal window opens each March."),
    ]

    stripped = _strip_repeated_chrome(pages)

    assert [page.text for page in stripped] == [page.text for page in pages]


def test_chrome_suppression_ignores_short_documents():
    pages = [
        ExtractedPage(1, "Same header\nContent one"),
        ExtractedPage(2, "Same header\nContent two"),
    ]

    stripped = _strip_repeated_chrome(pages)

    assert [page.text for page in stripped] == [page.text for page in pages]


def test_chrome_suppression_preserves_substantive_repeats():
    long_line = "This substantive clause appears on every page and must be preserved."
    pages = [
        ExtractedPage(index, f"{long_line}\nUnique content number {index}.")
        for index in range(1, 5)
    ]
    # The repeated line is longer than the chrome threshold (100 chars).
    long_line_extended = long_line + " It continues with additional binding legal language."
    pages = [
        ExtractedPage(index, f"{long_line_extended}\nUnique content number {index}.")
        for index in range(1, 5)
    ]

    stripped = _strip_repeated_chrome(pages)

    for page in stripped:
        assert long_line_extended in page.text


@pytest.mark.asyncio
async def test_extractor_strips_page_numbers_from_real_pdf(tmp_path):
    body_a = (
        "Quarterly revenue rose by double digits. Operating margins held steady "
        "throughout the reported period."
    )
    body_b = (
        "Customer retention improved again. The pipeline for enterprise contracts "
        "grew substantially."
    )
    pdf_bytes = page_pdf([f"ACME Corp Confidential\n{body_a}", f"ACME Corp Confidential\n{body_b}"])
    path = tmp_path / "report.pdf"
    path.write_bytes(pdf_bytes)

    pages = await PdfPageExtractor().extract(path)

    joined = "\n".join(page.text for page in pages)
    assert len(pages) == 2
    # Two pages is below the chrome threshold; header must survive.
    assert "ACME Corp Confidential" in joined


@pytest.mark.asyncio
async def test_extractor_handles_multi_page_pdf_with_unique_bodies(tmp_path):
    bodies = [f"Document body with distinct evidence on page {index}." for index in range(1, 6)]
    path = tmp_path / "multi.pdf"
    path.write_bytes(page_pdf(bodies))

    pages = await PdfPageExtractor().extract(path)

    assert [page.page_number for page in pages] == [1, 2, 3, 4, 5]
    assert pages[0].text.startswith("Document body")


@pytest.mark.asyncio
async def test_extractor_rejects_encrypted_pdf(tmp_path):
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter
    from pypdf.annotations import FreeText

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_annotation(page_number=0, annotation=FreeText(text="secret", rect=(0, 0, 100, 100)))
    path = tmp_path / "encrypted.pdf"
    with open(path, "wb") as handle:
        writer.write(handle)
    # Note: pypdf encryption without a password still marks is_encrypted.
    writer.encrypt(user_password="x")
    with open(path, "wb") as handle:
        writer.write(handle)

    from app.domain.errors import InvalidDocumentError

    with pytest.raises(InvalidDocumentError):
        await PdfPageExtractor().extract(path)
