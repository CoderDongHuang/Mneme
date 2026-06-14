"""
记忆写入节点测试 — 蒸馏触发时间逻辑

覆盖：
- 消息数 < 2 时安全跳过蒸馏
- 上一轮消息刚发不久 → 不触发蒸馏
- 上一轮消息超过空闲阈值 → 触发蒸馏
- 蒸馏时排除当前轮消息
"""
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from app.models.chat import Message
from app.agents.nodes import memory_write_node


def make_message(role: str, content: str, minutes_ago: float = 0) -> Message:
    """创建一条 Message，时间戳为现在减去 minutes_ago 分钟"""
    ts = datetime.now() - timedelta(minutes=minutes_ago)
    return Message(
        role=role, content=content,
        timestamp=ts.isoformat(),
        token_count=len(content) // 4
    )


class TestMemoryWriteNode:

    # ── 边界：消息数不足 ──────────────────────────────────

    def test_less_than_2_messages_skips(self):
        """只有 1 条消息时不触发蒸馏（无法判断空闲）"""
        with patch("app.agents.nodes.short_term_memory.get_history",
                   return_value=[make_message("user", "你好", minutes_ago=0)]):
            with patch("app.agents.nodes.distill_conversation") as mock_distill:
                result = memory_write_node({
                    "user_id": "u1", "session_id": "s1", "message": "你好"
                })
        mock_distill.assert_not_called()
        assert result == {"memory_entries_to_write": []}

    def test_empty_history_skips(self):
        """空历史直接跳过"""
        with patch("app.agents.nodes.short_term_memory.get_history", return_value=[]):
            with patch("app.agents.nodes.distill_conversation") as mock_distill:
                result = memory_write_node({
                    "user_id": "u1", "session_id": "s1", "message": ""
                })
        mock_distill.assert_not_called()

    # ── 核心：空闲触发逻辑 ───────────────────────────────

    def test_recent_previous_message_no_distillation(self):
        """上一轮消息刚发不久（5分钟），不触发蒸馏"""
        # 模拟：当前用户消息刚发 (history[-1])，上一轮助手消息 5 分钟前 (history[-2])
        history = [
            make_message("assistant", "上一轮回复", minutes_ago=5),   # history[-2]
            make_message("user", "新问题", minutes_ago=0),            # history[-1]
        ]
        with patch("app.agents.nodes.short_term_memory.get_history", return_value=history):
            with patch("app.agents.nodes.distill_conversation") as mock_distill:
                result = memory_write_node({
                    "user_id": "u1", "session_id": "s1", "message": "新问题"
                })
        mock_distill.assert_not_called()  # 5min < 15min 默认阈值

    def test_idle_exceeds_threshold_triggers_distillation(self):
        """上一轮消息超过 15 分钟，触发蒸馏"""
        history = [
            make_message("assistant", "上一轮回复", minutes_ago=20),  # 20 分钟前
            make_message("user", "新问题", minutes_ago=0),
        ]
        with patch("app.agents.nodes.short_term_memory.get_history", return_value=history):
            with patch("app.agents.nodes.distill_conversation",
                       return_value=[]) as mock_distill:
                with patch("app.agents.nodes.apply_distilled_entries") as mock_apply:
                    result = memory_write_node({
                        "user_id": "u1", "session_id": "s1", "message": "新问题"
                    })
        mock_distill.assert_called_once()
        mock_apply.assert_called_once()
        # 确认蒸馏的是旧对话（不含当前消息 history[-1]）
        distilled_convo = mock_distill.call_args[0][2]  # 第3个位置参数是 conversation
        assert len(distilled_convo) == 1  # 只有上一轮的消息
        assert distilled_convo[0]["role"] == "assistant"

    def test_exactly_at_threshold_triggers(self):
        """恰好在阈值边界触发蒸馏（> 比较）"""
        from app.core.config import settings
        threshold_minutes = settings.DISTILLATION_IDLE_MINUTES
        history = [
            make_message("assistant", "旧回复", minutes_ago=threshold_minutes + 1),
            make_message("user", "新问题", minutes_ago=0),
        ]
        with patch("app.agents.nodes.short_term_memory.get_history", return_value=history):
            with patch("app.agents.nodes.distill_conversation",
                       return_value=[]) as mock_distill:
                with patch("app.agents.nodes.apply_distilled_entries"):
                    memory_write_node({
                        "user_id": "u1", "session_id": "s1", "message": "新问题"
                    })
        mock_distill.assert_called_once()

    # ── 多轮对话场景 ──────────────────────────────────────

    def test_multi_round_only_distills_old(self):
        """多轮对话中只蒸馏当前轮之前的消息"""
        history = [
            make_message("user", "第1轮问题", minutes_ago=60),
            make_message("assistant", "第1轮回复", minutes_ago=58),
            make_message("user", "第2轮问题", minutes_ago=40),
            make_message("assistant", "第2轮回复", minutes_ago=38),
            make_message("user", "当前问题", minutes_ago=0),
        ]
        with patch("app.agents.nodes.short_term_memory.get_history", return_value=history):
            with patch("app.agents.nodes.distill_conversation",
                       return_value=[]) as mock_distill:
                with patch("app.agents.nodes.apply_distilled_entries"):
                    memory_write_node({
                        "user_id": "u1", "session_id": "s1", "message": "当前问题"
                    })
        mock_distill.assert_called_once()
        # 蒸馏了 4 条旧消息，不含当前的第 5 条
        distilled_convo = mock_distill.call_args[0][2]
        assert len(distilled_convo) == 4
