import json
from pathlib import Path


def test_review_rest_contract_examples_are_shared_with_gateway_and_browser():
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / 'contracts/review.schema.json').read_text(encoding='utf-8'))
    cases = json.loads((root / 'contracts/review.cases.json').read_text(encoding='utf-8'))
    assert set(schema['$defs']) == {'ReviewCard', 'LearningPlan', 'CreatePlanRequest', 'ReviewCardInput', 'ReviewRatingRequest'}
    assert {case['schema'] for case in cases} == set(schema['$defs']) - {'ReviewCardInput'}
