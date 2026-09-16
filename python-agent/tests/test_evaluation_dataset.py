import json
from pathlib import Path

from openpyxl import load_workbook
from pypdf import PdfReader


def test_offline_rag_dataset_has_structured_coverage():
    dataset = json.loads(
        (Path(__file__).parents[1] / "evaluation" / "rag_cases.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(dataset) >= 100
    assert {"roadmap", "metrics", "parser", "memory", "unanswerable"} <= {
        case["category"] for case in dataset
    }
    assert sum(not case.get("answerable", True) for case in dataset) >= 5


def test_annotated_layout_regression_fixtures_are_complete():
    root = Path(__file__).parents[1] / "evaluation"
    annotations = json.loads((root / "layout_annotations.json").read_text(encoding="utf-8"))
    categories = {item["category"] for item in annotations}
    assert {
        "scanned_pdf",
        "multi_column",
        "cross_page_table",
        "formula_chart",
        "spreadsheet_formula_chart",
    } <= categories
    for item in annotations:
        assert (root / "fixtures" / item["fixture"]).is_file()
    pdf = PdfReader(root / "fixtures" / "complex-layout.pdf")
    assert len(pdf.pages) == 4
    assert not (pdf.pages[0].extract_text() or "").strip()
    second_page = pdf.pages[1].extract_text()
    assert "COLUMN-LEFT" in second_page and "COLUMN-RIGHT" in second_page
    table_text = "\n".join((pdf.pages[index].extract_text() or "") for index in (2, 3))
    assert "Item 08" in table_text and "Item 09" in table_text
    workbook = load_workbook(root / "fixtures" / "formula-chart.xlsx", data_only=False)
    sheet = workbook["FormulaChart"]
    assert sheet["D2"].value == "=C2/B2"
    assert len(sheet._charts) == 1
