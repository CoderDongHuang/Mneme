from dataclasses import dataclass
from typing import Callable

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
