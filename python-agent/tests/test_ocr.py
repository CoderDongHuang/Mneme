"""OCR privacy, timeout and cancellation without a system OCR dependency."""

import subprocess
import shutil
import tempfile
from types import SimpleNamespace

import pytest
from PIL import Image

from app.knowledge import ocr
from app.knowledge.cancellation import IngestionCancelled, IngestionLeaseLost

TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "5\t1\t1\t1\t1\t1\t12\t34\t56\t78\t95.5\t记忆\n"
)


def test_image_and_both_outputs_use_pipes_without_pytesseract_tempfiles(monkeypatch):
    import pytesseract

    def forbid(*args, **kwargs):
        pytest.fail("OCR must not create temporary image/output files")

    monkeypatch.setattr(pytesseract.pytesseract, "save", forbid)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=(
            TSV if command[-1] == "tsv" else "记忆\n  layout\n"
        ).encode())

    monkeypatch.setattr(ocr.subprocess, "run", run)
    with Image.new("RGB", (100, 100)) as image:
        data, text = ocr.recognize_image(image, "chi_sim+eng", timeout=2)
    assert text == "记忆\n  layout"
    assert data == {"text": ["记忆"], "conf": [95.5], "left": [12],
                    "top": [34], "width": [56], "height": [78]}
    assert len(calls) == 2
    for command, kwargs in calls:
        assert command[1:5] == ["stdin", "stdout", "-l", "chi_sim+eng"]
        assert kwargs["input"].startswith(b"\x89PNG")
        assert kwargs["capture_output"] is True
        assert kwargs["timeout"] == 2


@pytest.mark.parametrize("failure, message", [
    (subprocess.TimeoutExpired("private-document", 1, output=b"SECRET", stderr=b"SECRET"),
     "OCR processing timed out"),
    (FileNotFoundError("SECRET"), "OCR runtime missing"),
    (PermissionError("SECRET"), "OCR runtime unavailable"),
])
def test_runtime_failures_do_not_expose_document_output(monkeypatch, failure, message):
    def run(*args, **kwargs):
        raise failure

    monkeypatch.setattr(ocr.subprocess, "run", run)
    with pytest.raises((RuntimeError, OSError), match=message) as caught:
        ocr._recognize(b"image", "eng", "txt", 1)
    assert "SECRET" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("code, output, message", [
    (1, b"SECRET", "OCR processing failed"),
    (0, b"\xff", "OCR returned invalid output"),
])
def test_bad_process_results_fail_safely(monkeypatch, code, output, message):
    monkeypatch.setattr(ocr.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=code, stdout=output, stderr=b"SECRET"))
    with pytest.raises(RuntimeError, match=message):
        ocr._recognize(b"image", "eng", "txt", 1)


@pytest.mark.parametrize("tsv", ["", "text\nSECRET\n",
                                TSV.replace("95.5", "invalid"),
                                TSV.replace("\t12\t", "\tinvalid\t")])
def test_malformed_coordinates_rejected(monkeypatch, tsv):
    monkeypatch.setattr(ocr, "_recognize", lambda *args: tsv)
    with Image.new("RGB", (10, 10)) as image:
        with pytest.raises(RuntimeError, match="OCR returned invalid coordinates"):
            ocr.recognize_image(image, "eng")


@pytest.mark.parametrize("error_type", [IngestionCancelled, IngestionLeaseLost])
@pytest.mark.parametrize("checkpoint", [1, 2])
def test_cancellation_and_lost_lease_preserved(monkeypatch, error_type, checkpoint):
    calls = 0

    def check():
        nonlocal calls
        calls += 1
        if calls == checkpoint:
            raise error_type("stop")

    monkeypatch.setattr(ocr, "check_cancelled", check)
    monkeypatch.setattr(ocr.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout=b"recognized"))
    with pytest.raises(error_type, match="stop"):
        ocr._recognize(b"image", "eng", "txt", 1)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_timeout_must_be_bounded(timeout):
    with pytest.raises(ValueError, match="finite and positive"):
        ocr.recognize_image(None, "eng", timeout)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="requires real Tesseract")
def test_real_ocr_creates_no_image_or_output_files_and_timeout_is_sanitized(monkeypatch):
    import pytesseract

    def forbid(*args, **kwargs):
        pytest.fail("real OCR tried to create a temporary document file")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", forbid)
    monkeypatch.setattr(pytesseract.pytesseract, "save", forbid)
    with Image.new("RGB", (200, 100), "white") as image:
        data, text = ocr.recognize_image(image, "eng", timeout=5)
        assert text == "" and all(word == "" for word in data["text"])
        with pytest.raises(TimeoutError, match="OCR processing timed out"):
            ocr.recognize_image(image, "eng", timeout=1e-9)


def test_language_enumeration_is_bounded(monkeypatch):
    def run(command, **kwargs):
        assert command[1:] == ["--list-langs"]
        assert kwargs["input"] is None and kwargs["timeout"] == 3
        return SimpleNamespace(returncode=0, stdout=b"List of available languages (2):\nchi_sim\neng\n")

    monkeypatch.setattr(ocr.subprocess, "run", run)
    assert ocr.available_languages(timeout=3) == {"chi_sim", "eng"}


def test_ocr_timeout_classified_as_timeout():
    from app.core.provider_diagnostics import classify_error

    assert classify_error(TimeoutError("OCR processing timed out")) == "timeout"
