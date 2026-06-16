import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"  # 禁用 Chroma 遥测，避免 capture() 参数错误

import chromadb
from chromadb.config import Settings as ChromaSettings
from app.core.config import settings
from app.core.logging import setup_logger
from app.utils.embedding import embeddings

logger = setup_logger("vector_store")

def _get_collection_name(user_id: str, kb_id: str) -> str:
    return f"user_{user_id}_kb_{kb_id}"

class VectorStore:
    def __init__(self):
        # Docker 环境：通过 HTTP 连接 Chroma 服务
        # 本地开发环境：使用 PersistentClient 直接访问本地路径
        chroma_host = settings.CHROMA_HOST or ""
        is_remote = chroma_host and "localhost" not in chroma_host and "127.0.0.1" not in chroma_host
        if is_remote:
            self.client = chromadb.HttpClient(
                host=settings.CHROMA_HOST,
                port=settings.CHROMA_PORT,
                settings=ChromaSettings(anonymized_telemetry=False)
            )
        else:
            self.client = chromadb.PersistentClient(
                path="./data/chroma",
                settings=ChromaSettings(anonymized_telemetry=False)
            )

    def get_or_create_collection(self, user_id: str, kb_id: str):
        collection_name = _get_collection_name(user_id, kb_id)
        return self.client.get_or_create_collection(
            name=collection_name,
            metadata={"user_id": user_id, "kb_id": kb_id},
            embedding_function=embeddings
        )

    def delete_collection(self, user_id: str, kb_id: str):
        collection_name = _get_collection_name(user_id, kb_id)
        try:
            self.client.delete_collection(name=collection_name)
            logger.info(f"成功删除 collection: {collection_name}")
        except ValueError:
            logger.debug(f"Collection 已不存在，无需删除: {collection_name}")
        except Exception as e:
            logger.error(f"删除 collection 失败 ({collection_name}): {e}", exc_info=True)

    # ── 管理与运维 ──────────────────────────────────────────

    def list_user_collections(self, user_id: str) -> list:
        """列出某用户的所有知识库 collection"""
        prefix = f"user_{user_id}_kb_"
        try:
            all_collections = self.client.list_collections()
            return [c for c in all_collections if c.name.startswith(prefix)]
        except Exception as e:
            logger.error(f"列出用户 collection 失败: user_id={user_id}, error={e}")
            return []

    def get_collection_stats(self, user_id: str) -> list:
        """获取用户所有知识库的统计信息（collection 名、chunk 数、元数据）"""
        stats = []
        for col in self.list_user_collections(user_id):
            try:
                count = col.count()
                stats.append({
                    "name": col.name,
                    "kb_id": col.name.split("_kb_")[-1],
                    "chunk_count": count,
                    "metadata": col.metadata or {}
                })
            except Exception as e:
                logger.warning(f"获取 collection 统计失败: {col.name}, error={e}")
                stats.append({
                    "name": col.name,
                    "kb_id": col.name.split("_kb_")[-1],
                    "chunk_count": -1,
                    "error": str(e)
                })
        return stats

    def cleanup_orphan_collections(self, valid_kb_pairs: set) -> dict:
        """清理孤儿 collection（知识库已在 MySQL 中删除但 Chroma 还在）。

        Args:
            valid_kb_pairs: 合法的 (user_id, kb_id) 集合

        Returns:
            {"removed": [...], "kept": [...], "errors": [...]}
        """
        removed = []
        kept = []
        errors = []

        try:
            all_collections = self.client.list_collections()
        except Exception as e:
            logger.error(f"无法列出所有 collection: {e}")
            return {"removed": [], "kept": [], "errors": [str(e)]}

        for col in all_collections:
            name = col.name
            # 只处理 user_X_kb_Y 格式的 collection
            if not name.startswith("user_") or "_kb_" not in name:
                continue

            try:
                parts = name.split("_kb_")
                uid = parts[0].replace("user_", "")
                kid = parts[1] if len(parts) > 1 else ""

                if (uid, kid) in valid_kb_pairs:
                    kept.append(name)
                else:
                    self.client.delete_collection(name=name)
                    removed.append(name)
                    logger.info(f"清理孤儿 collection: {name}")
            except Exception as e:
                errors.append({"name": name, "error": str(e)})
                logger.error(f"处理 collection 失败: {name}, {e}")

        return {"removed": removed, "kept": kept, "errors": errors}

    def get_total_stats(self) -> dict:
        """获取全局 Chroma 统计信息"""
        try:
            all_collections = self.client.list_collections()
            total_collections = len(all_collections)
            total_chunks = sum(c.count() for c in all_collections)
            return {
                "total_collections": total_collections,
                "total_chunks": total_chunks,
                "collection_names": [c.name for c in all_collections]
            }
        except Exception as e:
            logger.error(f"获取全局统计失败: {e}")
            return {"error": str(e)}


vector_store = VectorStore()