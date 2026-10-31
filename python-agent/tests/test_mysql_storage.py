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
        assert _kwargs['time_zone'] == '+00:00'
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


@pytest.mark.parametrize("failures,errno,expected_attempts", [(2, 1146, 3), (90, 1146, 90), (1, 1142, 1)])
def test_schema_wait_uses_select_and_closes_failed_connections(monkeypatch, failures, errno, expected_attempts):
    statements, opened, sleeps = [], [], []

    class Cursor:
        closed = False

        def execute(self, sql):
            statements.append(sql)
            assert sql == "SELECT 1 FROM `agent_trace` LIMIT 0"
            if len(opened) <= failures:
                raise ConnectorError(errno)

        def fetchall(self):
            return []

        def close(self):
            self.closed = True

    class SchemaConnection(Connection):
        rolled_back = False

        def __init__(self):
            super().__init__()
            self.schema_cursor = Cursor()

        def cursor(self):
            return self.schema_cursor

        def rollback(self):
            self.rolled_back = True

    def connect(**_kwargs):
        conn = SchemaConnection()
        opened.append(conn)
        return conn

    monkeypatch.setattr(mysql, "_connector", lambda: SimpleNamespace(Error=ConnectorError, connect=connect))
    monkeypatch.setattr(mysql.time, "sleep", sleeps.append)
    if errno != 1146:
        with pytest.raises(ConnectorError):
            mysql.require_tables("agent_trace")
    elif failures == 90:
        with pytest.raises(RuntimeError, match="run Gateway Flyway"):
            mysql.require_tables("agent_trace")
    else:
        mysql.require_tables("agent_trace")
        assert opened[-1].committed
    assert len(opened) == expected_attempts
    assert len(sleeps) == (expected_attempts - 1)
    assert all(conn.closed and conn.schema_cursor.closed for conn in opened)
    assert all(conn.rolled_back for conn in opened[:min(failures, expected_attempts)])


@pytest.mark.parametrize("tables", [(), ("user",), ("agent_trace; DROP DATABASE mneme",)])
def test_schema_wait_rejects_unexpected_identifiers_before_connecting(monkeypatch, tables):
    def unexpected():
        raise AssertionError("must validate before connecting")

    monkeypatch.setattr(mysql, "_connector", unexpected)
    with pytest.raises(ValueError):
        mysql.require_tables(*tables)


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
    monkeypatch.setattr(registry_module, "require_tables", lambda *tables: None)
    monkeypatch.setattr(version_store_module, "settings", shared_settings)

    ToolRegistry()._consume_quota("knowledge.retrieve", "u1", 1)
    store = MemoryVersionStore.__new__(MemoryVersionStore)
    assert store.snapshot({"id": "m1", "user_id": "u1", "content": "fact"}, "create") == 1
