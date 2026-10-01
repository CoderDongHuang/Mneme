#!/usr/bin/env python3
"""Collect privacy-safe aggregate usage evidence for policy recommendations."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python-agent"))
from app.core.usage_policy import finite_number, recommend_policy  # noqa: E402


def build_snapshot(aggregates: dict, settings: dict, captured_at: str) -> dict:
    counts = {
        field: int(finite_number(aggregates[field], field, integer=True))
        for field in (
            "users", "active_sessions", "idle_sessions", "trace_rows_total",
            "trace_rows_window", "learning_observations", "max_knowledge_bases", "llm_request_series",
        )
    }
    users = counts["users"]
    active_sessions = counts["active_sessions"]
    traces = counts["trace_rows_window"]
    observations = counts["learning_observations"]
    if counts["idle_sessions"] > active_sessions:
        raise ValueError("idle_sessions cannot exceed active_sessions")
    if traces > counts["trace_rows_total"]:
        raise ValueError("trace_rows_window cannot exceed trace_rows_total")
    storage_bytes = finite_number(aggregates["max_storage_bytes"], "max_storage_bytes")
    cost = finite_number(aggregates["llm_daily_cost_usd"], "llm_daily_cost_usd")
    retention = finite_number(aggregates["retention_rate"], "retention_rate", maximum=1)
    if not isinstance(aggregates["llm_cost_present"], bool):
        raise ValueError("llm_cost_present must be a boolean")
    if not aggregates["llm_cost_present"] and cost:
        raise ValueError("nonzero LLM cost requires a present cost counter")
    storage_quota = finite_number(settings["tenant_storage_quota_bytes"], "tenant_storage_quota_bytes", minimum=1)
    kb_quota = finite_number(settings["tenant_knowledge_base_quota"], "tenant_knowledge_base_quota", minimum=1, integer=True)
    trace_quota = finite_number(settings["trace_row_quota"], "trace_row_quota", minimum=1, integer=True)
    window = int(finite_number(settings["measurement_window_seconds"], "measurement_window_seconds", minimum=1, integer=True))
    # Only windowed observations support a windowed policy recommendation.
    # Prometheus request counters are cumulative since process start.
    sample_count = max(active_sessions, traces, observations)
    if sample_count < 1:
        raise ValueError("usage collection found no measurable samples")
    return {
        "captured_at": captured_at,
        "source": "mneme-aggregate-collector",
        "sample_count": sample_count,
        "measurement_window_seconds": window,
        "environment": settings.get("environment", "unspecified"),
        "cost_scope": settings.get("cost_scope"),
        "cost_period_start": aggregates.get("cost_period_start"),
        "cost_period_end": aggregates.get("cost_period_end"),
        "llm_daily_cost_usd": cost,
        "storage_usage_ratio": round(storage_bytes / storage_quota, 6),
        "trace_usage_ratio": round(counts["trace_rows_total"] / trace_quota, 6),
        "session_idle_ratio": round(
            counts["idle_sessions"] / active_sessions if active_sessions else 0.0, 6,
        ),
        "knowledge_base_usage_ratio": round(
            counts["max_knowledge_bases"] / kb_quota, 6,
        ),
        "learning_observations": observations,
        "retention_rate": retention,
        "evidence": {
            "mysql": {
                "aggregates_only": True,
                "users": users,
                "active_sessions": active_sessions,
                "trace_rows": counts["trace_rows_total"],
                "trace_rows_total": counts["trace_rows_total"],
                "trace_rows_window": traces,
                "idle_sessions": counts["idle_sessions"],
                "learning_observations": observations,
                "trace_row_quota": trace_quota,
                "trace_occupancy_basis": "all_retained_rows",
            },
            "redis": {
                "daily_cost_key": aggregates["llm_cost_key"],
                "value_present": aggregates["llm_cost_present"],
                "cost_basis": "reservation_estimate",
            },
            "prometheus": {
                "scrape_url": settings["metrics_url"],
                "llm_request_series": counts["llm_request_series"],
            },
        },
    }


def query_scalar(cursor, sql: str, params: tuple = ()) -> float:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    return float((row or (0,))[0] or 0)


def collect(args: argparse.Namespace) -> tuple[dict, dict]:
    # Validate operator settings before opening any external connections.
    window_seconds = int(finite_number(args.window_seconds, "window_seconds", minimum=1, integer=True))
    idle_seconds = finite_number(args.idle_seconds, "idle_seconds", minimum=1, maximum=window_seconds)
    finite_number(args.trace_row_quota, "trace_row_quota", minimum=1, integer=True)
    config = {
        "session_ttl_hours": args.session_ttl_hours,
        "agent_trace_retention_days": args.trace_retention_days,
        "tenant_storage_quota_mb": args.tenant_storage_quota_mb,
        "tenant_knowledge_base_quota": args.tenant_knowledge_base_quota,
        "llm_daily_budget_usd": args.llm_daily_budget_usd,
    }
    recommend_policy({}, config)
    captured = datetime.now(timezone.utc)
    try:
        window_start = (captured - timedelta(seconds=window_seconds)).replace(tzinfo=None)
        idle_before = (captured - timedelta(seconds=idle_seconds)).replace(tzinfo=None)
    except OverflowError as error:
        raise ValueError("window_seconds is too large for a timestamp interval") from error

    import mysql.connector
    from prometheus_client.parser import text_string_to_metric_families
    from redis import Redis

    connection = mysql.connector.connect(
        host=args.mysql_host,
        port=args.mysql_port,
        database=args.mysql_database,
        user=args.mysql_user,
        password=args.mysql_password,
        connection_timeout=10,
    )
    try:
        cursor = connection.cursor()
        users = query_scalar(cursor, "SELECT COUNT(*) FROM user")
        active_sessions = query_scalar(
            cursor,
            "SELECT COUNT(*) FROM auth_session WHERE revoked_at IS NULL AND expires_at > %s "
            "AND last_seen_at >= %s AND last_seen_at < %s",
            (captured.replace(tzinfo=None), window_start, captured.replace(tzinfo=None)),
        )
        idle_sessions = query_scalar(
            cursor,
            "SELECT COUNT(*) FROM auth_session WHERE revoked_at IS NULL AND expires_at > %s "
            "AND last_seen_at >= %s AND last_seen_at < %s",
            (captured.replace(tzinfo=None), window_start, idle_before),
        )
        max_storage = query_scalar(
            cursor,
            "SELECT COALESCE(MAX(total_bytes),0) FROM ("
            "SELECT kb.user_id, SUM(v.size_bytes) total_bytes FROM knowledge_document_version v "
            "JOIN knowledge_document d ON d.id=v.document_id JOIN knowledge_base kb ON kb.id=d.kb_id "
            "GROUP BY kb.user_id) usage_by_user",
        )
        max_kbs = query_scalar(
            cursor,
            "SELECT COALESCE(MAX(total_kbs),0) FROM (SELECT user_id, COUNT(*) total_kbs "
            "FROM knowledge_base WHERE status='active' GROUP BY user_id) kb_by_user",
        )
        trace_rows_window = query_scalar(
            cursor, "SELECT COUNT(*) FROM agent_trace WHERE created_at >= %s AND created_at < %s",
            (window_start, captured.replace(tzinfo=None)),
        )
        trace_rows_total = query_scalar(cursor, "SELECT COUNT(*) FROM agent_trace")
        observations = query_scalar(
            cursor,
            "SELECT COUNT(*) FROM learning_outcome_event WHERE created_at >= %s AND created_at < %s",
            (window_start, captured.replace(tzinfo=None)),
        )
        retention = query_scalar(
            cursor,
            "SELECT COALESCE(AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END),0) "
            "FROM learning_outcome_event WHERE created_at >= %s AND created_at < %s",
            (window_start, captured.replace(tzinfo=None)),
        )
        cursor.close()
    finally:
        connection.close()

    day = captured.date().isoformat()
    cost_key = f"mneme:llm:cost:{day}"
    redis = Redis(
        host=args.redis_host, port=args.redis_port, db=args.redis_db,
        password=args.redis_password or None, socket_timeout=5, decode_responses=True,
    )
    try:
        redis.ping()
        raw_cost = redis.get(cost_key)
        cost_captured = datetime.now(timezone.utc)
    finally:
        redis.close()
    if cost_captured.date() != captured.date():
        raise ValueError("UTC day changed during collection; retry for a consistent cost interval")

    with urlopen(args.metrics_url, timeout=10) as response:
        families = list(text_string_to_metric_families(response.read().decode("utf-8")))
    llm_request_series = sum(
        1 for family in families if family.name == "mneme_llm_requests"
        for sample in family.samples
        if sample.name == "mneme_llm_requests_total" and sample.value > 0
    )
    aggregates = {
        "users": users, "active_sessions": active_sessions, "idle_sessions": idle_sessions,
        "max_storage_bytes": max_storage, "max_knowledge_bases": max_kbs,
        "trace_rows_total": trace_rows_total, "trace_rows_window": trace_rows_window,
        "learning_observations": observations, "retention_rate": retention,
        "llm_daily_cost_usd": finite_number(raw_cost if raw_cost is not None else 0, "llm_daily_cost_usd"),
        "llm_cost_present": raw_cost is not None,
        "llm_cost_key": cost_key, "llm_request_series": llm_request_series,
        "cost_period_start": captured.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
        "cost_period_end": cost_captured.isoformat(),
    }
    snapshot = build_snapshot(aggregates, {
        "tenant_storage_quota_bytes": args.tenant_storage_quota_mb * 1024 * 1024,
        "tenant_knowledge_base_quota": args.tenant_knowledge_base_quota,
        "trace_row_quota": args.trace_row_quota,
        "measurement_window_seconds": args.window_seconds,
        "metrics_url": args.metrics_url,
        "environment": args.environment,
        "cost_scope": args.cost_scope,
    }, cost_captured.isoformat())
    snapshot["measurement_window_start"] = window_start.replace(tzinfo=timezone.utc).isoformat()
    snapshot["measurement_window_end"] = captured.isoformat()
    return snapshot, config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usage-report", type=Path, required=True)
    parser.add_argument("--config-report", type=Path, required=True)
    parser.add_argument("--environment", choices=("production", "staging", "test", "unspecified"), default="unspecified")
    parser.add_argument("--cost-scope", help="deployment/account/provider scope covered by the shared Redis cost key")
    parser.add_argument("--mysql-host", default=os.getenv("MYSQL_HOST", "127.0.0.1"))
    parser.add_argument("--mysql-port", type=int, default=int(os.getenv("MYSQL_PORT", "3306")))
    parser.add_argument("--mysql-database", default=os.getenv("MYSQL_DATABASE", "mneme"))
    parser.add_argument("--mysql-user", default=os.getenv("MYSQL_USER", "root"))
    parser.add_argument("--mysql-password", default=os.getenv("MYSQL_PASSWORD", os.getenv("MYSQL_ROOT_PASSWORD", "")))
    parser.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "127.0.0.1"))
    parser.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", "6379")))
    parser.add_argument("--redis-db", type=int, default=int(os.getenv("REDIS_DB", "0")))
    parser.add_argument("--redis-password", default=os.getenv("REDIS_PASSWORD", ""))
    parser.add_argument("--metrics-url", default="http://127.0.0.1:8001/metrics")
    parser.add_argument("--window-seconds", type=int, default=86400)
    parser.add_argument("--idle-seconds", type=int, default=43200)
    parser.add_argument("--trace-row-quota", type=int, default=int(os.getenv("AGENT_TRACE_ROW_QUOTA", "100000")))
    parser.add_argument("--session-ttl-hours", type=int, default=int(os.getenv("SESSION_TTL_HOURS", "24")))
    parser.add_argument("--trace-retention-days", type=int, default=int(os.getenv("AGENT_TRACE_RETENTION_DAYS", "30")))
    parser.add_argument("--tenant-storage-quota-mb", type=int, default=int(os.getenv("TENANT_STORAGE_QUOTA_MB", "2048")))
    parser.add_argument("--tenant-knowledge-base-quota", type=int, default=int(os.getenv("TENANT_KNOWLEDGE_BASE_QUOTA", "100")))
    parser.add_argument("--llm-daily-budget-usd", type=float, default=float(os.getenv("LLM_DAILY_BUDGET_USD", "0")))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.usage_report.resolve() == args.config_report.resolve():
        raise ValueError("usage-report and config-report must be different files")
    usage, config = collect(args)
    for path, payload in ((args.usage_report, usage), (args.config_report, config)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"usage_report": str(args.usage_report), "config_report": str(args.config_report), "sample_count": usage["sample_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
