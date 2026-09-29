"""Pure recommendations derived from observed usage and learning outcomes."""

from __future__ import annotations

from typing import Mapping


def recommend_policy(
    usage: Mapping[str, float], config: Mapping[str, float]
) -> dict[str, object]:
    """Return bounded, explainable recommendations without mutating settings."""
    recommendations: list[dict[str, object]] = []
    budget = max(0.0, float(config.get("llm_daily_budget_usd", 0)))
    spend = max(0.0, float(usage.get("llm_daily_cost_usd", 0)))
    budget_ratio = spend / budget if budget else 0.0
    learning_rate = float(usage.get("retention_rate", 0))
    observations = int(usage.get("learning_observations", 0))
    storage_ratio = float(usage.get("storage_usage_ratio", 0))
    trace_ratio = float(usage.get("trace_usage_ratio", 0))
    idle_ratio = float(usage.get("session_idle_ratio", 0))
    knowledge_base_ratio = float(usage.get("knowledge_base_usage_ratio", 0))

    if budget and budget_ratio >= 0.9:
        recommendations.append({
            "code": "llm_budget_near_limit",
            "severity": "high",
            "action": "reduce_model_budget_or_route_to_lower_cost_fallback",
            "reason": f"daily LLM spend is {budget_ratio:.0%} of the configured budget",
        })
    if budget and budget_ratio >= 0.75 and learning_rate < 0.6 and observations >= 4:
        recommendations.append({
            "code": "low_learning_return",
            "severity": "high",
            "action": "shorten_trace_retention_and_review_prompt_or_model_mix",
            "reason": "cost is high while observed retention is below 60%",
        })
    if trace_ratio >= 0.8:
        recommendations.append({
            "code": "trace_storage_near_limit",
            "severity": "medium",
            "action": "shorten_agent_trace_retention_days",
            "reason": f"trace storage is {trace_ratio:.0%} of its quota",
            "suggested_agent_trace_retention_days": max(7, int(config.get("agent_trace_retention_days", 30)) // 2),
        })
    if idle_ratio >= 0.8 and float(config.get("session_ttl_hours", 24)) > 12:
        recommendations.append({
            "code": "idle_sessions",
            "severity": "medium",
            "action": "reduce_session_ttl_hours_after_user_review",
            "reason": f"{idle_ratio:.0%} of measured sessions are idle",
            "suggested_session_ttl_hours": max(12, int(config.get("session_ttl_hours", 24)) // 2),
        })
    if storage_ratio >= 0.8:
        recommendations.append({
            "code": "knowledge_storage_near_limit",
            "severity": "medium",
            "action": "enforce_quota_or_archive_low_access_documents",
            "reason": f"knowledge storage is {storage_ratio:.0%} of its quota",
        })
    if knowledge_base_ratio >= 0.8:
        recommendations.append({
            "code": "knowledge_base_quota_near_limit",
            "severity": "medium",
            "action": "archive_unused_knowledge_bases_before_raising_quota",
            "reason": f"knowledge base count is {knowledge_base_ratio:.0%} of its quota",
        })
    if observations >= 4 and learning_rate >= 0.85:
        recommendations.append({
            "code": "strong_learning_signal",
            "severity": "low",
            "action": "increase_review_interval_within_configured_bounds",
            "reason": "observed retention is at least 85%",
        })
    return {
        "status": "action_required" if recommendations else "within_policy",
        "observations": observations,
        "budget_ratio": round(budget_ratio, 4),
        "recommendations": recommendations,
    }
