"""
意图识别节点测试

覆盖：
- 正常意图识别 (qa, review, suggest, general)
- JSON 解析失败时的降级行为
- 非法意图值的白名单校验
"""
import json
from unittest.mock import patch, MagicMock

import app.agents.nodes as nodes_module
from app.agents.nodes import intent_classification_node


def _mock_llm(return_content: str):
    """创建模拟 llm（绕过 Pydantic 属性拦截）"""
    mock = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = return_content
    mock.invoke.return_value = mock_resp
    return mock


class TestIntentClassification:

    # ── 正常流程 ──────────────────────────────────────────

    def test_returns_qa_intent(self):
        """qa 意图正确返回"""
        mock = _mock_llm(json.dumps({
            "intent": "qa", "confidence": 0.95, "extracted_entities": ["反向传播"]
        }))
        with patch.object(nodes_module, "llm", mock):
            result = intent_classification_node({"message": "什么是反向传播？"})
        assert result["intent"] == "qa"
        assert result["confidence"] == 0.95

    def test_returns_review_intent(self):
        """review 意图正确返回"""
        mock = _mock_llm(json.dumps({
            "intent": "review", "confidence": 0.88, "extracted_entities": []
        }))
        with patch.object(nodes_module, "llm", mock):
            result = intent_classification_node({"message": "上次讲的公式再讲一遍"})
        assert result["intent"] == "review"

    def test_returns_suggest_intent(self):
        """suggest 意图正确返回"""
        mock = _mock_llm(json.dumps({
            "intent": "suggest", "confidence": 0.90, "extracted_entities": []
        }))
        with patch.object(nodes_module, "llm", mock):
            result = intent_classification_node({"message": "我接下来该学什么？"})
        assert result["intent"] == "suggest"

    def test_returns_general_intent(self):
        """general 意图正确返回"""
        mock = _mock_llm(json.dumps({
            "intent": "general", "confidence": 0.85, "extracted_entities": []
        }))
        with patch.object(nodes_module, "llm", mock):
            result = intent_classification_node({"message": "你好"})
        assert result["intent"] == "general"

    # ── 容错：JSON 解析失败 ────────────────────────────────

    def test_invalid_json_falls_back_to_general(self):
        """LLM 返回非法 JSON 时回退到 general + 置信度 0"""
        mock = _mock_llm("这不是合法的 JSON 格式")
        with patch.object(nodes_module, "llm", mock):
            result = intent_classification_node({"message": "随机文本"})
        assert result["intent"] == "general"
        assert result["confidence"] == 0.0

    def test_empty_string_falls_back_to_general(self):
        """空字符串也安全回退"""
        mock = _mock_llm("")
        with patch.object(nodes_module, "llm", mock):
            result = intent_classification_node({"message": ""})
        assert result["intent"] == "general"

    # ── 容错：非法意图值 ──────────────────────────────────

    def test_unknown_intent_falls_back_to_general(self):
        """LLM 返回不在白名单的意图值时回退到 general"""
        mock = _mock_llm(json.dumps({
            "intent": "ingestion",  # 不在白名单中
            "confidence": 0.80,
            "extracted_entities": []
        }))
        with patch.object(nodes_module, "llm", mock):
            result = intent_classification_node({"message": "上传一份文档"})
        assert result["intent"] == "general"

    def test_malicious_intent_blocked(self):
        """任意非法字符串被拦截"""
        mock = _mock_llm(json.dumps({
            "intent": "delete_all_data",
            "confidence": 0.99,
            "extracted_entities": []
        }))
        with patch.object(nodes_module, "llm", mock):
            result = intent_classification_node({"message": "test"})
        assert result["intent"] == "general"

    # ── 缺失字段 ──────────────────────────────────────────

    def test_missing_intent_field_defaults_to_general(self):
        """JSON 缺少 intent 字段时默认 general"""
        mock = _mock_llm(json.dumps({"confidence": 0.90}))
        with patch.object(nodes_module, "llm", mock):
            result = intent_classification_node({"message": "test"})
        assert result["intent"] == "general"

    def test_missing_confidence_defaults_to_0_5(self):
        """JSON 缺少 confidence 字段时默认 0.5"""
        mock = _mock_llm(json.dumps({
            "intent": "qa",
            "extracted_entities": []
        }))
        with patch.object(nodes_module, "llm", mock):
            result = intent_classification_node({"message": "什么是神经网络？"})
        assert result["intent"] == "qa"
        assert result["confidence"] == 0.5
