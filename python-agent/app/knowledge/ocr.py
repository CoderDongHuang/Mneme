"""Run Tesseract through pipes: document images never become temporary files."""

import csv
import io
import math
import os
import subprocess

from app.knowledge.cancellation import check_cancelled


def _execute(arguments: list[str], payload: bytes | None, timeout: float) -> str:
    import pytesseract

    check_cancelled()
    command = [pytesseract.pytesseract.tesseract_cmd, *arguments]
    try:
        result = subprocess.run(
            command, input=payload, capture_output=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        # TimeoutExpired can carry document output. Never propagate it to logs.
        raise TimeoutError("OCR processing timed out") from None
    except FileNotFoundError:
        raise FileNotFoundError("OCR runtime missing") from None
    except OSError:
        raise RuntimeError("OCR runtime unavailable") from None
    if result.returncode:
        # Tesseract stderr may contain document content or paths.
        raise RuntimeError("OCR processing failed") from None
    check_cancelled()
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise RuntimeError("OCR returned invalid output") from None


def _recognize(payload: bytes, language: str, output: str, timeout: float) -> str:
    return _execute(["stdin", "stdout", "-l", language, output], payload, timeout)


def available_languages(timeout: float = 5) -> set[str]:
    """Bound language enumeration as well as actual recognition."""
    return set(_execute(["--list-langs"], None, timeout).splitlines()[1:])


def recognize_image(image, language: str, timeout: float = 60) -> tuple[dict, str]:
    """Preserve both TSV coordinates and native text layout without disk output."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("OCR timeout must be finite and positive")
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    payload = encoded.getvalue()
    tsv = _recognize(payload, language, "tsv", timeout)
    columns = ("text", "conf", "left", "top", "width", "height")
    data = {name: [] for name in columns}
    try:
        reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
        if not reader.fieldnames or not set(columns).issubset(reader.fieldnames):
            raise ValueError
        for row in reader:
            values = {name: row[name] for name in columns}
            values["conf"] = float(values["conf"])
            for name in ("left", "top", "width", "height"):
                values[name] = int(values[name])
            if values["text"] is None:
                raise ValueError
            for name in columns:
                data[name].append(values[name])
    except (KeyError, ValueError, TypeError, csv.Error):
        raise RuntimeError("OCR returned invalid coordinates") from None
    return data, _recognize(payload, language, "txt", timeout).strip()
