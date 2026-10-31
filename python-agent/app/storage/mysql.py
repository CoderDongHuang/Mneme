"""Small MySQL adapter for auxiliary state shared by Python replicas."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from app.core.config import settings


_CONNECT_ATTEMPTS = 30
_CONNECT_RETRY_SECONDS = 1.0
_TRANSIENT_CONNECTION_ERRNOS = {2002, 2003, 2005, 2006, 2013}


def _connector():
    try:
        import mysql.connector  # type: ignore
    except ImportError as error:  # pragma: no cover - exercised only in shared mode
        raise RuntimeError("AUXILIARY_STORE_BACKEND=mysql 需要 mysql-connector-python") from error
    return mysql.connector


def _connect(connector):
    for attempt in range(_CONNECT_ATTEMPTS):
        try:
            return connector.connect(
                host=settings.mysql_host,
                port=settings.mysql_port,
                database=settings.mysql_database,
                user=settings.mysql_user,
                password=settings.mysql_password,
                autocommit=False,
                time_zone="+00:00",
            )
        except connector.Error as error:
            if getattr(error, "errno", None) not in _TRANSIENT_CONNECTION_ERRNOS or attempt == _CONNECT_ATTEMPTS - 1:
                raise
            time.sleep(_CONNECT_RETRY_SECONDS)


@contextmanager
def connection() -> Iterator[object]:
    connector = _connector()
    conn = _connect(connector)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def placeholders(count: int) -> str:
    return ",".join(["%s"] * count)


def require_tables(*tables: str) -> None:
    """Wait for Gateway Flyway, without granting DDL to the Python runtime."""
    allowed = {"agent_trace", "memory_version", "agent_tool_usage", "agent_tool_approval", "knowledge_index_state"}
    if not tables or not set(tables) <= allowed:
        raise ValueError("Unsupported auxiliary schema check")
    connector = _connector()
    for attempt in range(90):
        try:
            with connection() as conn:
                cursor = conn.cursor()
                try:
                    for table in tables:
                        cursor.execute(f"SELECT 1 FROM `{table}` LIMIT 0")
                        cursor.fetchall()
                finally:
                    cursor.close()
            return
        except connector.Error as error:
            if getattr(error, "errno", None) != 1146:
                raise
            if attempt == 89:
                raise RuntimeError("Auxiliary MySQL schema is missing; run Gateway Flyway migrations before starting Python") from None
            time.sleep(1)
