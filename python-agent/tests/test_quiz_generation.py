import pytest

from app.api.knowledge import _quiz_json


def test_quiz_json_accepts_evidence_grounded_question():
    questions = _quiz_json(
        """```json
        [{"id":1,"type":"choice","prompt":"哪项有证据支持？",
          "options":["链式法则计算梯度","梯度与导数无关"],"answer":"0",
          "key_points":["链式法则"],"evidence":"通过链式法则计算梯度",
          "source":{"page":2}}]
        ```"""
    )
    assert questions[0]["answer"] == "0"
    assert questions[0]["source"]["page"] == 2


def test_quiz_json_rejects_choice_without_options():
    with pytest.raises(ValueError):
        _quiz_json(
            '[{"id":1,"type":"choice","prompt":"这是无效题目",'
            '"options":[],"answer":"0","key_points":["要点"],'
            '"evidence":"证据内容","source":{}}]'
        )
