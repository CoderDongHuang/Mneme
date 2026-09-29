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
