from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Optional
from .nodes import (
    intent_classification_node,
    knowledge_retrieval_node,
    memory_retrieval_node,
    weak_point_retrieval_node,
    llm_reasoning_node,
    suggestion_generation_node,
    format_response_node,
    memory_write_node
)

class AgentState(TypedDict):
    user_id: str
    session_id: str
    message: str
    knowledge_base_ids: List[str]
    intent: str
    confidence: float
    context: str
    memory_context: str
    weak_points: str
    answer: str
    suggestions: List[str]
    memory_entries_to_write: List[dict]

def route_by_intent(state: AgentState) -> str:
    intent = state["intent"]
    if intent == "qa":
        return "knowledge_retrieval"
    elif intent == "review":
        return "memory_retrieval"
    elif intent == "suggest":
        return "weak_point_retrieval"
    elif intent == "general":
        return "llm_reasoning"
    return "llm_reasoning"

def build_graph():
    graph = StateGraph(AgentState)

    # 节点
    graph.add_node("intent_classification", intent_classification_node)
    graph.add_node("knowledge_retrieval", knowledge_retrieval_node)
    graph.add_node("memory_retrieval", memory_retrieval_node)
    graph.add_node("weak_point_retrieval", weak_point_retrieval_node)
    graph.add_node("llm_reasoning", llm_reasoning_node)
    graph.add_node("suggestion_generation", suggestion_generation_node)
    graph.add_node("format_response", format_response_node)
    graph.add_node("memory_write", memory_write_node)

    # 边
    graph.set_entry_point("intent_classification")
    graph.add_conditional_edges("intent_classification", route_by_intent)

    # qa 链路
    graph.add_edge("knowledge_retrieval", "llm_reasoning")

    # review 链路
    graph.add_edge("memory_retrieval", "llm_reasoning")

    # suggest 链路
    graph.add_edge("weak_point_retrieval", "suggestion_generation")
    graph.add_edge("suggestion_generation", "llm_reasoning")

    # 统一链路
    graph.add_edge("llm_reasoning", "format_response")
    graph.add_edge("format_response", "memory_write")
    graph.add_edge("memory_write", END)

    return graph.compile()

agent_graph = build_graph()