from copy import deepcopy

import pytest

from app.core.usage_policy import recommend_policy


def test_policy_flags_cost_and_storage_pressure():
    result = recommend_policy(
        {
            "llm_daily_cost_usd": 9.5,
            "retention_rate": 0.4,
            "learning_observations": 8,
            "trace_usage_ratio": 0.9,
            "storage_usage_ratio": 0.85,
        },
        {"llm_daily_budget_usd": 10},
    )
    codes = {item["code"] for item in result["recommendations"]}
    assert result["status"] == "action_required"
    assert {"llm_budget_near_limit", "low_learning_return", "trace_storage_near_limit", "knowledge_storage_near_limit"} <= codes


def test_policy_keeps_strong_learning_signal_bounded():
    result = recommend_policy(
        {"retention_rate": 0.9, "learning_observations": 10},
        {"llm_daily_budget_usd": 0},
    )
    assert result["status"] == "action_required"
    assert result["recommendations"][0]["action"] == "increase_review_interval_within_configured_bounds"


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), -1, True, None, "invalid"])
@pytest.mark.parametrize("field", [
    "llm_daily_cost_usd", "learning_observations", "retention_rate",
    "trace_usage_ratio", "storage_usage_ratio", "session_idle_ratio", "knowledge_base_usage_ratio",
])
def test_policy_rejects_invalid_usage(field, invalid):
    with pytest.raises(ValueError, match=field):
        recommend_policy({field: invalid}, {})


@pytest.mark.parametrize("field,invalid", [
    ("learning_observations", 1.5), ("session_idle_ratio", 1.1), ("retention_rate", 1.1),
    ("llm_daily_budget_usd", -1), ("llm_daily_budget_usd", float("nan")),
    ("session_ttl_hours", 0), ("session_ttl_hours", 1.5),
    ("agent_trace_retention_days", float("inf")), ("tenant_storage_quota_mb", 0),
    ("tenant_knowledge_base_quota", -1),
])
def test_policy_rejects_invalid_counts_fractions_and_settings(field, invalid):
    usage_fields = {"learning_observations", "session_idle_ratio", "retention_rate"}
    with pytest.raises(ValueError, match=field):
        recommend_policy({field: invalid} if field in usage_fields else {},
                         {} if field in usage_fields else {field: invalid})


def test_over_quota_and_short_retention_recommendations_do_not_mutate_config():
    usage = {"trace_usage_ratio": 1.5, "storage_usage_ratio": 2, "knowledge_base_usage_ratio": 3}
    config = {"agent_trace_retention_days": 3, "session_ttl_hours": 24}
    before = deepcopy((usage, config))
    result = recommend_policy(usage, config)
    assert len(result["recommendations"]) == 3
    assert result["recommendations"][0]["suggested_agent_trace_retention_days"] == 3
    assert "150%" in result["recommendations"][0]["reason"]
    assert (usage, config) == before


def test_unrepresentable_budget_ratio_is_rejected():
    with pytest.raises(ValueError, match="budget_ratio"):
        recommend_policy({"llm_daily_cost_usd": 1e308}, {"llm_daily_budget_usd": 1e-308})
