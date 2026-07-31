"""
长期记忆 Chroma 持久化存储层

设计：
- 单一 Chroma collection: mneme_long_term_memory
- 通过 metadata 字段 (user_id, category, topic) 实现多租户隔离和多类型过滤
- 语义检索：用 embedding 相似度匹配语义相近的记忆
- 支持 CRUD + 语义去重 + 重要性更新
"""
import os
import uuid
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings
from app.utils.embedding import embeddings
from app.core.logging import setup_logger

logger = setup_logger("memory_store")

# 合法记忆类别
VALID_CATEGORIES = {"preference", "weak_point", "progress"}


def _build_client():
    """根据环境变量构建 Chroma 客户端（优先远程，本地降级 PersistentClient）"""
    if settings.chroma_mode == "http":
        return chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
    Path(settings.chroma_path).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=settings.chroma_path,
        settings=ChromaSettings(anonymized_telemetry=False)
    )


class MemoryVectorStore:
    """长期记忆的 Chroma 向量存储层"""

    COLLECTION_NAME = "mneme_long_term_memory"

    def __init__(self):
        self._client = _build_client()
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"description": "用户长期记忆：偏好、薄弱点、学习进度"},
            embedding_function=embeddings
        )
        logger.info(f"MemoryVectorStore 初始化完成，collection='{self.COLLECTION_NAME}'")

    # ── 写操作 ──────────────────────────────────────────────

    def add_memory(
        self,
        user_id: str,
        category: str,
        content: str,
        topic: str = "",
        importance: float = 0.5
    ) -> str:
        """添加一条长期记忆，返回记忆 ID。

        Args:
            user_id: 用户 ID
            category: 记忆类别 (preference / weak_point / progress)
            content: 记忆内容（自然语言描述）
            topic: 薄弱点主题（仅 weak_point 类别有意义）
            importance: 重要性分数 0.0-1.0
        """
        if category not in VALID_CATEGORIES:
            raise ValueError(f"非法记忆类别: {category}，合法值: {VALID_CATEGORIES}")

        mem_id = f"mem_{user_id}_{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()

        self._collection.add(
            documents=[content],
            metadatas=[{
                "user_id": user_id,
                "category": category,
                "topic": topic or "",
                "importance": importance,
                "created_at": now,
                "updated_at": now,
            }],
            ids=[mem_id]
        )
        logger.debug(f"记忆已写入: id={mem_id}, category={category}, content={content[:50]}...")
        return mem_id

    def update_importance(self, mem_id: str, new_importance: float):
        """更新记忆的重要性分数"""
        current = self._collection.get(ids=[mem_id], include=["metadatas"])
        if not current.get("ids"):
            return
        metadata = dict((current.get("metadatas") or [{}])[0] or {})
        metadata["importance"] = max(0.0, min(float(new_importance), 1.0))
        metadata["updated_at"] = datetime.now().isoformat()
        self._collection.update(ids=[mem_id], metadatas=[metadata])

    def update_memory_topic(self, mem_id: str, new_topic: str):
        """更新记忆的 topic 字段"""
        current = self._collection.get(ids=[mem_id], include=["metadatas"])
        if not current.get("ids"):
            return
        metadata = dict((current.get("metadatas") or [{}])[0] or {})
        metadata["topic"] = new_topic
        metadata["updated_at"] = datetime.now().isoformat()
        self._collection.update(ids=[mem_id], metadatas=[metadata])

    def update_memory(self, mem_id: str, content: str | None = None, topic: str | None = None):
        """Update editable memory fields while preserving ownership metadata."""
        current = self._collection.get(ids=[mem_id], include=["documents", "metadatas"])
        if not current.get("ids"):
            return False
        metadata = dict((current.get("metadatas") or [{}])[0] or {})
        if topic is not None:
            metadata["topic"] = topic
        metadata["updated_at"] = datetime.now().isoformat()
        document = content if content is not None else (current.get("documents") or [""])[0]
        self._collection.update(ids=[mem_id], documents=[document], metadatas=[metadata])
        return True

    def set_frozen(self, mem_id: str, frozen: bool):
        current = self._collection.get(ids=[mem_id], include=["metadatas"])
        if not current.get("ids"):
            return False
        metadata = dict((current.get("metadatas") or [{}])[0] or {})
        metadata["frozen"] = bool(frozen)
        metadata["updated_at"] = datetime.now().isoformat()
        self._collection.update(ids=[mem_id], metadatas=[metadata])
        return True

    def get_memory(self, mem_id: str):
        result = self._collection.get(ids=[mem_id], include=["documents", "metadatas"])
        if not result.get("ids"):
            return None
        metadata = (result.get("metadatas") or [{}])[0] or {}
        return {"id": mem_id, "content": (result.get("documents") or [""])[0], **metadata}

    def list_all(self, user_id: str):
        result = self._collection.get(where={"user_id": user_id}, include=["documents", "metadatas"])
        entries = []
        for index, mem_id in enumerate(result.get("ids", [])):
            metadata = (result.get("metadatas") or [{}])[index] or {}
            entries.append({"id": mem_id, "content": (result.get("documents") or [""])[index], **metadata})
        entries.sort(key=lambda item: item.get("updated_at") or item.get("created_at", ""), reverse=True)
        return entries

    def delete_memory(self, mem_id: str):
        """删除单条记忆"""
        self._collection.delete(ids=[mem_id])
        logger.debug(f"记忆已删除: {mem_id}")

    def delete_user_memories(self, user_id: str):
        """删除某用户所有长期记忆"""
        self._collection.delete(where={"user_id": user_id})
        logger.info(f"用户 {user_id} 所有记忆已删除")

    # ── 读操作 ──────────────────────────────────────────────

    def search(
        self,
        user_id: str,
        query: str = "",
        category: Optional[str] = None,
        top_k: int = 10
    ) -> List[Dict]:
        """语义检索记忆，可按 category 过滤。

        Args:
            user_id: 用户 ID
            query: 搜索查询文本（语义匹配），空字符串返回全部
            category: 记忆类别过滤，None 表示不过滤
            top_k: 返回条数
        """
        # Chroma 多条件过滤需 $and 语法，兼容各版本
        if category:
            where_filter = {"$and": [{"user_id": user_id}, {"category": category}]}
        else:
            where_filter = {"user_id": user_id}

        try:
            results = self._collection.query(
                query_texts=[query or " "],
                n_results=top_k,
                where=where_filter
            )
        except Exception as e:
            logger.error(f"记忆检索失败: user_id={user_id}, query={query[:50]}, error={e}")
            return []

        entries = []
        ids_list = results.get("ids", [[]])[0]
        docs_list = results.get("documents", [[]])[0]
        metas_list = results.get("metadatas", [[]])[0]
        dists_list = results.get("distances", [[]])[0] if "distances" in results else [0.0] * len(ids_list)

        for i in range(len(ids_list)):
            meta = metas_list[i] if metas_list[i] else {}
            entries.append({
                "id": ids_list[i],
                "content": docs_list[i],
                "category": meta.get("category", ""),
                "topic": meta.get("topic", ""),
                "importance": meta.get("importance", 0.5),
                "score": dists_list[i] if i < len(dists_list) else 0.0,
                "created_at": meta.get("created_at", ""),
            })
        return entries

    def get_by_category(
        self,
        user_id: str,
        category: str,
        limit: int = 50
    ) -> List[Dict]:
        """获取某用户某类别的所有记忆"""
        where_filter = {"$and": [{"user_id": user_id}, {"category": category}]}
        try:
            results = self._collection.get(
                where=where_filter,
                limit=limit,
                include=["documents", "metadatas"],
            )
        except Exception as error:
            logger.error(
                "记忆分类读取失败: user_id=%s category=%s error=%s",
                user_id, category, error,
            )
            return []
        entries = []
        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])
        for index, mem_id in enumerate(ids):
            metadata = metadatas[index] or {}
            if metadata.get("frozen", False):
                continue
            entries.append({
                "id": mem_id,
                "content": documents[index],
                "category": metadata.get("category", ""),
                "topic": metadata.get("topic", ""),
                "importance": metadata.get("importance", 0.5),
                "score": 0.0,
                "created_at": metadata.get("created_at", ""),
                "updated_at": metadata.get("updated_at", ""),
            })
        entries.sort(key=lambda item: item.get("updated_at") or item.get("created_at"), reverse=True)
        return entries

    def count_user_memories(self, user_id: str) -> int:
        """统计某用户的记忆总数"""
        try:
            result = self._collection.get(where={"user_id": user_id})
            return len(result.get("ids", []))
        except Exception:
            return 0

    def list_users(self) -> List[str]:
        """列出所有拥有记忆的用户 ID（用于批量维护任务）"""
        try:
            result = self._collection.get(include=["metadatas"])
            metadatas = result.get("metadatas", [])
            user_ids = set()
            for meta in metadatas:
                uid = meta.get("user_id", "")
                if uid:
                    user_ids.add(uid)
            return list(user_ids)
        except Exception:
            return []

    # ── 语义去重 ────────────────────────────────────────────

    def find_duplicates(
        self,
        user_id: str,
        category: str,
        content: str,
        threshold: float = 0.15
    ) -> List[Dict]:
        """查找与给定内容语义高度相似的已有记忆。

        Chroma 返回的是距离（越小越相似），threshold 是距离阈值。
        距离 < threshold 视为重复。
        """
        similar = self.search(user_id, query=content, category=category, top_k=5)
        return [e for e in similar if e["score"] < threshold]


# 全局单例
memory_store = MemoryVectorStore()
