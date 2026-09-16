from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Callable

from app.agents.trace_store import agent_trace_store
from app.core.config import settings

from app.knowledge.retriever import retrieve
from app.memory.memory_store import memory_store


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    owner: str
    audited: bool = True


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolSpec, Callable]] = {}
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="agent-tool")

    def register(self, spec: ToolSpec, handler: Callable) -> None:
        self._tools[spec.name] = (spec, handler)

    def list_specs(self) -> list[dict]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema,
                "owner": spec.owner,
                "audited": spec.audited,
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
    ) -> Any:
        if name not in self._tools:
            raise KeyError(f"未注册工具: {name}")
        spec, handler = self._tools[name]
        self._validate(spec, arguments)
        attempts = settings.agent_tool_max_attempts
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            future = self._executor.submit(handler, **arguments)
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
    ),
    retrieve,
)
tool_registry.register(
    ToolSpec(
        name="memory.read",
        description="Read long-term user memory by category.",
        input_schema={"user_id": "string", "category": "string"},
        owner="memory",
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
    ),
    memory_store.add_memory,
)
