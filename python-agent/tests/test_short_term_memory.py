"""
短期记忆管理测试

覆盖：
- 消息添加与历史获取
- should_summarize 的判断条件
- 冷却期保护
- 增量压缩保留最近消息
- 空历史/消息不足时安全跳过
"""
from unittest.mock import patch, MagicMock
from app.models.chat import Message
import app.memory.short_term_memory as stm_module
from app.memory.short_term_memory import (
    ShortTermMemoryManager,
    SUMMARY_COOLDOWN_SECONDS,
    KEEP_RECENT_COUNT,
)
from app.core.config import settings
from datetime import datetime, timedelta


def _mock_llm(return_content: str):
    """创建模拟 llm（绕过 Pydantic 属性拦截）"""
    mock = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = return_content
    mock.invoke.return_value = mock_resp
    return mock


def make_msg(role: str, content: str, token_count: int = 100) -> Message:
    return Message(
        role=role, content=content,
        timestamp=datetime.now().isoformat(),
        token_count=token_count
    )


class TestShortTermMemoryBasics:

    def test_add_and_get_messages(self):
        """添加消息后能正确获取"""
        store = ShortTermMemoryManager()
        store.add_message("s1", make_msg("user", "hello"))
        store.add_message("s1", make_msg("assistant", "hi"))
        history = store.get_history("s1")
        assert len(history) == 2
        assert history[0].role == "user"
        assert history[1].role == "assistant"

    def test_clear_removes_session(self):
        """clear 后获取空列表"""
        store = ShortTermMemoryManager()
        store.add_message("s1", make_msg("user", "test"))
        store.clear("s1")
        assert store.get_history("s1") == []

    def test_multiple_sessions_isolated(self):
        """不同会话互不影响"""
        store = ShortTermMemoryManager()
        store.add_message("s1", make_msg("user", "a"))
        store.add_message("s2", make_msg("user", "b"))
        assert len(store.get_history("s1")) == 1
        assert len(store.get_history("s2")) == 1


class TestShouldSummarize:

    def test_below_threshold_no_summarize(self):
        """token 未超阈值时不触发摘要"""
        store = ShortTermMemoryManager()
        # 添加少量消息，token 远低于阈值
        for i in range(5):
            store.add_message("s1", make_msg("user", f"msg{i}", token_count=100))
        assert not store.should_summarize("s1")

    def test_above_threshold_triggers(self):
        """token 超过阈值时触发"""
        store = ShortTermMemoryManager()
        # 添加大量消息超过阈值
        for i in range(50):
            store.add_message("s1", make_msg("user", f"msg{i}", token_count=200))
        assert store.should_summarize("s1")

    def test_few_messages_no_summarize_even_above_threshold(self):
        """消息数 <= KEEP_RECENT_COUNT 时不压缩（不值得）"""
        store = ShortTermMemoryManager()
        for i in range(KEEP_RECENT_COUNT):
            store.add_message("s1", make_msg("user", "x" * 5000, token_count=5000))
        assert not store.should_summarize("s1")

    def test_cooldown_prevents_rapid_summarization(self):
        """冷却期内不触发第二次摘要"""
        store = ShortTermMemoryManager()
        # 添加大量消息
        for i in range(50):
            store.add_message("s1", make_msg("user", f"msg{i}", token_count=200))
        assert store.should_summarize("s1")

        # 手动设置上次摘要时间为"刚刚"
        store._last_summary_time["s1"] = datetime.now()
        # 冷却期内不应再次触发
        assert not store.should_summarize("s1")

    def test_cooldown_expired_triggers_again(self):
        """冷却期过后可再次触发"""
        store = ShortTermMemoryManager()
        for i in range(50):
            store.add_message("s1", make_msg("user", f"msg{i}", token_count=200))

        # 冷却期已过
        store._last_summary_time["s1"] = (
            datetime.now() - timedelta(seconds=SUMMARY_COOLDOWN_SECONDS + 10)
        )
        assert store.should_summarize("s1")


class TestSummarize:

    def test_empty_history_no_error(self):
        """空历史 safely no-op"""
        store = ShortTermMemoryManager()
        store.summarize("s1")  # 不应抛出异常

    def test_incremental_compression_preserves_recent(self):
        """增量压缩：早期消息被压缩，近期消息保留"""
        store = ShortTermMemoryManager()
        # 添加 20 条消息，每条 500 token，总计 10000 > 4000 阈值
        for i in range(20):
            store.add_message("s1", make_msg("user", f"msg{i}", token_count=500))

        original_count = len(store.get_history("s1"))

        # 模拟 LLM 返回摘要
        mock = _mock_llm("这是对话摘要")
        with patch.object(stm_module, "llm", mock):
            store.summarize("s1")

        history = store.get_history("s1")
        # 压缩后：1 条摘要 + 保留的近期消息 < 原始 20 条
        assert len(history) < original_count
        # 至少有一条摘要消息
        system_msgs = [m for m in history if m.role == "system"]
        assert len(system_msgs) == 1
        assert "历史摘要" in system_msgs[0].content
        # 冷却时间已记录
        assert "s1" in store._last_summary_time

    def test_summarize_updates_cooldown_timestamp(self):
        """摘要后记录冷却时间"""
        store = ShortTermMemoryManager()
        for i in range(30):
            store.add_message("s1", make_msg("user", f"msg{i}", token_count=300))

        assert "s1" not in store._last_summary_time

        mock = _mock_llm("摘要")
        with patch.object(stm_module, "llm", mock):
            store.summarize("s1")

        assert "s1" in store._last_summary_time

    def test_llm_failure_no_crash(self):
        """LLM 调用失败时不崩溃，历史保持原样"""
        store = ShortTermMemoryManager()
        for i in range(30):
            store.add_message("s1", make_msg("user", f"msg{i}", token_count=300))

        history_before = store.get_history("s1").copy()

        mock = _mock_llm("应被忽略")
        mock.invoke.side_effect = RuntimeError("LLM 超时")
        with patch.object(stm_module, "llm", mock):
            store.summarize("s1")

        # 历史应保持原样
        history_after = store.get_history("s1")
        assert len(history_after) == len(history_before)
