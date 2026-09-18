import importlib.util
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).parents[1] / "scripts" / "evaluate_document_ai.py"
SPEC = importlib.util.spec_from_file_location("evaluate_document_ai", SCRIPT)
assert SPEC and SPEC.loader
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


def test_term_recall_normalizes_case_and_whitespace():
    recall, missing = evaluation._term_recall(
        "MNEME-7294\n  Formula: y = 2X + 3", ["mneme", "2x", "missing"]
    )
    assert recall == 2 / 3
    assert missing == ["missing"]


def test_visual_quality_fixture_is_a_nonblank_png():
    image = Image.open(evaluation.io.BytesIO(evaluation._vision_fixture()))
    assert image.format == "PNG"
    assert image.size == (1400, 900)
    assert image.getbbox() is not None
