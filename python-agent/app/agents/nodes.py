import json
from langchain_core.messages import HumanMessage, SystemMessage
from app.utils.llm import llm
from app.agents.prompts import INTENT_CLASSIFICATION_PROMPT, QA_PROMPT
from app.knowledge.retriever import retrieve
from app.core.logging import setup_logger

logger = setup_logger("nodes")

def intent_classification_node(state: dict) -> dict:
    prompt = INTENT_CLASSIFICATION_PROMPT.format(question=state["message"])
    response = llm.invoke([SystemMessage(content="你是一个意图分类器，只输出JSON。"), HumanMessage(content=prompt)])
    try:
        intent_data = json.loads(response.content)
    except:
        intent_data = {"intent": "qa", "confidence": 0.5, "extracted_entities": []}
    logger.info(f"意图识别结果: {intent_data}")
    valid_intents = {"qa", "review", "suggest"}
    intent = intent_data.get("intent", "qa")
    if intent not in valid_intents:
        intent = "qa"
    return {"intent": intent, "confidence": intent_data.get("confidence", 0.5)}

def knowledge_retrieval_node(state: dict) -> dict:
    all_chunks = []
    for kb_id in state.get("knowledge_base_ids", []):
        chunks = retrieve(state["user_id"], kb_id, state["message"])
        all_chunks.extend(chunks)
    context = "\n\n".join([f"[来源: {c['metadata'].get('source', 'unknown')}] {c['content']}" for c in all_chunks])
    return {"context": context, "retrieved_chunks": all_chunks}

def llm_reasoning_node(state: dict) -> dict:
    prompt = QA_PROMPT.format(context=state.get("context", "无参考资料"), question=state["message"])
    response = llm.invoke([HumanMessage(content=prompt)])
    return {"answer": response.content}