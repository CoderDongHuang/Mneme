import argparse
import io
import json
import os
import sys
import tempfile
from pathlib import Path


AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.knowledge.ingestion import parse_document  # noqa: E402
from app.knowledge.vision import describe_image  # noqa: E402


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _term_recall(text: str, expected: list[str]) -> tuple[float, list[str]]:
    normalized = " ".join(text.casefold().split())
    missing = [term for term in expected if term.casefold() not in normalized]
    return (len(expected) - len(missing)) / max(1, len(expected)), missing


def _ocr_fixture(path: Path) -> None:
    image = Image.new("RGB", (1600, 800), "white")
    draw = ImageDraw.Draw(image)
    draw.text((100, 130), "MNEME OCR QUALITY 7294", fill="black", font=_font(72))
    draw.text((100, 290), "Memory retention is 42 months", fill="black", font=_font(58))
    draw.text((100, 450), "记忆学习 质量验收", fill="black", font=_font(64))
    image.save(path, "PDF", resolution=150)


def _vision_fixture() -> bytes:
    image = Image.new("RGB", (1400, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.text((70, 45), "MNEME-VISION-7294", fill="black", font=_font(52))
    draw.text((70, 130), "Retention quality by year", fill="black", font=_font(38))
    draw.rectangle((180, 650, 450, 730), fill="#257A55")
    draw.rectangle((700, 490, 970, 730), fill="#CB4B35")
    draw.text((255, 665), "40", fill="white", font=_font(42))
    draw.text((775, 575), "80", fill="white", font=_font(42))
    draw.text((245, 750), "2024", fill="black", font=_font(36))
    draw.text((765, 750), "2025", fill="black", font=_font(36))
    draw.text((70, 825), "Formula: y = 2x + 3", fill="black", font=_font(42))
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def evaluate(require_multimodal: bool, dataset_path: Path | None = None) -> dict:
    cases = (
        json.loads(dataset_path.read_text(encoding="utf-8"))
        if dataset_path
        else [
            {"id": "ocr-default", "kind": "ocr", "expected_terms": ["MNEME", "7294", "42", "记忆", "质量"]},
            {"id": "vision-default", "kind": "multimodal", "expected_terms": ["MNEME-VISION-7294", "2024", "40", "2025", "80", "2x", "3"]},
        ]
    )
    if not isinstance(cases, list) or not cases:
        raise ValueError("文档 AI 评测集必须是非空 JSON 数组")
    with tempfile.TemporaryDirectory(prefix="mneme-document-ai-") as temporary:
        pdf_path = Path(temporary) / "ocr-quality.pdf"
        _ocr_fixture(pdf_path)
        documents = parse_document(str(pdf_path), source_name="ocr-quality.pdf")
    ocr_text = "\n".join(item.page_content for item in documents)
    ocr_samples = []
    for case in [item for item in cases if item.get("kind") == "ocr"]:
        recall, missing = _term_recall(ocr_text, case.get("expected_terms", []))
        ocr_samples.append({"id": case.get("id", "ocr"), "term_recall": round(recall, 4), "missing_terms": missing})
    confidences = [
        float(item.metadata["ocr_confidence"])
        for item in documents
        if item.metadata.get("ocr_confidence") is not None
    ]
    report = {
        "ocr": {
            "languages": os.getenv("OCR_LANGUAGES", "chi_sim+eng"),
            "term_recall": round(min((item["term_recall"] for item in ocr_samples), default=0.0), 4),
            "minimum_confidence": round(min(confidences), 4) if confidences else 0.0,
            "missing_terms": sorted({term for item in ocr_samples for term in item["missing_terms"]}),
            "samples": ocr_samples,
            "status": "passed"
            if ocr_samples and all(item["term_recall"] >= 0.8 for item in ocr_samples) and confidences and min(confidences) >= 0.5
            else "failed",
        },
        "multimodal": {"status": "disabled"},
    }
    if require_multimodal:
        vision_samples = []
        for case in [item for item in cases if item.get("kind") == "multimodal"]:
            response = describe_image(
                _vision_fixture(),
                "quality fixture; preserve identifiers, chart values, years, and formula exactly",
            )
            recall, missing = _term_recall(response, case.get("expected_terms", []))
            vision_samples.append({"id": case.get("id", "multimodal"), "term_recall": round(recall, 4), "missing_terms": missing, "response": response})
        report["multimodal"] = {
            "model": os.getenv("MULTIMODAL_MODEL", "qwen-vl-plus"),
            "term_recall": round(min((item["term_recall"] for item in vision_samples), default=0.0), 4),
            "missing_terms": sorted({term for item in vision_samples for term in item["missing_terms"]}),
            "samples": vision_samples,
            "status": "passed" if vision_samples and all(item["term_recall"] >= 0.85 for item in vision_samples) else "failed",
        }
    report["status"] = (
        "passed"
        if report["ocr"]["status"] == "passed"
        and (not require_multimodal or report["multimodal"]["status"] == "passed")
        else "failed"
    )
    report["dataset"] = {"path": dataset_path.name if dataset_path else "built-in"}
    report["failed_examples"] = [
        sample
        for group in (report["ocr"].get("samples", []), report["multimodal"].get("samples", []))
        for sample in group
        if sample.get("missing_terms")
    ]
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Mneme OCR and multimodal quality gate")
    parser.add_argument("--require-multimodal", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--dataset", type=Path)
    args = parser.parse_args()
    report = evaluate(args.require_multimodal, args.dataset)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
