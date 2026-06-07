from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Optional
from .nodes import intent_classification_node, knowledge_retrieval_node, llm_reasoning_node

class AgentState(TypedDict):
    user_id: str
    session_id: str
    message: str
    knowledge_base_ids: List[str]
    intent: str
    confidence: float
    context: str
    retrieved_chunks: List[dict]
    answer: str

def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("intent_classification", intent_classification_node)
    graph.add_node("knowledge_retrieval", knowledge_retrieval_node)
    graph.add_node("llm_reasoning", llm_reasoning_node)

    graph.set_entry_point("intent_classification")
    graph.add_edge("intent_classification", "knowledge_retrieval")
    graph.add_edge("knowledge_retrieval", "llm_reasoning")
    graph.add_edge("llm_reasoning", END)

    return graph.compile()

agent_graph = build_graph()