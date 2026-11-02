"""
长期记忆 Qdrant 持久化存储层

设计：
- 单一 Qdrant collection: mneme_long_term_memory
- 通过 metadata 字段 (user_id, category, topic) 实现多租户隔离和多类型过滤
- 语义检索：用 embedding 相似度匹配语义相近的记忆
- 支持 CRUD + 语义去重 + 重要性更新
"""

import uuid
import json
from contextlib import contextmanager
from typing import List, Optional, Dict

from app.core.time import utc_now
from app.knowledge.qdrant_store import VectorClient, InvalidCollectionException

from app.core.config import settings
from app.core.errors import MemoryIndexConflict
from app.knowledge.generations import generation_store, StaleGeneration
from app.core.privacy import require_cloud_processing
from app.utils.embedding import embeddings
from app.core.logging import setup_logger, memory_log_fields
from app.memory.version_store import memory_version_store

logger = setup_logger("memory_store")

# 合法记忆类别
VALID_CATEGORIES = {"preference", "weak_point", "progress"}


def _build_client():
    if settings.vector_store_mode == "http":
        return VectorClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, check_legacy=True)
    return VectorClient(path=settings.qdrant_path, check_legacy=True)


class MemoryVectorStore:
    """长期记忆的 Qdrant 向量存储层"""

    COLLECTION_NAME = "mneme_long_term_memory"

    def __init__(self):
        self._client = _build_client()
        try:
            self._collection = self._client.get_collection(
                name=self.COLLECTION_NAME, embedding_function=embeddings,
            )
        except InvalidCollectionException:
            self._collection = self._client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"description": "用户长期记忆：偏好、薄弱点、学习进度", "embedding_profile": embeddings.profile()},
                embedding_function=embeddings,
            )
        logger.info(
            f"MemoryVectorStore 初始化完成，collection='{self.COLLECTION_NAME}'"
        )

    def _require_embedding_profile(self):
        metadata = self._collection.metadata or {}
        if metadata.get("embedding_profile") != embeddings.profile():
            if self._collection.count():
                raise MemoryIndexConflict("长期记忆索引需要迁移，请联系管理员按 Embedding 迁移指南重建索引；仍可查看、导出或删除记忆")
            self._collection.modify(metadata={**metadata, "embedding_profile": embeddings.profile()})

    # ── 写操作 ──────────────────────────────────────────────

    def add_memory(
        self,
        user_id: str,
        category: str,
        content: str,
        topic: str = "",
        importance: float = 0.5,
        source_session_id: str = "",
        evidence_hashes: list[str] | None = None,
    ) -> str:
        """添加一条长期记忆，返回记忆 ID。

        Args:
            user_id: 用户 ID
            category: 记忆类别 (preference / weak_point / progress)
            content: 记忆内容（自然语言描述）
            topic: 薄弱点主题（仅 weak_point 类别有意义）
            importance: 重要性分数 0.0-1.0
        """
        require_cloud_processing(user_id)
        self._require_embedding_profile()
        if category not in VALID_CATEGORIES:
            raise ValueError(f"非法记忆类别: {category}，合法值: {VALID_CATEGORIES}")

        mem_id = f"mem_{user_id}_{uuid.uuid4().hex[:8]}"
        now = utc_now().isoformat()

        # Provider calls must never hold a database lock. Deletion may complete
        # while this call is in flight; re-check the durable fence before publish.
        vectors = embeddings([content])
        with generation_store.locked(user_id) as state:
            self._require_active(state)
            self._require_embedding_profile()
            self._collection.add(
                documents=[content], embeddings=vectors,
                metadatas=[
                    {
                        "user_id": user_id,
                        "category": category,
                        "topic": topic or "",
                        "importance": importance,
                        "created_at": now,
                        "updated_at": now,
                        "source_session_id": source_session_id,
                        "evidence_hashes": json.dumps(evidence_hashes or []),
                    }
                ],
                ids=[mem_id],
            )
        logger.debug(memory_log_fields("write", "stored", user_id=user_id, memory_id=mem_id,
                     category=category, content=content, source_session_id=source_session_id))
        return mem_id

    @staticmethod
    def _require_active(state):
        if state.get("deleted"):
            raise StaleGeneration("账号已删除，拒绝修改长期记忆")

    @contextmanager
    def _editing(self, mem_id):
        # The first read discovers the owner only. All editable fields must be
        # re-read under the shared user lock to avoid stale metadata overwrites.
        initial = self.get_memory(mem_id)
        if not initial:
            yield None
            return
        user_id = str(initial["user_id"])
        with generation_store.locked(user_id) as state:
            self._require_active(state)
            current = self.get_memory(mem_id)
            if current and str(current.get("user_id")) != user_id:
                raise ValueError("记忆所有者发生变化")
            yield current

    def _update_fields(self, mem_id, changes, action):
        with self._editing(mem_id) as current:
            if not current:
                return False
            memory_version_store._snapshot_locked(current, action)
            metadata = {**changes, "updated_at": utc_now().isoformat()}
            self._collection.update(ids=[mem_id], metadatas=[metadata])
            return True

    def update_importance(self, mem_id: str, new_importance: float):
        return self._update_fields(mem_id, {"importance": max(0.0, min(float(new_importance), 1.0))}, "importance")

    def update_memory_topic(self, mem_id: str, new_topic: str):
        return self._update_fields(mem_id, {"topic": new_topic}, "topic")

    def update_memory(self, mem_id: str, content: str | None = None, topic: str | None = None):
        initial = self.get_memory(mem_id)
        if not initial:
            return False
        vectors = None
        if content is not None:
            require_cloud_processing(str(initial["user_id"]))
            self._require_embedding_profile()
            vectors = embeddings([content])
        with self._editing(mem_id) as current:
            if not current:
                return False
            if str(current.get("user_id")) != str(initial["user_id"]):
                raise ValueError("记忆所有者发生变化")
            if content is not None:
                self._require_embedding_profile()
            memory_version_store._snapshot_locked(current, "update")
            metadata = {"updated_at": utc_now().isoformat()}
            if topic is not None:
                metadata["topic"] = topic
            fields = {} if content is None else {"documents": [content], "embeddings": vectors}
            self._collection.update(ids=[mem_id], metadatas=[metadata], **fields)
            return True

    def set_frozen(self, mem_id: str, frozen: bool):
        return self._update_fields(mem_id, {"frozen": bool(frozen)}, "freeze" if frozen else "unfreeze")

    def update_metadata(self, mem_id: str, changes: dict):
        if not changes.keys() <= {"status", "confirmed", "tags"}:
            raise ValueError("不可修改的元数据")
        return self._update_fields(mem_id, changes, "metadata")

    def restore_memory(self, memory_id: str, content: str, metadata: dict, *, snapshot_current=False):
        user_id = str(metadata.get("user_id", ""))
        if not user_id:
            raise ValueError("记忆缺少所有者")
        require_cloud_processing(user_id)
        self._require_embedding_profile()
        vectors = embeddings([content])
        with generation_store.locked(user_id) as state:
            self._require_active(state)
            self._require_embedding_profile()
            current = self.get_memory(memory_id)
            if current and str(current.get("user_id")) != user_id:
                raise ValueError("不能恢复其他用户的记忆")
            if snapshot_current and current:
                memory_version_store._snapshot_locked(current, "restore")
            metadata = {key: value for key, value in metadata.items() if key not in {"id", "content"}}
            metadata["updated_at"] = utc_now().isoformat()
            self._collection.upsert(ids=[memory_id], documents=[content],
                                    metadatas=[metadata], embeddings=vectors)
            return self.get_memory(memory_id)

    def get_memory(self, mem_id: str):
        result = self._collection.get(ids=[mem_id], include=["documents", "metadatas"])
        if not result.get("ids"):
            return None
        metadata = (result.get("metadatas") or [{}])[0] or {}
        return {
            **metadata,
            "id": mem_id,
            "content": (result.get("documents") or [""])[0],
        }

    def list_all(self, user_id: str):
        result = self._collection.get(
            where={"user_id": user_id}, include=["documents", "metadatas"]
        )
        entries = []
        for index, mem_id in enumerate(result.get("ids", [])):
            metadata = (result.get("metadatas") or [{}])[index] or {}
            entries.append(
                {
                    **metadata,
                    "id": mem_id,
                    "content": (result.get("documents") or [""])[index],
                }
            )
        entries.sort(
            key=lambda item: item.get("updated_at") or item.get("created_at", ""),
            reverse=True,
        )
        return entries

    def delete_memory(self, mem_id: str):
        with self._editing(mem_id) as current:
            if not current:
                return
            memory_version_store._snapshot_locked(current, "delete")
            self._collection.delete(ids=[mem_id])
            if self.get_memory(mem_id) is not None:
                raise RuntimeError("记忆删除后仍有残留")
        logger.debug(memory_log_fields("delete", "deleted", memory_id=mem_id))

    def delete_user_memories(self, user_id: str):
        # Ordinary memory clearing must not tombstone a live account. Account
        # deletion has already committed its fence before entering this stage.
        with generation_store.locked(user_id) as state:
            if not state.get("deleted"):
                for memory in self.list_all(user_id):
                    memory_version_store._snapshot_locked(memory, "delete_user")
            self._collection.delete(where={"user_id": user_id})
            if self.count_user_memories(user_id) != 0:
                raise RuntimeError("长期记忆删除后仍有残留")
        logger.info(memory_log_fields("delete_user", "deleted", user_id=user_id))

    # ── 读操作 ──────────────────────────────────────────────

    def search(
        self,
        user_id: str,
        query: str = "",
        category: Optional[str] = None,
        top_k: int = 10,
    ) -> List[Dict]:
        """语义检索记忆，可按 category 过滤。

        Args:
            user_id: 用户 ID
            query: 搜索查询文本（语义匹配），空字符串返回全部
            category: 记忆类别过滤，None 表示不过滤
            top_k: 返回条数
        """
        require_cloud_processing(user_id)
        self._require_embedding_profile()
        # Qdrant 多条件过滤需 $and 语法，兼容各版本
        conditions = [{"user_id": user_id}, {"status": {"$nin": ["archived", "ignored"]}}, {"frozen": {"$ne": True}}]
        if category:
            conditions.append({"category": category})
        where_filter = {"$and": conditions}

        try:
            results = self._collection.query(
                query_texts=[query or " "], n_results=top_k, where=where_filter
            )
        except Exception:
            logger.error(memory_log_fields("search", "failed", user_id=user_id, category=category))
            raise

        entries = []
        ids_list = results.get("ids", [[]])[0]
        docs_list = results.get("documents", [[]])[0]
        metas_list = results.get("metadatas", [[]])[0]
        dists_list = (
            results.get("distances", [[]])[0]
            if "distances" in results
            else [0.0] * len(ids_list)
        )

        for i in range(len(ids_list)):
            meta = metas_list[i] if metas_list[i] else {}
            entries.append(
                {
                    "id": ids_list[i],
                    "content": docs_list[i],
                    "category": meta.get("category", ""),
                    "topic": meta.get("topic", ""),
                    "importance": meta.get("importance", 0.5),
                    "score": dists_list[i] if i < len(dists_list) else 0.0,
                    "created_at": meta.get("created_at", ""),
                }
            )
        return entries

    def get_by_category(
        self, user_id: str, category: str, limit: int = 50
    ) -> List[Dict]:
        """获取某用户某类别的所有记忆"""
        where_filter = {"$and": [{"user_id": user_id}, {"category": category},
            {"status": {"$nin": ["archived", "ignored"]}}, {"frozen": {"$ne": True}}]}
        try:
            results = self._collection.get(
                where=where_filter,
                limit=limit,
                include=["documents", "metadatas"],
            )
        except Exception as error:
            logger.error(
                "error_type=%s %s", type(error).__name__,
                memory_log_fields("read_category", "failed", user_id=user_id, category=category),
            )
            return []
        entries = []
        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])
        for index, mem_id in enumerate(ids):
            metadata = metadatas[index] or {}
            if metadata.get("frozen", False) or metadata.get("status") in {"archived", "ignored"}:
                continue
            entries.append(
                {
                    "id": mem_id,
                    "content": documents[index],
                    "category": metadata.get("category", ""),
                    "topic": metadata.get("topic", ""),
                    "importance": metadata.get("importance", 0.5),
                    "score": 0.0,
                    "created_at": metadata.get("created_at", ""),
                    "source_session_id": metadata.get("source_session_id", ""),
                    "evidence_hashes": json.loads(metadata.get("evidence_hashes", "[]")),
                    "updated_at": metadata.get("updated_at", ""),
                }
            )
        entries.sort(
            key=lambda item: item.get("updated_at") or item.get("created_at"),
            reverse=True,
        )
        return entries

    def count_user_memories(self, user_id: str) -> int:
        """统计某用户的记忆总数"""
        result = self._collection.get(where={"user_id": user_id})
        return len(result["ids"])

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
        self, user_id: str, category: str, content: str, threshold: float = 0.15
    ) -> List[Dict]:
        """查找与给定内容语义高度相似的已有记忆。

        Qdrant 返回的是距离（越小越相似），threshold 是距离阈值。
        距离 < threshold 视为重复。
        """
        similar = self.search(user_id, query=content, category=category, top_k=5)
        return [e for e in similar if e["score"] < threshold]


# 全局单例
memory_store = MemoryVectorStore()
