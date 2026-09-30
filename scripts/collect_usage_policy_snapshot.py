#!/usr/bin/env python3
"""Collect privacy-safe aggregate usage evidence for policy recommendations."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen

def clamp_ratio(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 6)


def build_snapshot(aggregates: dict[str, float], settings: dict[str, float], captured_at: str) -> dict:
    users = int(aggregates["users"])
    active_sessions = int(aggregates["active_sessions"])
    traces = int(aggregates["traces"])
    observations = int(aggregates["learning_observations"])
    # Only windowed observations support a windowed policy recommendation.
    # Prometheus request counters are cumulative since process start.
    sample_count = max(active_sessions, traces, observations)
    if sample_count < 1:
        raise ValueError("usage collection found no measurable samples")
    storage_quota = max(1.0, settings["tenant_storage_quota_bytes"])
    kb_quota = max(1.0, settings["tenant_knowledge_base_quota"])
    trace_quota = max(1.0, settings["trace_row_quota"])
    return {
        "captured_at": captured_at,
        "source": "mneme-aggregate-collector",
        "sample_count": sample_count,
        "measurement_window_seconds": int(settings["measurement_window_seconds"]),
        "llm_daily_cost_usd": round(float(aggregates["llm_daily_cost_usd"]), 8),
        "storage_usage_ratio": clamp_ratio(float(aggregates["max_storage_bytes"]) / storage_quota),
        "trace_usage_ratio": clamp_ratio(traces / trace_quota),
        "session_idle_ratio": clamp_ratio(
            float(aggregates["idle_sessions"]) / active_sessions if active_sessions else 0.0
        ),
        "knowledge_base_usage_ratio": clamp_ratio(
            float(aggregates["max_knowledge_bases"]) / kb_quota
        ),
        "learning_observations": observations,
        "retention_rate": clamp_ratio(float(aggregates["retention_rate"])),
        "evidence": {
            "mysql": {
                "aggregates_only": True,
                "users": users,
                "active_sessions": active_sessions,
                "trace_rows": traces,
            },
            "redis": {
                "daily_cost_key": aggregates["llm_cost_key"],
                "value_present": bool(aggregates["llm_cost_present"]),
            },
            "prometheus": {
                "scrape_url": settings["metrics_url"],
                "llm_request_series": int(aggregates["llm_request_series"]),
            },
        },
    }


def query_scalar(cursor, sql: str, params: tuple = ()) -> float:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    return float((row or (0,))[0] or 0)


def collect(args: argparse.Namespace) -> tuple[dict, dict]:
    import mysql.connector
    from prometheus_client.parser import text_string_to_metric_families
    from redis import Redis

    captured = datetime.now(timezone.utc)
    window_start = (captured - timedelta(seconds=args.window_seconds)).replace(tzinfo=None)
    idle_before = (captured - timedelta(seconds=args.idle_seconds)).replace(tzinfo=None)
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
            "AND last_seen_at >= %s",
            (captured.replace(tzinfo=None), window_start),
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
        traces = query_scalar(
            cursor, "SELECT COUNT(*) FROM agent_trace WHERE created_at >= %s", (window_start,)
        )
        observations = query_scalar(
            cursor,
            "SELECT COUNT(*) FROM learning_outcome_event WHERE created_at >= %s",
            (window_start,),
        )
        retention = query_scalar(
            cursor,
            "SELECT COALESCE(AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END),0) "
            "FROM learning_outcome_event WHERE created_at >= %s",
            (window_start,),
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
    redis.ping()
    raw_cost = redis.get(cost_key)

    with urlopen(args.metrics_url, timeout=10) as response:
        families = list(text_string_to_metric_families(response.read().decode("utf-8")))
    llm_request_series = sum(
        1 for family in families if family.name == "mneme_llm_requests"
        for sample in family.samples
        if sample.name == "mneme_llm_requests_total" and sample.value > 0
    )
    aggregates = {
        "users": users, "active_sessions": active_sessions, "idle_sessions": idle_sessions,
        "max_storage_bytes": max_storage, "max_knowledge_bases": max_kbs, "traces": traces,
        "learning_observations": observations, "retention_rate": retention,
        "llm_daily_cost_usd": float(raw_cost or 0), "llm_cost_present": raw_cost is not None,
        "llm_cost_key": cost_key, "llm_request_series": llm_request_series,
    }
    config = {
        "session_ttl_hours": args.session_ttl_hours,
        "agent_trace_retention_days": args.trace_retention_days,
        "tenant_storage_quota_mb": args.tenant_storage_quota_mb,
        "tenant_knowledge_base_quota": args.tenant_knowledge_base_quota,
        "llm_daily_budget_usd": args.llm_daily_budget_usd,
    }
    snapshot = build_snapshot(aggregates, {
        "tenant_storage_quota_bytes": args.tenant_storage_quota_mb * 1024 * 1024,
        "tenant_knowledge_base_quota": args.tenant_knowledge_base_quota,
        "trace_row_quota": args.trace_row_quota,
        "measurement_window_seconds": args.window_seconds,
        "metrics_url": args.metrics_url,
    }, captured.isoformat())
    return snapshot, config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usage-report", type=Path, required=True)
    parser.add_argument("--config-report", type=Path, required=True)
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
    usage, config = collect(args)
    for path, payload in ((args.usage_report, usage), (args.config_report, config)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"usage_report": str(args.usage_report), "config_report": str(args.config_report), "sample_count": usage["sample_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
