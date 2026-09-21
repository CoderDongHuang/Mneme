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
