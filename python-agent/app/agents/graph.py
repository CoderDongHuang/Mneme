from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.agents.nodes import (
    format_response_node,
    intent_classification_node,
    knowledge_retrieval_node,
    llm_reasoning_node,
    memory_retrieval_node,
    memory_write_node,
    suggestion_generation_node,
    weak_point_retrieval_node,
)


class AgentState(TypedDict, total=False):
    user_id: str
    session_id: str
    message: str
    knowledge_base_ids: list[str]
    intent: str
    confidence: float
    context: str
    memory_context: str
    answer: str
    retrieved_chunks: list[dict]
    memory_entries_to_write: list[dict]
    pending_memories: list[dict]


def route_by_intent(state: AgentState) -> str:
    return {
        "qa": "knowledge_retrieval",
        "review": "memory_retrieval",
        "suggest": "weak_point_retrieval",
    }.get(state.get("intent", "general"), "llm_reasoning")


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("intent_classification", intent_classification_node)
    graph.add_node("knowledge_retrieval", knowledge_retrieval_node)
    graph.add_node("memory_retrieval", memory_retrieval_node)
    graph.add_node("weak_point_retrieval", weak_point_retrieval_node)
    graph.add_node("suggestion_generation", suggestion_generation_node)
    graph.add_node("llm_reasoning", llm_reasoning_node)
    graph.add_node("format_response", format_response_node)
    graph.add_node("memory_write", memory_write_node)
    graph.set_entry_point("intent_classification")
    graph.add_conditional_edges("intent_classification", route_by_intent)
    graph.add_edge("knowledge_retrieval", "llm_reasoning")
    graph.add_edge("memory_retrieval", "llm_reasoning")
    graph.add_edge("weak_point_retrieval", "suggestion_generation")
    graph.add_edge("suggestion_generation", "llm_reasoning")
    graph.add_edge("llm_reasoning", "format_response")
    graph.add_edge("format_response", "memory_write")
    graph.add_edge("memory_write", END)
    return graph.compile()


agent_graph = build_graph()
