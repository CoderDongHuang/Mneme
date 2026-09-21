from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import app.memory.version_store as version_store_module
import app.tools.registry as registry_module
from app.memory.version_store import MemoryVersionStore
from app.storage import mysql
from app.tools.registry import ToolRegistry


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


class StrictCursor:
    def __init__(self):
        self.pending_result = None
        self.has_pending_result = False

    def execute(self, statement, _parameters=()):
        if self.has_pending_result:
            raise AssertionError("previous result was not consumed")
        if "GET_LOCK" in statement or "RELEASE_LOCK" in statement:
            self.pending_result = (1,)
            self.has_pending_result = True
        elif "SELECT used_units" in statement:
            self.pending_result = None
            self.has_pending_result = True
        elif "SELECT COALESCE(MAX(version)" in statement:
            self.pending_result = (0,)
            self.has_pending_result = True

    def fetchone(self):
        if not self.has_pending_result:
            raise AssertionError("no result is available")
        result = self.pending_result
        self.pending_result = None
        self.has_pending_result = False
        return result

    def close(self):
        if self.has_pending_result:
            raise AssertionError("Unread result found")


class StrictConnection:
    def cursor(self):
        return StrictCursor()


@contextmanager
def strict_connection():
    yield StrictConnection()


def test_named_lock_results_are_consumed_before_cursor_close(monkeypatch):
    shared_settings = SimpleNamespace(auxiliary_store_backend="mysql", agent_tool_daily_quota=100)
    monkeypatch.setattr(registry_module, "mysql_connection", strict_connection)
    monkeypatch.setattr(version_store_module, "mysql_connection", strict_connection)
    monkeypatch.setattr(registry_module, "settings", shared_settings)
    monkeypatch.setattr(version_store_module, "settings", shared_settings)

    ToolRegistry()._consume_quota("knowledge.retrieve", "u1", 1)
    store = MemoryVersionStore.__new__(MemoryVersionStore)
    assert store.snapshot({"id": "m1", "user_id": "u1", "content": "fact"}, "create") == 1
