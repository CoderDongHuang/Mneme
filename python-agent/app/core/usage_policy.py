"""Pure recommendations derived from observed usage and learning outcomes."""

from __future__ import annotations

import math
from typing import Mapping


def finite_number(
    value: object, field: str, *, minimum: float = 0,
    maximum: float | None = None, integer: bool = False,
) -> float:
    """Validate measurements before arithmetic; never clamp invalid evidence."""
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{field} must be a finite number") from error
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    if number < minimum or (maximum is not None and number > maximum):
        upper = maximum if maximum is not None else "infinity"
        raise ValueError(f"{field} must be within [{minimum}, {upper}]")
    if integer and not number.is_integer():
        raise ValueError(f"{field} must be an integer")
    return number


def recommend_policy(
    usage: Mapping[str, float], config: Mapping[str, float]
) -> dict[str, object]:
    """Return bounded, explainable recommendations without mutating settings."""
    recommendations: list[dict[str, object]] = []
    budget = finite_number(config.get("llm_daily_budget_usd", 0), "llm_daily_budget_usd")
    spend = finite_number(usage.get("llm_daily_cost_usd", 0), "llm_daily_cost_usd")
    budget_ratio = finite_number(spend / budget if budget else 0.0, "budget_ratio")
    learning_rate = finite_number(usage.get("retention_rate", 0), "retention_rate", maximum=1)
    observations = int(finite_number(
        usage.get("learning_observations", 0), "learning_observations", integer=True,
    ))
    # Occupancy can exceed a quota. Idle and learning fractions cannot exceed one.
    storage_ratio = finite_number(usage.get("storage_usage_ratio", 0), "storage_usage_ratio")
    trace_ratio = finite_number(usage.get("trace_usage_ratio", 0), "trace_usage_ratio")
    idle_ratio = finite_number(usage.get("session_idle_ratio", 0), "session_idle_ratio", maximum=1)
    knowledge_base_ratio = finite_number(
        usage.get("knowledge_base_usage_ratio", 0), "knowledge_base_usage_ratio",
    )
    ttl = int(finite_number(config.get("session_ttl_hours", 24), "session_ttl_hours", minimum=1, integer=True))
    retention_days = int(finite_number(
        config.get("agent_trace_retention_days", 30), "agent_trace_retention_days", minimum=1, integer=True,
    ))
    for field in ("tenant_storage_quota_mb", "tenant_knowledge_base_quota"):
        if field in config:
            finite_number(config[field], field, minimum=1, integer=True)

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
            "suggested_agent_trace_retention_days": min(retention_days, max(7, retention_days // 2)),
        })
    if idle_ratio >= 0.8 and ttl > 12:
        recommendations.append({
            "code": "idle_sessions",
            "severity": "medium",
            "action": "reduce_session_ttl_hours_after_user_review",
            "reason": f"{idle_ratio:.0%} of measured sessions are idle",
            "suggested_session_ttl_hours": max(12, ttl // 2),
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
