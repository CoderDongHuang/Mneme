"""持久化词法索引，使用 SQLite FTS5 避免查询时扫描 Chroma。"""

import re
import sqlite3
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import setup_logger


logger = setup_logger("lexical_index")


def _terms(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    terms = re.findall(r"[a-z0-9_+-]{2,}", normalized)
    for run in re.findall(r"[\u4e00-\u9fff]+", normalized):
        terms.extend(run[index : index + 2] for index in range(len(run) - 1))
        if len(run) == 1:
            terms.append(run)
    return list(dict.fromkeys(terms))


def _search_query(query: str) -> str:
    terms = _terms(query)
    return " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


class LexicalIndex:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._available = True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS lexical_chunks USING fts5(
                        chunk_id UNINDEXED,
                        user_id UNINDEXED,
                        kb_id UNINDEXED,
                        document_id UNINDEXED,
                        page UNINDEXED,
                        chunk_type UNINDEXED,
                        parser UNINDEXED,
                        search_text,
                        content UNINDEXED,
                        source UNINDEXED,
                        section UNINDEXED
                    )
                    """
                )
        except sqlite3.Error as error:
            self._available = False
            logger.warning("SQLite FTS5 不可用，词法检索将降级到 Chroma 扫描: %s", error)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @property
    def available(self) -> bool:
        return self._available

    def replace_document(
        self,
        user_id: str,
        kb_id: str,
        document_id: str,
        chunks: list[dict[str, Any]],
    ) -> None:
        if not self._available:
            return
        try:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM lexical_chunks WHERE user_id=? AND kb_id=? AND document_id=?",
                    (str(user_id), str(kb_id), str(document_id)),
                )
                connection.executemany(
                    """
                    INSERT INTO lexical_chunks(
                        chunk_id,user_id,kb_id,document_id,page,chunk_type,parser,
                        search_text,content,source,section
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    [
                        (
                            str(chunk["id"]),
                            str(user_id),
                            str(kb_id),
                            str(document_id),
                            int(chunk.get("metadata", {}).get("page", 0) or 0),
                            str(chunk.get("metadata", {}).get("chunk_type", "text")),
                            str(chunk.get("metadata", {}).get("parser", "")),
                            " ".join(_terms(str(chunk.get("content", "")))),
                            str(chunk.get("content", "")),
                            str(chunk.get("metadata", {}).get("source", "")),
                            str(chunk.get("metadata", {}).get("section", "")),
                        )
                        for chunk in chunks
                    ],
                )
        except sqlite3.Error as error:
            logger.warning("写入 SQLite 词法索引失败，继续使用 Chroma: %s", error)

    def delete_document(self, user_id: str, kb_id: str, document_id: str) -> int:
        if not self._available:
            return 0
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM lexical_chunks WHERE user_id=? AND kb_id=? AND document_id=?",
                    (str(user_id), str(kb_id), str(document_id)),
                )
                return max(0, cursor.rowcount)
        except sqlite3.Error as error:
            logger.warning("删除 SQLite 词法索引失败: %s", error)
            return 0

    def delete_collection(self, user_id: str, kb_id: str) -> int:
        if not self._available:
            return 0
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM lexical_chunks WHERE user_id=? AND kb_id=?",
                    (str(user_id), str(kb_id)),
                )
                return max(0, cursor.rowcount)
        except sqlite3.Error as error:
            logger.warning("删除 SQLite 词法索引集合失败: %s", error)
            return 0

    def delete_user(self, user_id: str) -> int:
        if not self._available:
            return 0
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM lexical_chunks WHERE user_id=?", (str(user_id),)
                )
                return max(0, cursor.rowcount)
        except sqlite3.Error as error:
            logger.warning("删除 SQLite 用户词法索引失败: %s", error)
            return 0

    def search(
        self, user_id: str, kb_id: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        if not self._available:
            return []
        match_query = _search_query(query)
        if not match_query:
            return []
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT chunk_id,document_id,page,chunk_type,parser,content,
                           source,section,bm25(lexical_chunks) AS rank
                    FROM lexical_chunks
                    WHERE lexical_chunks MATCH ? AND user_id=? AND kb_id=?
                    ORDER BY rank ASC
                    LIMIT ?
                    """,
                    (match_query, str(user_id), str(kb_id), max(1, int(limit))),
                ).fetchall()
        except sqlite3.Error as error:
            logger.warning("SQLite 词法检索失败，继续使用 Chroma: %s", error)
            return []
        return [
            {
                "id": row["chunk_id"],
                "content": row["content"],
                "metadata": {
                    "document_id": row["document_id"],
                    "source": row["source"],
                    "page": row["page"],
                    "section": row["section"],
                    "chunk_type": row["chunk_type"],
                    "parser": row["parser"],
                },
                "lexical_score": 1.0 / (1.0 + abs(float(row["rank"]))),
            }
            for row in rows
        ]


lexical_index = LexicalIndex(settings.lexical_index_path)
