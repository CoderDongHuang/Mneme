QA_PROMPT = """你是一个学习助手，基于以下参考资料回答用户的问题。

参考资料：
{context}

用户问题：{question}

请基于参考资料回答，如果资料中没有相关信息，请明确告知用户。回答时请标注信息来源。"""

INTENT_CLASSIFICATION_PROMPT = """请判断用户问题的意图类型，输出 JSON 格式。
可选类型：
- qa：基于知识库回答（涉及具体知识、概念、技术问题等）
- review：回顾历史对话或用户偏好
- suggest：请求学习建议或规划
- general：通用闲聊或简单问题，不需要检索任何资料

用户问题：{question}

输出格式：{{"intent": "qa", "confidence": 0.9, "extracted_entities": []}}"""