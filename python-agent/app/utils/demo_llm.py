"""Explicit offline product demo: quote supplied passages, never simulate intelligence."""
import json
import re

from langchain_core.messages import AIMessage, AIMessageChunk


class ExtractiveDemoLLM:
    def _answer(self, messages):
        parts = []
        for message in messages:
            if isinstance(message, tuple):
                parts.append(str(message[1]))
            else:
                parts.append(str(getattr(message, "content", message)))
        prompt = "\n".join(parts)
        if "意图分类器" in prompt:
            return '{"intent":"qa","confidence":1.0,"extracted_entities":[]}'
        if "记忆蒸馏器" in prompt or "提取关键信息" in prompt:
            return "[]"
        if "记忆反思器" in prompt or "implicit_preferences" in prompt:
            return '{"implicit_preferences":[],"priority_weak_points":[],"next_step_suggestion":""}'
        # Parse only the JSON-quoted evidence section, never instructions or history.
        evidence = prompt.split("检索资料：", 1)[-1].split("\n用户问题：", 1)[0] if "检索资料：" in prompt else ""
        matches = re.findall(r'^\[(\d+)\] [^\n]*\n("(?:[^"\\]|\\.)*")$', evidence, re.M)
        excerpts = []
        for number, raw in matches[:3]:
            text = json.loads(raw)[:650]
            # Avoid letting document-controlled citation numbers masquerade as references.
            text = re.sub(r"\[(\d+)\]", r"（\1）", text)
            excerpts.append(f"{text} [{number}]")
        if excerpts:
            return "演示模式 · 以下为资料原文摘录，请自行核对相关性：\n\n" + "\n\n".join(excerpts)
        return "演示模式仅支持资料检索和原文摘录。请上传资料、选择知识库后提问；推理、自动记忆与 AI 测验需要配置真实模型。"

    def invoke(self, messages, **kwargs):
        return AIMessage(content=self._answer(messages))

    async def ainvoke(self, messages, **kwargs):
        return self.invoke(messages, **kwargs)

    async def astream(self, messages, **kwargs):
        yield AIMessageChunk(content=self._answer(messages))
