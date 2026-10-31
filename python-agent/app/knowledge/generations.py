"""Durable document fencing, independent of the fallible derived FTS database.

The per-user row is locked for short storage mutations, never parsing/provider
calls. SQLite is for one host; MySQL shares the same lock across replicas.
"""

import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from app.core.config import settings
from app.storage.mysql import connection as mysql_connection, require_tables


class StaleGeneration(ValueError):
    pass


class GenerationStore:
    def __init__(self, path=None):
        self.path = Path(path or settings.index_generation_path)
        if settings.auxiliary_store_backend == "mysql":
            require_tables("knowledge_index_state")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute("CREATE TABLE IF NOT EXISTS knowledge_index_state "
                                   "(user_id TEXT PRIMARY KEY, state_json TEXT NOT NULL)")

    @contextmanager
    def locked(self, user_id):
        """A DB transaction, not an expiring distributed mutex."""
        if settings.auxiliary_store_backend == "mysql":
            with mysql_connection() as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute("INSERT IGNORE INTO knowledge_index_state(user_id,state_json) VALUES(%s,%s)", (str(user_id), "{}"))
                    cursor.execute("SELECT state_json FROM knowledge_index_state WHERE user_id=%s FOR UPDATE", (str(user_id),))
                    state = json.loads(cursor.fetchone()[0])
                    yield state
                    cursor.execute("UPDATE knowledge_index_state SET state_json=%s WHERE user_id=%s", (json.dumps(state), str(user_id)))
                finally:
                    cursor.close()
            return
        connection = sqlite3.connect(self.path, timeout=60)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT state_json FROM knowledge_index_state WHERE user_id=?", (str(user_id),)).fetchone()
            state = json.loads(row[0]) if row else {}
            yield state
            connection.execute("INSERT INTO knowledge_index_state(user_id,state_json) VALUES(?,?) "
                               "ON CONFLICT(user_id) DO UPDATE SET state_json=excluded.state_json", (str(user_id), json.dumps(state)))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def snapshot(self, user_id):
        # A read failure is intentionally fatal; never fall back to unfiltered data.
        if settings.auxiliary_store_backend == "mysql":
            with mysql_connection() as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute("SELECT state_json FROM knowledge_index_state WHERE user_id=%s", (str(user_id),))
                    row = cursor.fetchone()
                finally:
                    cursor.close()
        else:
            with closing(sqlite3.connect(self.path, timeout=60)) as connection:
                row = connection.execute("SELECT state_json FROM knowledge_index_state WHERE user_id=?", (str(user_id),)).fetchone()
        return json.loads(row[0]) if row else {}

    @staticmethod
    def _document(state, kb_id, document_id):
        kb = state.setdefault("libraries", {}).setdefault(str(kb_id), {})
        doc = kb.setdefault("documents", {}).setdefault(str(document_id), {"latest": 0, "active": 0})
        if state.get("deleted") or kb.get("deleted") or doc.get("deleted"):
            raise StaleGeneration("索引范围已删除，拒绝写入")
        return doc

    def begin(self, user_id, kb_id, document_id, requested=None):
        with self.locked(user_id) as state:
            doc = self._document(state, kb_id, document_id)
            generation = requested if requested is not None else doc["latest"] + 1
            if (isinstance(generation, bool) or not isinstance(generation, int)
                    or not 0 < generation <= 9223372036854775807 or generation <= doc["latest"]):
                raise StaleGeneration("解析代已过时，拒绝重放")
            doc["latest"] = generation
            return generation

    @contextmanager
    def writing(self, user_id, kb_id, document_id, generation, *, repair=False):
        with self.locked(user_id) as state:
            doc = self._document(state, kb_id, document_id)
            if (doc["latest"] != generation or ("suspended_through" in doc and generation <= doc["suspended_through"])
                    or (repair and doc["active"] != generation)):
                raise StaleGeneration("文档已有更新的解析代，拒绝旧 worker 写入")
            yield
            doc["active"] = generation
            doc.pop("suspended", None)

    def suspend(self, user_id, kb_id, document_id):
        """Fence cancelled work without permanently deleting the document ID.

        latest is retained even if no active version exists; the next Gateway
        allocation must be strictly newer. Only successful publication clears
        suspended, so failed physical cleanup remains invisible and retryable.
        """
        with self.locked(user_id) as state:
            doc = self._document(state, kb_id, document_id)
            doc["suspended"] = True
            doc["active"] = 0
            # A request cancelled before begin must also reject its first late
            # allocation. Later explicit retries receive a newer generation.
            doc["latest"] = max(1, doc["latest"])
            doc["suspended_through"] = doc["latest"]

    def tombstone(self, user_id, kb_id=None, document_id=None):
        with self.locked(user_id) as state:
            scope = state
            if kb_id is not None:
                scope = scope.setdefault("libraries", {}).setdefault(str(kb_id), {})
            if document_id is not None:
                scope = scope.setdefault("documents", {}).setdefault(str(document_id), {"latest": 0, "active": 0})
            scope["deleted"] = True

    def where(self, user_id, kb_id):
        state = self.snapshot(user_id)
        kb = state.get("libraries", {}).get(str(kb_id), {})
        if state.get("deleted") or kb.get("deleted"):
            return {"document_id": {"$in": []}}
        docs = kb.get("documents", {})
        # Only pre-upgrade chunks without a generation may use the legacy path.
        # If the manifest is lost, generated data is hidden rather than guessed.
        alternatives = [{"$and": [{"document_id": {"$nin": list(docs)}}, {"index_generation": {"$exists": False}}]}]
        for document_id, doc in docs.items():
            if not doc.get("deleted") and not doc.get("suspended"):
                generation = doc.get("active", 0)
                alternatives.append({"$and": [{"document_id": document_id},
                    {"index_generation": generation if generation else {"$exists": False}}]})
        return {"$or": alternatives}


generation_store = GenerationStore()
