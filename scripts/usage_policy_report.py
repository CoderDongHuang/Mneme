#!/usr/bin/env python3
"""Generate recommendations from measured usage and learning outcome snapshots."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python-agent"))
from app.core.usage_policy import finite_number, recommend_policy  # noqa: E402


def timestamp(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def nonempty_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value.strip()


def cost_interval(usage: dict) -> tuple[datetime, datetime] | None:
    if not usage.get("cost_period_start") or not usage.get("cost_period_end"):
        return None
    start = timestamp(usage["cost_period_start"], "cost_period_start")
    end = timestamp(usage["cost_period_end"], "cost_period_end")
    if start >= end or end > timestamp(usage["captured_at"], "captured_at"):
        raise ValueError("estimated cost interval must be nonempty and end by captured_at")
    if start != start.replace(hour=0, minute=0, second=0, microsecond=0) or end.date() != start.date():
        raise ValueError("estimated cost interval must cover a single UTC day from midnight")
    return start, end


def reconcile_billing(usage: dict, billing: dict | None, current: datetime) -> dict:
    """Reconcile supplied export evidence; this does not authenticate a provider."""
    result = {
        "status": "unverified",
        "scope": "llm_cost_only",
        "estimated_cost_usd": float(usage["llm_daily_cost_usd"]),
        "cost_basis": "reservation_estimate",
        "absolute_tolerance_usd": 0.05,
        "relative_tolerance": 0.10,
        "provenance_verification": "operator_supplied_not_authenticated",
        "reasons": [],
    }
    if billing is None:
        result["reasons"] = ["billing_not_supplied"]
        return result
    if not isinstance(billing, dict):
        raise ValueError("billing must be a JSON object")
    required = {
        "schema_version", "source", "environment", "cost_scope", "currency",
        "period_start", "period_end", "exported_at", "complete", "actual_cost_usd",
    }
    if missing := required - billing.keys():
        raise ValueError(f"billing is missing fields: {sorted(missing)}")
    if finite_number(billing["schema_version"], "billing.schema_version", integer=True) != 1:
        raise ValueError("billing.schema_version must be 1")
    source = billing["source"]
    if not isinstance(source, dict):
        raise ValueError("billing.source must be an object")
    kind = nonempty_text(source.get("kind"), "billing.source.kind")
    reference = nonempty_text(source.get("reference"), "billing.source.reference")
    environment = nonempty_text(billing["environment"], "billing.environment")
    scope = nonempty_text(billing["cost_scope"], "billing.cost_scope")
    if billing["currency"] != "USD":
        raise ValueError("billing.currency must be USD; currency conversion is not supported")
    if not isinstance(billing["complete"], bool):
        raise ValueError("billing.complete must be a boolean")
    actual = finite_number(billing["actual_cost_usd"], "billing.actual_cost_usd")
    start = timestamp(billing["period_start"], "billing.period_start")
    end = timestamp(billing["period_end"], "billing.period_end")
    exported = timestamp(billing["exported_at"], "billing.exported_at")
    if start >= end:
        raise ValueError("billing period_start must be before period_end")
    if exported < end or exported > current + timedelta(minutes=5):
        raise ValueError("billing.exported_at must follow period_end and must not be in the future")
    reasons = result["reasons"]
    if kind != "provider_billing_export":
        reasons.append("not_provider_billing_export")
    if environment != "production" or usage.get("environment") != "production":
        reasons.append("nonproduction_or_unknown_environment")
    if usage.get("source") != "mneme-aggregate-collector":
        reasons.append("estimated_cost_source_unverified")
    if not billing["complete"]:
        reasons.append("billing_interval_incomplete")
    if scope != usage.get("cost_scope"):
        reasons.append("cost_scope_mismatch_or_missing")
    redis_evidence = usage["evidence"].get("redis")
    if not isinstance(redis_evidence, dict) or redis_evidence.get("value_present") is not True:
        reasons.append("estimated_cost_evidence_missing")
    interval = cost_interval(usage)
    if interval is None:
        reasons.append("estimated_cost_interval_missing")
    else:
        cost_start, cost_end = interval
        if start != cost_start or end != cost_end:
            reasons.append("cost_interval_mismatch")
        if isinstance(redis_evidence, dict) and redis_evidence.get("daily_cost_key") != f"mneme:llm:cost:{cost_start.date().isoformat()}":
            reasons.append("estimated_cost_key_mismatch")
    estimated = result["estimated_cost_usd"]
    difference = abs(estimated - actual)
    relative = difference / actual if actual else None
    # A relative difference can overflow for tiny positive bills. It is diagnostic only.
    if relative is not None and not math.isfinite(relative):
        relative = None
    if not actual or not estimated:
        reasons.append("positive_cost_evidence_required")
    if difference > max(result["absolute_tolerance_usd"], actual * result["relative_tolerance"]):
        reasons.append("cost_difference_exceeds_tolerance")
    result.update({
        "actual_cost_usd": actual,
        "absolute_difference_usd": round(difference, 8),
        "relative_difference": relative,
        "billing_source": {"kind": kind, "reference": reference},
        "billing_environment": environment,
        "billing_cost_scope": scope,
        "currency": "USD",
        "billing_complete": billing["complete"],
        "billing_exported_at": exported.isoformat(),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
    })
    if not reasons:
        result["status"] = "calibrated"
    return result


def run(
    usage: dict, config: dict, now: datetime | None = None, *, billing: dict | None = None,
) -> dict:
    if not isinstance(usage, dict) or not isinstance(config, dict):
        raise ValueError("usage and config must be JSON objects")
    required = {"captured_at", "llm_daily_cost_usd", "storage_usage_ratio", "trace_usage_ratio", "session_idle_ratio", "knowledge_base_usage_ratio", "learning_observations", "retention_rate"}
    missing = required - usage.keys()
    if missing:
        raise ValueError(f"usage snapshot is missing measured fields: {sorted(missing)}")
    captured_at = timestamp(usage["captured_at"], "captured_at")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("current time must include a timezone")
    if captured_at > current + timedelta(minutes=5):
        raise ValueError("usage snapshot captured_at is in the future")
    sample_count = int(finite_number(usage.get("sample_count", 0), "sample_count", minimum=1, integer=True))
    window_seconds = finite_number(usage.get("measurement_window_seconds", 0), "measurement_window_seconds", minimum=1, integer=True)
    if (current - captured_at).total_seconds() - 300 > window_seconds:
        raise ValueError("usage snapshot is older than its measurement window")
    evidence = usage.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("usage snapshot must identify measured evidence sources")
    policy = recommend_policy(usage, config)
    if policy["observations"] > sample_count:
        raise ValueError("learning_observations cannot exceed sample_count")
    cost_interval(usage)
    return {
        "captured_at": usage["captured_at"],
        "sample_count": sample_count,
        "measurement_window_seconds": window_seconds,
        "evidence": evidence,
        "source": usage.get("source", "operator-measured-snapshot"),
        "environment": usage.get("environment", "unspecified"),
        "cost_scope": usage.get("cost_scope"),
        "cost_period_start": usage.get("cost_period_start"),
        "cost_period_end": usage.get("cost_period_end"),
        "measured_usage": {
            field: finite_number(usage[field], field)
            for field in sorted(required - {"captured_at"})
        },
        "policy": policy,
        "billing_reconciliation": reconcile_billing(usage, billing, current),
        "production_policy_verified": False,
        "configuration_changed": False,
        "current_settings": {
            "session_ttl_hours": config.get("session_ttl_hours"),
            "agent_trace_retention_days": config.get("agent_trace_retention_days"),
            "tenant_storage_quota_mb": config.get("tenant_storage_quota_mb"),
            "tenant_knowledge_base_quota": config.get("tenant_knowledge_base_quota"),
            "llm_daily_budget_usd": config.get("llm_daily_budget_usd"),
        },
    }


def save_history(result: dict, directory: Path) -> Path:
    """Keep every distinct report, including unverified reports, without overwrite."""
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    day = timestamp(result["captured_at"], "captured_at").date().isoformat()
    path = directory / day / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as entry:
            entry.write(payload)
    except FileExistsError:
        if path.read_bytes() != payload.encode("utf-8"):
            raise ValueError(f"existing report history entry is inconsistent: {path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usage", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--billing", type=Path, help="normalized provider billing export (optional)")
    parser.add_argument("--history-dir", type=Path, help="preserve distinct reports in dated history (optional)")
    args = parser.parse_args()
    inputs = (args.usage, args.config, args.billing)
    if any(path is not None and args.report.resolve() == path.resolve() for path in inputs):
        parser.error("--report must differ from the usage, config, and billing input files")
    result = run(
        json.loads(args.usage.read_text(encoding="utf-8")),
        json.loads(args.config.read_text(encoding="utf-8")),
        billing=json.loads(args.billing.read_text(encoding="utf-8")) if args.billing else None,
    )
    if args.history_dir:
        save_history(result, args.history_dir)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
