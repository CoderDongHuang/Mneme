from datetime import datetime

from app.agents.nodes import memory_write_node, run_pre_llm_nodes
from app.agents.trace_store import agent_trace_store
from app.memory.reflection_scheduler import reflection_scheduler
from app.memory.session_store import session_store
from app.memory.short_term_memory import short_term_memory
from app.memory.working_memory import working_memory
from app.models.chat import ChatRequest, Message


def prepare_conversation(request: ChatRequest) -> dict:
    user_message = Message(
        role="user",
        content=request.message,
        timestamp=datetime.now().isoformat(),
        token_count=max(1, len(request.message) // 4),
    )
    working_memory.add_message(request.session_id, user_message)
    short_term_memory.add_message(request.session_id, user_message)
    session_store.register_session(
        request.user_id,
        request.session_id,
        title=request.message[:30] + ("..." if len(request.message) > 30 else ""),
    )
    state = {
        "user_id": request.user_id,
        "session_id": request.session_id,
        "message": request.message,
        "knowledge_base_ids": request.knowledge_base_ids,
    }
    with agent_trace_store.span(
        request.user_id,
        request.session_id,
        "conversation.prepare",
        {"message_chars": len(request.message), "kb_count": len(request.knowledge_base_ids)},
    ):
        return run_pre_llm_nodes(state)


def complete_conversation(request: ChatRequest, state: dict, answer: str) -> dict:
    answer = answer.strip()
    state["answer"] = answer
    with agent_trace_store.span(
        request.user_id,
        request.session_id,
        "memory_write",
        {"answer_chars": len(answer)},
    ):
        memory_result = memory_write_node(state)
    assistant_message = Message(
        role="assistant",
        content=answer,
        timestamp=datetime.now().isoformat(),
        token_count=max(1, len(answer) // 4),
    )
    working_memory.add_message(request.session_id, assistant_message)
    short_term_memory.add_message(request.session_id, assistant_message)
    session_store.increment_message_count(request.user_id, request.session_id)

    reflection_scheduler.record_session(request.user_id)
    reflection_scheduler.check_and_trigger(request.user_id)

    session_summary = None
    if short_term_memory.should_summarize(request.session_id):
        with agent_trace_store.span(request.user_id, request.session_id, "summarize"):
            short_term_memory.summarize(request.session_id)
        for message in short_term_memory.get_history(request.session_id):
            if message.role == "system" and message.content.startswith("[历史摘要]"):
                session_summary = message.content
                break
    agent_trace_store.record(
        request.user_id,
        request.session_id,
        "conversation.complete",
        "ok",
        {
            "pending_memories": len(memory_result.get("pending_memories", [])),
            "summary_created": bool(session_summary),
        },
    )
    return {**memory_result, "session_summary": session_summary}
