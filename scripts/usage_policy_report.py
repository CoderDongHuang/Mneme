#!/usr/bin/env python3
"""Generate recommendations from measured usage and learning outcome snapshots."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python-agent"))
from app.core.usage_policy import recommend_policy  # noqa: E402


def run(usage: dict, config: dict, now: datetime | None = None) -> dict:
    required = {"captured_at", "llm_daily_cost_usd", "storage_usage_ratio", "trace_usage_ratio", "session_idle_ratio", "knowledge_base_usage_ratio", "learning_observations", "retention_rate"}
    missing = required - usage.keys()
    if missing:
        raise ValueError(f"usage snapshot is missing measured fields: {sorted(missing)}")
    try:
        captured_at = datetime.fromisoformat(str(usage["captured_at"]).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("captured_at must be an ISO-8601 timestamp") from error
    if captured_at.tzinfo is None:
        raise ValueError("captured_at must include a timezone")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("current time must include a timezone")
    if captured_at > current + timedelta(minutes=5):
        raise ValueError("usage snapshot captured_at is in the future")
    if int(usage.get("sample_count", 0)) < 1:
        raise ValueError("usage snapshot must contain a positive sample_count")
    if float(usage.get("measurement_window_seconds", 0)) <= 0:
        raise ValueError("usage snapshot must contain a positive measurement_window_seconds")
    window_seconds = float(usage["measurement_window_seconds"])
    if current - captured_at > timedelta(seconds=window_seconds + 300):
        raise ValueError("usage snapshot is older than its measurement window")
    evidence = usage.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("usage snapshot must identify measured evidence sources")
    if not 0 <= float(usage["retention_rate"]) <= 1:
        raise ValueError("retention_rate must be within [0, 1]")
    for field in ("storage_usage_ratio", "trace_usage_ratio", "session_idle_ratio", "knowledge_base_usage_ratio"):
        if not 0 <= float(usage[field]) <= 1:
            raise ValueError(f"{field} must be within [0, 1]")
    return {
        "captured_at": usage["captured_at"],
        "sample_count": int(usage["sample_count"]),
        "measurement_window_seconds": window_seconds,
        "evidence": evidence,
        "source": usage.get("source", "operator-measured-snapshot"),
        "policy": recommend_policy(usage, config),
        "current_settings": {
            "session_ttl_hours": config.get("session_ttl_hours"),
            "agent_trace_retention_days": config.get("agent_trace_retention_days"),
            "tenant_storage_quota_mb": config.get("tenant_storage_quota_mb"),
            "tenant_knowledge_base_quota": config.get("tenant_knowledge_base_quota"),
            "llm_daily_budget_usd": config.get("llm_daily_budget_usd"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usage", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = run(
        json.loads(args.usage.read_text(encoding="utf-8")),
        json.loads(args.config.read_text(encoding="utf-8")),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
