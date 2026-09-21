from types import SimpleNamespace

import pytest

from app.storage import mysql


class ConnectorError(Exception):
    def __init__(self, errno: int):
        super().__init__(f"mysql error {errno}")
        self.errno = errno


class Connection:
    def __init__(self):
        self.committed = False
        self.closed = False

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("rollback should not be called")

    def close(self):
        self.closed = True


def test_connection_retries_transient_startup_failure(monkeypatch):
    connection = Connection()
    attempts = []

    def connect(**_kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectorError(2003)
        return connection

    connector = SimpleNamespace(Error=ConnectorError, connect=connect)
    monkeypatch.setattr(mysql, "_connector", lambda: connector)
    monkeypatch.setattr(mysql.time, "sleep", lambda _seconds: None)

    with mysql.connection() as opened:
        assert opened is connection

    assert len(attempts) == 3
    assert connection.committed
    assert connection.closed


def test_connection_does_not_retry_non_transient_error(monkeypatch):
    attempts = []

    def connect(**_kwargs):
        attempts.append(1)
        raise ConnectorError(1045)

    connector = SimpleNamespace(Error=ConnectorError, connect=connect)
    monkeypatch.setattr(mysql, "_connector", lambda: connector)

    with pytest.raises(ConnectorError):
        with mysql.connection():
            pass

    assert len(attempts) == 1
