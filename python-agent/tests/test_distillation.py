"""
记忆蒸馏测试

覆盖：
- 空对话返回空列表
- 低置信度记忆被过滤（confidence < 0.6）
- LLM 返回非法 JSON 时安全降级
- is_new=False 的条目被跳过
- 蒸馏写入的去重统计
- 已有记忆作为上下文传给 LLM
"""
import json
from unittest.mock import patch, MagicMock

import app.memory.distillation as distillation_module
from app.memory.distillation import distill_conversation, apply_distilled_entries


def _mock_llm(return_content: str):
    """创建一个模拟的模块级 llm 对象，避免 Pydantic 属性拦截"""
    mock = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = return_content
    mock.invoke.return_value = mock_resp
    return mock


class TestDistillConversation:

    def test_empty_conversation_returns_empty(self):
        """空对话直接返回空列表，不调用 LLM"""
        result = distill_conversation("test_user", "sess_1", [])
        assert result == []

    def test_single_message_extracts_preference(self, sample_conversation):
        """正常对话能提取偏好"""
        mock = _mock_llm(json.dumps([
            {"category": "preference", "content": "喜欢图表讲解",
             "confidence": 0.9, "is_new": True}
        ]))
        with patch.object(distillation_module, "llm", mock), \
             patch("app.memory.distillation.long_term_memory.get_all_memories", return_value={}):
            result = distill_conversation("test_user", "sess_1", sample_conversation)
        assert len(result) == 1
        assert result[0]["category"] == "preference"
        assert result[0]["confidence"] == 0.9

    def test_weak_point_extracted(self, weak_point_conversation):
        """薄弱点对话能提取薄弱点"""
        mock = _mock_llm(json.dumps([
            {"category": "weak_point", "content": "梯度下降理解不透彻",
             "topic": "梯度下降", "confidence": 0.85, "is_new": True}
        ]))
        with patch.object(distillation_module, "llm", mock), \
             patch("app.memory.distillation.long_term_memory.get_all_memories", return_value={}):
            result = distill_conversation("test_user", "sess_1", weak_point_conversation)
        assert len(result) == 1
        assert result[0]["category"] == "weak_point"
        assert result[0]["topic"] == "梯度下降"

    # ── 置信度过滤 ───────────────────────────────────────

    def test_low_confidence_filtered_out(self, sample_conversation):
        """confidence < 0.6 的记忆不入库"""
        mock = _mock_llm(json.dumps([
            {"category": "preference", "content": "不确定的偏好",
             "confidence": 0.3, "is_new": True},
            {"category": "preference", "content": "确定的偏好",
             "confidence": 0.85, "is_new": True},
        ]))
        with patch.object(distillation_module, "llm", mock), \
             patch("app.memory.distillation.long_term_memory.get_all_memories", return_value={}):
            result = distill_conversation("test_user", "sess_1", sample_conversation)
        assert len(result) == 1
        assert result[0]["content"] == "确定的偏好"

    def test_all_low_confidence_returns_empty(self):
        """全部低置信度时返回空列表"""
        mock = _mock_llm(json.dumps([
            {"category": "preference", "content": "弱信号1",
             "confidence": 0.2, "is_new": True},
            {"category": "weak_point", "content": "弱信号2",
             "confidence": 0.5, "is_new": True},
        ]))
        with patch.object(distillation_module, "llm", mock), \
             patch("app.memory.distillation.long_term_memory.get_all_memories", return_value={}):
            result = distill_conversation("test_user", "sess_1",
                                          [{"role": "user", "content": "test"}])
        assert result == []

    # ── is_new 过滤 ──────────────────────────────────────

    def test_not_new_entries_filtered(self, sample_conversation):
        """LLM 标记 is_new=False 的条目被过滤"""
        mock = _mock_llm(json.dumps([
            {"category": "preference", "content": "旧偏好",
             "confidence": 0.9, "is_new": False},
            {"category": "weak_point", "content": "新薄弱点", "topic": "test",
             "confidence": 0.85, "is_new": True},
        ]))
        with patch.object(distillation_module, "llm", mock), \
             patch("app.memory.distillation.long_term_memory.get_all_memories", return_value={}):
            result = distill_conversation("test_user", "sess_1", sample_conversation)
        assert len(result) == 1
        assert result[0]["category"] == "weak_point"

    # ── JSON 解析失败 ────────────────────────────────────

    def test_invalid_json_returns_empty(self):
        """LLM 返回非法 JSON 时安全降级"""
        mock = _mock_llm("not a valid json [broken")
        with patch.object(distillation_module, "llm", mock), \
             patch("app.memory.distillation.long_term_memory.get_all_memories", return_value={}):
            result = distill_conversation("test_user", "sess_1",
                                          [{"role": "user", "content": "test"}])
        assert result == []

    def test_empty_json_array_returns_empty(self):
        """LLM 认为无可提取信息，返回空数组"""
        mock = _mock_llm("[]")
        with patch.object(distillation_module, "llm", mock), \
             patch("app.memory.distillation.long_term_memory.get_all_memories", return_value={}):
            result = distill_conversation("test_user", "sess_1",
                                          [{"role": "user", "content": "你好"}])
        assert result == []

    # ── 已有记忆传给 LLM ──────────────────────────────────

    def test_existing_memories_passed_to_prompt(self):
        """验证已有记忆被传入 prompt 作为去重参考"""
        mock = _mock_llm("[]")
        existing_memories = {
            "preferences": [{"content": "喜欢图表"}],
            "weak_points": [{"topic": "梯度下降", "content": "梯度下降不熟"}],
            "progress": {"topic": "第三章", "content": "学习进度: 第三章/第二节"}
        }
        with patch.object(distillation_module, "llm", mock), \
             patch("app.memory.distillation.long_term_memory.get_all_memories",
                   return_value=existing_memories):
            distill_conversation("test_user", "sess_1",
                                 [{"role": "user", "content": "test"}])
        # 验证 prompt 中包含了已有记忆
        call_args = mock.invoke.call_args[0]  # positional args to invoke()
        prompt_text = str(call_args)
        assert "喜欢图表" in prompt_text
        assert "梯度下降" in prompt_text


class TestApplyDistilledEntries:

    def test_preference_written_to_long_term_memory(self):
        """偏好条目正确路由到 add_preference"""
        with patch("app.memory.distillation.long_term_memory.add_preference",
                   return_value="mem_001") as mock_add:
            apply_distilled_entries("test_user", [
                {"category": "preference", "content": "喜欢图表", "confidence": 0.9}
            ])
        mock_add.assert_called_once_with("test_user", "喜欢图表")

    def test_weak_point_written_with_topic(self):
        """薄弱点携带 topic 路由到 add_weak_point"""
        with patch("app.memory.distillation.long_term_memory.add_weak_point",
                   return_value="mem_002") as mock_add:
            apply_distilled_entries("test_user", [
                {"category": "weak_point", "content": "梯度不熟",
                 "topic": "梯度下降", "confidence": 0.85}
            ])
        mock_add.assert_called_once_with("test_user", "梯度不熟", "梯度下降")

    def test_progress_parsed_and_written(self):
        """进度按 / 分割后写入 update_progress"""
        with patch("app.memory.distillation.long_term_memory.update_progress") as mock_update:
            apply_distilled_entries("test_user", [
                {"category": "progress", "content": "第三章/第二节", "confidence": 0.9}
            ])
        mock_update.assert_called_once_with("test_user", "第三章", "第二节")

    def test_skipped_on_duplicate(self):
        """语义去重命中时不写入（add_preference 返回 None）"""
        with patch("app.memory.distillation.long_term_memory.add_preference",
                   return_value=None) as mock_add, \
             patch("app.memory.distillation.long_term_memory.add_weak_point"):
            apply_distilled_entries("test_user", [
                {"category": "preference", "content": "重复偏好", "confidence": 0.9}
            ])
        mock_add.assert_called_once()  # 调用但去重跳过
