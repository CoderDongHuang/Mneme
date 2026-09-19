import pytest

from scripts.quality_policy import CostBudget, require_sanitized, sensitive_findings


def test_sanitized_examples_are_accepted():
    require_sanitized({"email": "learner@example.test", "question": "学习路线是什么？"})


def test_sensitive_fields_are_rejected_even_without_key_pattern():
    with pytest.raises(ValueError, match="sensitive_field"):
        require_sanitized({"api_key": "redacted-but-present"})


@pytest.mark.parametrize(
    ("value", "label"),
    [
        ("联系 learner@private.cn", "email"),
        ("手机号 13812345678", "mainland_phone"),
        ("身份证 110101199001011234", "mainland_id"),
        ("token sk-secretvalue123456789", "api_key"),
    ],
)
def test_sensitive_values_are_rejected(value, label):
    assert label in sensitive_findings({"value": value})[0]
    with pytest.raises(ValueError, match="未通过脱敏检查"):
        require_sanitized({"value": value})


def test_budget_is_reserved_before_external_calls():
    budget = CostBudget(0.001, 100.0, 200.0)
    assert budget.reserve(2, 1, "sample") == pytest.approx(0.0004)
    with pytest.raises(RuntimeError, match="超过评测预算"):
        budget.reserve(4, 2, "next sample")
