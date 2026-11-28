import json
from pathlib import Path


def test_quiz_rest_types_are_included_in_the_shared_generator():
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / 'contracts/quiz.schema.json').read_text(encoding='utf-8'))
    cases = json.loads((root / 'contracts/quiz.cases.json').read_text(encoding='utf-8'))
    assert set(schema['$defs']) == {
        'Quiz', 'QuizQuestion', 'QuizOption', 'QuizDraft', 'SaveQuizDraftRequest',
        'QuizFeedback', 'QuizAttempt', 'SubmitQuizRequest', 'QuizSubmissionReceipt',
        'ReportQuestionRequest', 'ReportQuestionReceipt',
    }
    assert {case['schema'] for case in cases} == set(schema['$defs']) - {'QuizOption', 'QuizFeedback'}
