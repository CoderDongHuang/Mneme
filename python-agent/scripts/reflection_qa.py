"""Remove only reserved synthetic DB rows after standalone reflection probes."""
import re
import sqlite3

from app.core.config import settings
from app.knowledge.generations import generation_store
from app.storage.mysql import connection


def remove_probe_users(*users):
    pattern = r"reflection-(?:(?:delivery|cleanup)-)?qa-[0-9a-f]{32}(?:-other|-retention-[ab]|:nested|\*\?\[old\])?"
    if not users or any(not re.fullmatch(pattern, user) for user in users):
        raise ValueError("Only reserved synthetic reflection probe identities may be removed")
    if settings.auxiliary_store_backend == "mysql":
        with connection() as opened:
            cursor = opened.cursor()
            try:
                for user in users:
                    cursor.execute("DELETE FROM knowledge_index_state WHERE user_id=%s", (user,))
            finally:
                cursor.close()
    else:
        with sqlite3.connect(generation_store.path) as opened:
            opened.executemany("DELETE FROM knowledge_index_state WHERE user_id=?", [(user,) for user in users])
