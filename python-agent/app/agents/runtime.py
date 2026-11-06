import uuid

from app.core.time import utc_now
from app.core.privacy import require_cloud_processing

from app.agents.nodes import run_pre_llm_nodes
from app.agents.trace_store import agent_trace_store
from app.memory.session_store import session_store
from app.memory.short_term_memory import short_term_memory
from app.memory.working_memory import working_memory
from app.models.chat import ChatRequest, Message


def prepare_conversation(request: ChatRequest) -> dict:
    require_cloud_processing(request.user_id)
    delivery_id = request.request_id or uuid.uuid4().hex
    user_message = Message(
        role="user",
        content=request.message,
        timestamp=utc_now().isoformat(),
        token_count=max(1, len(request.message) // 4),
    )
    # Commit history before publishing a new manifest. Existing manifests with
    # no SQL history must first recover/migrate their legacy Redis contents.
    history = short_term_memory.add_message(
        request.session_id, user_message, user_id=request.user_id, delivery_id=delivery_id)
    if request.conversation_history is not None:
        history = [*request.conversation_history, user_message]
    session_store.register_session(
        request.user_id,
        request.session_id,
        title=request.message[:30] + ("..." if len(request.message) > 30 else ""),
        delivery_id=delivery_id,
    )
    working_memory.replace_messages(request.session_id, history, user_id=request.user_id)
    state = {
        "user_id": request.user_id,
        "session_id": request.session_id,
        "message": request.message,
        "knowledge_base_ids": request.knowledge_base_ids,
        "document_ids": request.document_ids,
        "conversation_history": request.conversation_history,
        # Freeze the input before model generation. A delayed completion must
        # never distill a later turn or use its execution time as the idle gap.
        "memory_input": {
            "history": [message.model_dump() for message in history],
            "reference_time": user_message.timestamp,
            "delivery_id": delivery_id,
        },
    }
    with agent_trace_store.span(
        request.user_id,
        request.session_id,
        "conversation.prepare",
        {"message_chars": len(request.message), "kb_count": len(request.knowledge_base_ids)},
    ):
        return run_pre_llm_nodes(state)
