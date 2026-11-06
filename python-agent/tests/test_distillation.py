"""
记忆蒸馏测试

覆盖：
- 空对话返回空列表
- 低置信度记忆被过滤（confidence < 0.6）
- LLM 返回非法 JSON 或错误字段时明确失败，恢复后可重试
- is_new=False 的条目被跳过
- 蒸馏写入的去重统计
- 已有记忆作为上下文传给 LLM
"""

import json
import traceback
from unittest.mock import patch, MagicMock, call

import pytest

import app.memory.distillation as distillation_module
from app.memory.distillation import DistillationResultError, distill_conversation, apply_distilled_entries


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
        mock = _mock_llm(
            json.dumps(
                [
                    {
                        "category": "preference",
                        "content": "喜欢图表讲解",
                        "confidence": 0.9,
                        "is_new": True,
                    }
                ]
            )
        )
        with (
            patch.object(distillation_module, "llm", mock),
            patch(
                "app.memory.distillation.long_term_memory.get_all_memories",
                return_value={},
            ),
        ):
            result = distill_conversation("test_user", "sess_1", sample_conversation)
        assert len(result) == 1
        assert result[0]["category"] == "preference"
        assert result[0]["confidence"] == 0.9

    def test_weak_point_extracted(self, weak_point_conversation):
        """薄弱点对话能提取薄弱点"""
        mock = _mock_llm(
            json.dumps(
                [
                    {
                        "category": "weak_point",
                        "content": "梯度下降理解不透彻",
                        "topic": "梯度下降",
                        "confidence": 0.85,
                        "is_new": True,
                    }
                ]
            )
        )
        with (
            patch.object(distillation_module, "llm", mock),
            patch(
                "app.memory.distillation.long_term_memory.get_all_memories",
                return_value={},
            ),
        ):
            result = distill_conversation(
                "test_user", "sess_1", weak_point_conversation
            )
        assert len(result) == 1
        assert result[0]["category"] == "weak_point"
        assert result[0]["topic"] == "梯度下降"

    # ── 置信度过滤 ───────────────────────────────────────

    def test_low_confidence_filtered_out(self, sample_conversation):
        """confidence < 0.6 的记忆不入库"""
        mock = _mock_llm(
            json.dumps(
                [
                    {
                        "category": "preference",
                        "content": "不确定的偏好",
                        "confidence": 0.3,
                        "is_new": True,
                    },
                    {
                        "category": "preference",
                        "content": "确定的偏好",
                        "confidence": 0.85,
                        "is_new": True,
                    },
                ]
            )
        )
        with (
            patch.object(distillation_module, "llm", mock),
            patch(
                "app.memory.distillation.long_term_memory.get_all_memories",
                return_value={},
            ),
        ):
            result = distill_conversation("test_user", "sess_1", sample_conversation)
        assert len(result) == 1
        assert result[0]["content"] == "确定的偏好"

    def test_all_low_confidence_returns_empty(self):
        """全部低置信度时返回空列表"""
        mock = _mock_llm(
            json.dumps(
                [
                    {
                        "category": "preference",
                        "content": "弱信号1",
                        "confidence": 0.2,
                        "is_new": True,
                    },
                    {
                        "category": "weak_point",
                        "content": "弱信号2",
                        "topic": "弱信号",
                        "confidence": 0.5,
                        "is_new": True,
                    },
                ]
            )
        )
        with (
            patch.object(distillation_module, "llm", mock),
            patch(
                "app.memory.distillation.long_term_memory.get_all_memories",
                return_value={},
            ),
        ):
            result = distill_conversation(
                "test_user", "sess_1", [{"role": "user", "content": "test"}]
            )
        assert result == []

    # ── is_new 过滤 ──────────────────────────────────────

    def test_not_new_entries_filtered(self, sample_conversation):
        """LLM 标记 is_new=False 的条目被过滤"""
        mock = _mock_llm(
            json.dumps(
                [
                    {
                        "category": "preference",
                        "content": "旧偏好",
                        "confidence": 0.9,
                        "is_new": False,
                    },
                    {
                        "category": "weak_point",
                        "content": "新薄弱点",
                        "topic": "test",
                        "confidence": 0.85,
                        "is_new": True,
                    },
                ]
            )
        )
        with (
            patch.object(distillation_module, "llm", mock),
            patch(
                "app.memory.distillation.long_term_memory.get_all_memories",
                return_value={},
            ),
        ):
            result = distill_conversation("test_user", "sess_1", sample_conversation)
        assert len(result) == 1
        assert result[0]["category"] == "weak_point"

    # ── JSON 解析失败 ────────────────────────────────────

    def test_invalid_json_raises(self):
        """不能把非法 JSON 冒充没有新记忆。"""
        mock = _mock_llm("not a valid json [broken")
        with (
            patch.object(distillation_module, "llm", mock),
            patch(
                "app.memory.distillation.long_term_memory.get_all_memories",
                return_value={},
            ),
        ):
            with pytest.raises(DistillationResultError):
                distill_conversation("test_user", "sess_1", [{"role": "user", "content": "test"}])

    def test_empty_json_array_returns_empty(self):
        """LLM 认为无可提取信息，返回空数组"""
        mock = _mock_llm("[]")
        with (
            patch.object(distillation_module, "llm", mock),
            patch(
                "app.memory.distillation.long_term_memory.get_all_memories",
                return_value={},
            ),
        ):
            result = distill_conversation(
                "test_user", "sess_1", [{"role": "user", "content": "你好"}]
            )
        assert result == []

    # ── 已有记忆传给 LLM ──────────────────────────────────

    def test_existing_memories_passed_to_prompt(self):
        """验证已有记忆被传入 prompt 作为去重参考"""
        mock = _mock_llm("[]")
        existing_memories = {
            "preferences": [{"content": "喜欢图表"}],
            "weak_points": [{"topic": "梯度下降", "content": "梯度下降不熟"}],
            "progress": {"topic": "第三章", "content": "学习进度: 第三章/第二节"},
        }
        with (
            patch.object(distillation_module, "llm", mock),
            patch(
                "app.memory.distillation.long_term_memory.get_all_memories",
                return_value=existing_memories,
            ),
        ):
            distill_conversation(
                "test_user", "sess_1", [{"role": "user", "content": "test"}]
            )
        # 验证 prompt 中包含了已有记忆
        call_args = mock.invoke.call_args[0]  # positional args to invoke()
        prompt_text = str(call_args)
        assert "喜欢图表" in prompt_text
        assert "梯度下降" in prompt_text


_VALID_ENTRY = {"category": "preference", "content": "Valid preference", "confidence": 0.7, "is_new": True}


@pytest.mark.parametrize("content", [
    None, [], {}, 1, "not-json-PRIVATE_RESULT", "```json\n[]\n```", "{}", "null", "true", "[null]", "[1]",
    *[json.dumps([entry]) for entry in (
        {}, {**_VALID_ENTRY, "category": "unsupported"}, {**_VALID_ENTRY, "category": []},
        {**_VALID_ENTRY, "content": "  "}, {**_VALID_ENTRY, "content": 5},
        {**_VALID_ENTRY, "confidence": "0.9"}, {**_VALID_ENTRY, "confidence": True},
        {**_VALID_ENTRY, "confidence": -0.1}, {**_VALID_ENTRY, "confidence": 1.1},
        {**_VALID_ENTRY, "confidence": float("nan")}, {**_VALID_ENTRY, "confidence": float("inf")},
        {**_VALID_ENTRY, "confidence": 10 ** 400},
        {**_VALID_ENTRY, "is_new": "false"}, {**_VALID_ENTRY, "is_new": 1},
        {**_VALID_ENTRY, "topic": None}, {**_VALID_ENTRY, "topic": []},
        {**_VALID_ENTRY, "category": "weak_point"},
        {**_VALID_ENTRY, "category": "weak_point", "topic": " "},
        {**_VALID_ENTRY, "source_session_id": "forged"},
        {key: value for key, value in _VALID_ENTRY.items() if key != "is_new"},
        {key: value for key, value in _VALID_ENTRY.items() if key != "confidence"},
    )],
    '[{"category":"preference","content":"PRIVATE_RESULT","confidence":0.9,"confidence":0.1,"is_new":true}]',
    json.dumps([_VALID_ENTRY, {**_VALID_ENTRY, "is_new": "false"}]),
    "[" * 1500 + "]" * 1500,
])
def test_invalid_results_fail_whole_batch_without_private_exception(content, monkeypatch):
    conversation = [{"role": "user", "content": "PRIVATE_RESULT"}]
    backend = MagicMock(get_all_memories=MagicMock(return_value={}))
    monkeypatch.setattr(distillation_module, "long_term_memory", backend)
    monkeypatch.setattr(distillation_module, "llm", _mock_llm(content))
    with pytest.raises(DistillationResultError) as failure:
        distill_conversation("test_user", "sess_1", conversation)
    assert str(failure.value) == "Memory distillation result is invalid"
    assert "PRIVATE_RESULT" not in "".join(traceback.format_exception(failure.value))
    assert failure.value.__cause__ is None and failure.value.__context__ is None
    assert backend.mock_calls == [call.get_all_memories("test_user")]


def test_failed_batch_can_retry_same_snapshot_without_partial_writes(monkeypatch):
    from app.memory.completion import _extract
    from app.models.chat import MemoryCompletion

    backend = MagicMock(get_all_memories=MagicMock(return_value={}))
    provider = _mock_llm("")
    provider.invoke.side_effect = [
        MagicMock(content=json.dumps([_VALID_ENTRY, {**_VALID_ENTRY, "confidence": False}])),
        MagicMock(content=json.dumps([_VALID_ENTRY])),
        MagicMock(content=json.dumps([_VALID_ENTRY])),
    ]
    monkeypatch.setattr(distillation_module, "long_term_memory", backend)
    monkeypatch.setattr(distillation_module, "llm", provider)
    state = {"user_id": "test_user", "session_id": "sess_1", "memory_input": {
        "delivery_id": "stable-request", "reference_time": "2026-11-04T01:00:00Z", "history": [
            {"role": "user", "content": "Historical preference", "timestamp": "2026-11-04T00:00:00Z"},
            {"role": "user", "content": "Current question", "timestamp": "2026-11-04T01:00:00Z"},
        ],
    }}
    snapshot = json.dumps(state, sort_keys=True)
    request = MemoryCompletion(user_id=state["user_id"], session_id=state["session_id"], **state["memory_input"], answer="saved")
    def extract():
        entries = _extract(request)
        return {"memory_entries_to_write": entries, "pending_memories": apply_distilled_entries(request.user_id, entries,
            candidate_scope=[request.user_id, request.session_id, request.delivery_id])}
    with pytest.raises(DistillationResultError):
        extract()
    recovered = extract()
    assert recovered == extract()
    assert len(recovered["pending_memories"]) == 1
    assert recovered["pending_memories"][0]["content"] == _VALID_ENTRY["content"]
    assert recovered["memory_entries_to_write"][0]["source_session_id"] == "sess_1"
    assert len(recovered["memory_entries_to_write"][0]["evidence_hashes"]) == 1
    assert json.dumps(state, sort_keys=True) == snapshot
    backend.add_preference.assert_not_called()
    backend.add_weak_point.assert_not_called()
    backend.update_progress.assert_not_called()


@pytest.mark.parametrize("confidence,accepted", [(0, False), (0.59, False), (0.6, True), (1, True)])
def test_valid_numeric_boundaries(confidence, accepted, monkeypatch):
    monkeypatch.setattr(distillation_module, "long_term_memory", MagicMock(get_all_memories=MagicMock(return_value={})))
    monkeypatch.setattr(distillation_module, "llm", _mock_llm(json.dumps([{**_VALID_ENTRY, "confidence": confidence}])))
    assert bool(distill_conversation("test_user", "sess_1", [{"role": "user", "content": "test"}])) is accepted


class TestApplyDistilledEntries:
    def test_preference_written_to_long_term_memory(self):
        """偏好条目正确路由到 add_preference"""
        with patch(
            "app.memory.distillation.long_term_memory.add_preference",
            return_value="mem_001",
        ) as mock_add:
            apply_distilled_entries(
                "test_user",
                [{"category": "preference", "content": "喜欢图表", "confidence": 0.9}],
            )
        mock_add.assert_called_once_with("test_user", "喜欢图表")

    def test_weak_point_written_with_topic(self):
        """薄弱点携带 topic 路由到 add_weak_point"""
        with patch(
            "app.memory.distillation.long_term_memory.add_weak_point",
            return_value="mem_002",
        ) as mock_add:
            apply_distilled_entries(
                "test_user",
                [
                    {
                        "category": "weak_point",
                        "content": "梯度不熟",
                        "topic": "梯度下降",
                        "confidence": 0.85,
                    }
                ],
            )
        mock_add.assert_called_once_with("test_user", "梯度不熟", "梯度下降")

    def test_progress_parsed_and_written(self):
        """进度按 / 分割后写入 update_progress"""
        with patch(
            "app.memory.distillation.long_term_memory.update_progress"
        ) as mock_update:
            apply_distilled_entries(
                "test_user",
                [
                    {
                        "category": "progress",
                        "content": "第三章/第二节",
                        "confidence": 0.9,
                    }
                ],
            )
        mock_update.assert_called_once_with("test_user", "第三章", "第二节")

    def test_skipped_on_duplicate(self):
        """语义去重命中时不写入（add_preference 返回 None）"""
        with (
            patch(
                "app.memory.distillation.long_term_memory.add_preference",
                return_value=None,
            ) as mock_add,
            patch("app.memory.distillation.long_term_memory.add_weak_point"),
        ):
            apply_distilled_entries(
                "test_user",
                [{"category": "preference", "content": "重复偏好", "confidence": 0.9}],
            )
        mock_add.assert_called_once()  # 调用但去重跳过
