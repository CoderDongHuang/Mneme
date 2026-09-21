from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextvars import copy_context
from datetime import datetime, timezone
import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import threading
from typing import Any, Callable

from app.agents.trace_store import agent_trace_store
from app.core.config import settings
from app.storage.mysql import connection as mysql_connection

from app.knowledge.retriever import retrieve
from app.memory.memory_store import memory_store


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    owner: str
    audited: bool = True
    required_scopes: frozenset[str] = frozenset()
    quota_units: int = 1
    requires_approval: bool = False
    isolation_profile: str = "thread"


@dataclass(frozen=True)
class SubprocessTool:
    command: tuple[str, ...]
    max_output_bytes: int = 1_048_576

    def execute(self, arguments: dict[str, Any]) -> Any:
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
        }
        for name in ("SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP"):
            if os.environ.get(name):
                environment[name] = os.environ[name]
        with tempfile.TemporaryDirectory(prefix="mneme-tool-") as working_directory:
            result = subprocess.run(
                self.command,
                input=json.dumps(arguments, ensure_ascii=False),
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=working_directory,
                env=environment,
                timeout=max(0.1, settings.agent_tool_timeout_seconds),
                check=False,
            )
        if result.returncode != 0:
            raise RuntimeError(f"隔离工具退出码 {result.returncode}: {result.stderr[:1000]}")
        if len(result.stdout.encode("utf-8")) > self.max_output_bytes:
            raise RuntimeError("隔离工具输出超过限制")
        return json.loads(result.stdout)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolSpec, Callable]] = {}
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="agent-tool")
        self._lock = threading.Lock()
        self._usage: dict[tuple[str, str], tuple[str, int]] = {}
        self._approvals: dict[str, tuple[str, str, float]] = {}
        if settings.auxiliary_store_backend == "mysql":
            self._init_governance_store()

    def _init_governance_store(self) -> None:
        with mysql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_tool_usage (
                    user_id VARCHAR(128) NOT NULL, usage_date DATE NOT NULL,
                    used_units INT NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, usage_date)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_tool_approval (
                    token_hash CHAR(64) PRIMARY KEY, tool_name VARCHAR(255) NOT NULL,
                    user_id VARCHAR(128) NOT NULL, approved_by VARCHAR(128) NOT NULL,
                    expires_at TIMESTAMP NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_tool_approval_lookup (tool_name, user_id, expires_at)
                )
            """)
            cursor.execute("DELETE FROM agent_tool_usage WHERE usage_date < DATE_SUB(UTC_DATE(), INTERVAL 31 DAY)")
            cursor.execute("DELETE FROM agent_tool_approval WHERE expires_at < UTC_TIMESTAMP()")
            cursor.close()

    def register(self, spec: ToolSpec, handler: Callable) -> None:
        if not spec.name or not spec.owner or not spec.audited:
            raise ValueError("工具必须有 owner 且完成审计后才能注册")
        if spec.quota_units < 1 or spec.isolation_profile not in {"thread", "subprocess"}:
            raise ValueError("工具配额或隔离级别不合法")
        self._tools[spec.name] = (spec, handler)

    def approve(self, tool_name: str, user_id: str, approved_by: str, ttl_seconds: int | None = None) -> str:
        if tool_name not in self._tools:
            raise KeyError(f"未注册工具: {tool_name}")
        token = secrets.token_urlsafe(32)
        ttl = max(60, int(ttl_seconds or settings.agent_tool_approval_ttl_seconds))
        expires_at = datetime.now(timezone.utc).timestamp() + ttl
        if settings.auxiliary_store_backend == "mysql":
            with mysql_connection() as connection:
                cursor = connection.cursor()
                cursor.execute(
                    "INSERT INTO agent_tool_approval(token_hash,tool_name,user_id,approved_by,expires_at) VALUES(%s,%s,%s,%s,FROM_UNIXTIME(%s))",
                    (hashlib.sha256(token.encode()).hexdigest(), tool_name, str(user_id), approved_by, expires_at),
                )
                cursor.close()
        else:
            with self._lock:
                self._approvals[token] = (tool_name, str(user_id), expires_at)
        agent_trace_store.record(str(user_id), "tool-approval", f"tool.{tool_name}", "approved", {"approved_by": approved_by, "ttl_seconds": ttl})
        return token

    def list_specs(self) -> list[dict]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema,
                "owner": spec.owner,
                "audited": spec.audited,
                "required_scopes": sorted(spec.required_scopes),
                "quota_units": spec.quota_units,
                "requires_approval": spec.requires_approval,
                "isolation_profile": spec.isolation_profile,
            }
            for spec, _ in sorted(self._tools.values(), key=lambda item: item[0].name)
        ]

    def get(self, name: str) -> Callable:
        if name not in self._tools:
            raise KeyError(name)
        return self._tools[name][1]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        trace_user_id: str | None = None,
        trace_session_id: str | None = None,
        principal_scopes: set[str] | frozenset[str] | None = None,
        approval_token: str | None = None,
    ) -> Any:
        if name not in self._tools:
            raise KeyError(f"未注册工具: {name}")
        spec, handler = self._tools[name]
        self._validate(spec, arguments)
        user_id = str(trace_user_id or arguments.get("user_id", ""))
        scopes = set(principal_scopes or ())
        if not spec.required_scopes.issubset(scopes):
            raise PermissionError(f"工具 {name} 缺少权限范围: {', '.join(sorted(spec.required_scopes - scopes))}")
        if spec.requires_approval and not self._valid_approval(approval_token, name, user_id):
            raise PermissionError(f"工具 {name} 需要管理员审批")
        if spec.isolation_profile == "subprocess" and not isinstance(handler, SubprocessTool):
            raise RuntimeError(f"工具 {name} 缺少隔离进程适配器")
        self._consume_quota(name, user_id, spec.quota_units)
        attempts = settings.agent_tool_max_attempts
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            context = copy_context()
            invocation = handler.execute if isinstance(handler, SubprocessTool) else handler
            invocation_args = (arguments,) if isinstance(handler, SubprocessTool) else ()
            invocation_kwargs = {} if isinstance(handler, SubprocessTool) else arguments
            future = self._executor.submit(context.run, invocation, *invocation_args, **invocation_kwargs)
            try:
                result = future.result(timeout=max(0.1, settings.agent_tool_timeout_seconds))
                self._trace(name, trace_user_id, trace_session_id, "ok", attempt, arguments)
                return result
            except FutureTimeoutError:
                future.cancel()
                last_error = TimeoutError(
                    f"工具 {name} 超过 {settings.agent_tool_timeout_seconds:g} 秒未完成"
                )
            except Exception as error:
                last_error = error
            self._trace(name, trace_user_id, trace_session_id, "retry", attempt, arguments, last_error)
        assert last_error is not None
        self._trace(name, trace_user_id, trace_session_id, "error", attempts, arguments, last_error)
        raise last_error

    def _valid_approval(self, token: str | None, name: str, user_id: str) -> bool:
        if not token:
            return False
        if settings.auxiliary_store_backend == "mysql":
            with mysql_connection() as connection:
                cursor = connection.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM agent_tool_approval WHERE token_hash=%s AND tool_name=%s AND user_id=%s AND expires_at>UTC_TIMESTAMP()",
                    (hashlib.sha256(token.encode()).hexdigest(), name, user_id),
                )
                valid = int(cursor.fetchone()[0]) == 1
                cursor.close()
                return valid
        with self._lock:
            approval = self._approvals.get(token)
            if not approval or approval[0] != name or approval[1] != user_id:
                return False
            if approval[2] < datetime.now(timezone.utc).timestamp():
                self._approvals.pop(token, None)
                return False
            return True

    def _consume_quota(self, name: str, user_id: str, units: int) -> None:
        if not user_id:
            return
        day = datetime.now(timezone.utc).date().isoformat()
        if settings.auxiliary_store_backend == "mysql":
            with mysql_connection() as connection:
                cursor = connection.cursor()
                lock_name = f"mneme-tool-quota:{user_id}:{day}"[:64]
                cursor.execute("SELECT GET_LOCK(%s, 10)", (lock_name,))
                if cursor.fetchone()[0] != 1:
                    cursor.close()
                    raise RuntimeError("无法取得工具配额锁")
                try:
                    cursor.execute("SELECT used_units FROM agent_tool_usage WHERE user_id=%s AND usage_date=%s", (user_id, day))
                    row = cursor.fetchone()
                    used = int(row[0]) if row else 0
                    if used + units > settings.agent_tool_daily_quota:
                        raise RuntimeError(f"用户工具配额已用尽: {settings.agent_tool_daily_quota}")
                    cursor.execute(
                        "INSERT INTO agent_tool_usage(user_id,usage_date,used_units) VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE used_units=VALUES(used_units)",
                        (user_id, day, used + units),
                    )
                    return
                finally:
                    cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
                    cursor.fetchone()
                    cursor.close()
        key = (user_id, day)
        with self._lock:
            _, used = self._usage.get(key, (day, 0))
            if used + units > settings.agent_tool_daily_quota:
                raise RuntimeError(f"用户工具配额已用尽: {settings.agent_tool_daily_quota}")
            self._usage[key] = (day, used + units)

    def delete_user_governance(self, user_id: str) -> int:
        if settings.auxiliary_store_backend == "mysql":
            deleted = 0
            with mysql_connection() as connection:
                cursor = connection.cursor()
                for table in ("agent_tool_usage", "agent_tool_approval"):
                    cursor.execute(f"DELETE FROM {table} WHERE user_id=%s", (str(user_id),))
                    deleted += max(0, cursor.rowcount)
                cursor.close()
            return deleted
        with self._lock:
            usage_keys = [key for key in self._usage if key[0] == str(user_id)]
            approval_keys = [key for key, value in self._approvals.items() if value[1] == str(user_id)]
            for key in usage_keys:
                self._usage.pop(key, None)
            for key in approval_keys:
                self._approvals.pop(key, None)
            return len(usage_keys) + len(approval_keys)

    def _validate(self, spec: ToolSpec, arguments: dict[str, Any]) -> None:
        unknown = set(arguments) - set(spec.input_schema)
        missing = set(spec.input_schema) - set(arguments)
        if unknown or missing:
            raise ValueError(
                f"工具 {spec.name} 参数不合法: missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        expected_types = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
        }
        for field, declared in spec.input_schema.items():
            expected = expected_types.get(str(declared))
            if expected and (not isinstance(arguments[field], expected) or (
                declared in {"integer", "number"} and isinstance(arguments[field], bool)
            )):
                raise TypeError(f"工具 {spec.name} 参数 {field} 必须是 {declared}")

    def _trace(
        self,
        name: str,
        user_id: str | None,
        session_id: str | None,
        status: str,
        attempt: int,
        arguments: dict[str, Any],
        error: Exception | None = None,
    ) -> None:
        if not user_id or not session_id:
            return
        agent_trace_store.record(
            user_id,
            session_id,
            f"tool.{name}",
            status,
            {"attempt": attempt, "arguments": arguments},
            error=str(error) if error else "",
        )


tool_registry = ToolRegistry()

tool_registry.register(
    ToolSpec(
        name="knowledge.retrieve",
        description="Retrieve cited chunks from a user's knowledge base.",
        input_schema={
            "user_id": "string",
            "kb_id": "string",
            "query": "string",
            "top_k": "integer",
        },
        owner="knowledge",
        required_scopes=frozenset({"knowledge.read"}),
    ),
    retrieve,
)
tool_registry.register(
    ToolSpec(
        name="memory.read",
        description="Read long-term user memory by category.",
        input_schema={"user_id": "string", "category": "string"},
        owner="memory",
        required_scopes=frozenset({"memory.read"}),
    ),
    memory_store.get_by_category,
)
tool_registry.register(
    ToolSpec(
        name="memory.write",
        description="Write a long-term memory entry after confirmation or high-confidence distillation.",
        input_schema={
            "user_id": "string",
            "category": "string",
            "content": "string",
            "topic": "string",
            "importance": "number",
        },
        owner="memory",
        required_scopes=frozenset({"memory.write"}),
    ),
    memory_store.add_memory,
)
