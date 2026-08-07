from pathlib import Path
import shutil

import fitz
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.knowledge.ingestion import parse_document


def _create_layout_pdf(path: Path) -> None:
    document = fitz.open()
    for page_number in range(1, 4):
        page = document.new_page()
        page.insert_text((72, 40), "Mneme test material")
        page.insert_text((72, 90), f"Chapter {page_number}")
        page.insert_text((72, 130), f"Unique page content TOKEN-{page_number}")
        page.insert_text((72, 800), "Internal material")
    document.save(path)


def test_pdf_layout_removes_repeated_headers_and_footers(tmp_path):
    path = tmp_path / "layout.pdf"
    _create_layout_pdf(path)

    parsed = parse_document(str(path))
    text_documents = [
        document for document in parsed if document.metadata["chunk_type"] == "text"
    ]

    assert len(text_documents) == 3
    assert all("Mneme test material" not in document.page_content for document in text_documents)
    assert all("Internal material" not in document.page_content for document in text_documents)
    assert "TOKEN-2" in text_documents[1].page_content
    assert text_documents[1].metadata["page"] == 2
    assert text_documents[1].metadata["parser"] == "pymupdf_layout"


def test_pdf_keeps_extracted_text_when_ocr_is_unavailable(tmp_path, monkeypatch):
    import pytesseract

    path = tmp_path / "ocr-fallback.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 90), "Extracted text must survive OCR failure")
    document.save(path)

    def unavailable(*args, **kwargs):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "image_to_string", unavailable)

    parsed = parse_document(str(path))

    assert "Extracted text must survive" in parsed[0].page_content


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("tesseract") is None, reason="需要 Tesseract")
def test_scanned_pdf_uses_ocr(tmp_path):
    image_path = tmp_path / "scan.png"
    image = Image.new("RGB", (1200, 300), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 64)
    except OSError:
        font = ImageFont.load_default()
    draw.text((60, 100), "MNEME OCR TOKEN 7294", fill="black", font=font)
    image.save(image_path)

    pdf_path = tmp_path / "scan.pdf"
    document = fitz.open()
    page = document.new_page(width=1200, height=300)
    page.insert_image(page.rect, filename=str(image_path))
    document.save(pdf_path)

    parsed = parse_document(str(pdf_path))
    content = "\n".join(document.page_content for document in parsed)
    assert "MNEME" in content
    assert "7294" in content
