"""Small MySQL adapter for auxiliary state shared by Python replicas."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from app.core.config import settings


def _connector():
    try:
        import mysql.connector  # type: ignore
    except ImportError as error:  # pragma: no cover - exercised only in shared mode
        raise RuntimeError("AUXILIARY_STORE_BACKEND=mysql 需要 mysql-connector-python") from error
    return mysql.connector


@contextmanager
def connection() -> Iterator[object]:
    connector = _connector()
    conn = connector.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=settings.mysql_database,
        user=settings.mysql_user,
        password=settings.mysql_password,
        autocommit=False,
    )
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
