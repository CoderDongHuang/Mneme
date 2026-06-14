"""
长期记忆管理器测试

覆盖：
- 偏好/薄弱点/进度的写入与读取
- 缓存生效与失效
- 语义去重
- 薄弱点合并（同 topic 累加）
- 容量上限淘汰
- 薄弱点衰减
"""
import pytest
from unittest.mock import patch, MagicMock
from app.memory.long_term_memory import LongTermMemoryManager


@pytest.fixture
def ltm():
    """创建一个干净的 LongTermMemoryManager（每次测试独立）"""
    return LongTermMemoryManager()


class TestPreferences:

    def test_add_and_get(self, ltm):
        """写入偏好后能读取到"""
        with patch.object(ltm._store, "find_duplicates", return_value=[]), \
             patch.object(ltm._store, "add_memory", return_value="mem_pref_001"), \
             patch.object(ltm._store, "get_by_category", return_value=[
                 {"id": "mem_pref_001", "content": "喜欢图表讲解", "category": "preference",
                  "importance": 0.5, "topic": "", "score": 0.0}
             ]), \
             patch.object(ltm._store, "search", return_value=[]):
            mem_id = ltm.add_preference("u1", "喜欢图表讲解")
            assert mem_id == "mem_pref_001"
            prefs = ltm.get_preferences("u1")
            assert len(prefs) == 1
            assert prefs[0]["content"] == "喜欢图表讲解"

    def test_cache_hit(self, ltm):
        """第二次读取走缓存，不调用 store"""
        with patch.object(ltm._store, "find_duplicates", return_value=[]), \
             patch.object(ltm._store, "add_memory", return_value="mem_001"):
            ltm.add_preference("u1", "测试偏好")

        # 第一次：走 store
        with patch.object(ltm._store, "get_by_category", return_value=[
            {"id": "mem_001", "content": "测试偏好", "category": "preference",
             "importance": 0.5, "topic": "", "score": 0.0}
        ]) as mock_get:
            result1 = ltm.get_preferences("u1")
            assert mock_get.call_count == 1
            assert len(result1) == 1

        # 第二次：走缓存，不应再调 store
        with patch.object(ltm._store, "get_by_category") as mock_get2:
            result2 = ltm.get_preferences("u1")
            assert mock_get2.call_count == 0  # 缓存命中
            assert len(result2) == 1
            assert result2[0]["content"] == "测试偏好"

    def test_cache_invalidated_after_write(self, ltm):
        """写入新偏好后缓存失效，下次从 store 重读"""
        with patch.object(ltm._store, "find_duplicates", return_value=[]), \
             patch.object(ltm._store, "add_memory", return_value="mem_001"):
            ltm.add_preference("u1", "初始偏好")

        # 写入缓存
        with patch.object(ltm._store, "get_by_category", return_value=[
            {"id": "mem_001", "content": "初始偏好", "category": "preference",
             "importance": 0.5, "topic": "", "score": 0.0}
        ]):
            ltm.get_preferences("u1")

        # 新写入后缓存失效
        with patch.object(ltm._store, "find_duplicates", return_value=[]), \
             patch.object(ltm._store, "add_memory", return_value="mem_002"), \
             patch.object(ltm._store, "get_by_category", return_value=[
                 {"id": "mem_001", "content": "初始偏好", "category": "preference",
                  "importance": 0.5, "topic": "", "score": 0.0},
                 {"id": "mem_002", "content": "新偏好", "category": "preference",
                  "importance": 0.5, "topic": "", "score": 0.0}
             ]) as mock_get:
            ltm.add_preference("u1", "新偏好")
            result = ltm.get_preferences("u1")
            assert mock_get.call_count == 1  # 缓存已失效，重新读取
            assert len(result) == 2

    def test_duplicate_not_added(self, ltm):
        """语义重复的偏好不入库"""
        with patch.object(ltm._store, "find_duplicates", return_value=[
            {"id": "mem_old", "content": "喜欢图表", "score": 0.05}
        ]):
            result = ltm.add_preference("u1", "喜欢图表讲解")
        assert result is None  # 去重命中，返回 None


class TestWeakPoints:

    def test_add_and_get(self, ltm):
        """写入薄弱点后能读取到"""
        with patch.object(ltm._store, "find_duplicates", return_value=[]), \
             patch.object(ltm._store, "get_by_category", return_value=[]), \
             patch.object(ltm._store, "add_memory", return_value="mem_wp_001"):
            mem_id = ltm.add_weak_point("u1", "梯度下降不熟", "梯度下降")
            assert mem_id == "mem_wp_001"

    def test_same_topic_merges(self, ltm):
        """同 topic 的薄弱点合并（累加 importance），不新增"""
        existing = [{"id": "mem_wp_001", "topic": "梯度下降", "importance": 0.5,
                     "content": "梯度下降不熟", "category": "weak_point"}]
        with patch.object(ltm._store, "get_by_category", return_value=existing), \
             patch.object(ltm._store, "update_importance") as mock_update:
            result = ltm.add_weak_point("u1", "还是不懂梯度下降", "梯度下降")
        assert result == "mem_wp_001"  # 返回已有 ID
        mock_update.assert_called_once_with("mem_wp_001", 0.6)  # 0.5 + 0.1

    def test_different_topic_adds_new(self, ltm):
        """不同 topic 的薄弱点正常新增"""
        existing = [{"id": "mem_001", "topic": "梯度下降", "importance": 0.5,
                     "content": "...", "category": "weak_point"}]
        with patch.object(ltm._store, "get_by_category", return_value=existing), \
             patch.object(ltm._store, "find_duplicates", return_value=[]), \
             patch.object(ltm._store, "add_memory", return_value="mem_002") as mock_add:
            result = ltm.add_weak_point("u1", "反向传播不熟", "反向传播")
        mock_add.assert_called_once()
        assert result == "mem_002"

    def test_decay_removes_expired(self, ltm):
        """30 天前创建的薄弱点 importance 降到 0 后删除"""
        from datetime import datetime, timedelta
        old_date = (datetime.now() - timedelta(days=40)).isoformat()
        existing = [{"id": "mem_old", "topic": "过时的薄弱点", "importance": 0.1,
                     "content": "...", "category": "weak_point", "created_at": old_date}]
        with patch.object(ltm._store, "get_by_category", return_value=existing), \
             patch.object(ltm._store, "delete_memory") as mock_delete, \
             patch.object(ltm._store, "update_importance") as mock_update:
            ltm.decay_weak_points("u1")
        # importance 0.1 - 0.2 = -0.1 → 应删除
        mock_delete.assert_called_once_with("mem_old")
        mock_update.assert_not_called()


class TestProgress:

    def test_update_and_get(self, ltm):
        """更新进度后能读取到"""
        with patch.object(ltm._store, "get_by_category", return_value=[]), \
             patch.object(ltm._store, "delete_memory"), \
             patch.object(ltm._store, "add_memory", return_value="mem_prog_001"):
            ltm.update_progress("u1", "第三章", "第二节")

        with patch.object(ltm._store, "get_by_category", return_value=[
            {"id": "mem_prog_001", "content": "学习进度: 第三章/第二节",
             "category": "progress", "topic": "第三章/第二节",
             "importance": 0.5, "score": 0.0}
        ]):
            progress = ltm.get_progress("u1")
            assert progress is not None
            assert progress["topic"] == "第三章/第二节"

    def test_update_replaces_old_progress(self, ltm):
        """新旧进度替换（旧记录被删除）"""
        with patch.object(ltm._store, "get_by_category", return_value=[
            {"id": "old_progress", "content": "旧进度", "category": "progress"}
        ]), \
             patch.object(ltm._store, "delete_memory") as mock_delete, \
             patch.object(ltm._store, "add_memory", return_value="new_progress"):
            ltm.update_progress("u1", "第五章", "第一节")
        mock_delete.assert_called_once_with("old_progress")


class TestGetAllMemories:

    def test_returns_all_categories(self, ltm):
        """获取所有记忆返回三类数据"""
        with patch.object(ltm, "get_preferences", return_value=["pref1"]), \
             patch.object(ltm, "get_weak_points", return_value=["wp1"]), \
             patch.object(ltm, "get_progress", return_value={"topic": "ch1"}):
            all_mem = ltm.get_all_memories("u1")
        assert "preferences" in all_mem
        assert "weak_points" in all_mem
        assert "progress" in all_mem
