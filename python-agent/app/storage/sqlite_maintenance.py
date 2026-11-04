"""Offline compaction of the five known SQLite stores; never unlink WAL files."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys


TABLES = {
    'lexical': ('lexical_chunks', 'rowid'),
    'generations': ('knowledge_index_state', 'user_id'),
    'memory_versions': ('memory_version', 'id'),
    'traces': ('agent_trace', 'id'),
    'privacy': ('user_privacy', 'user_id'),
}


def checked_path(value, roots):
    path = Path(value)
    if not path.is_absolute() or any(part == '..' for part in path.parts):
        raise ValueError('invalid_store_path')
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValueError('symlink_store_path')
    for suffix in ('-wal', '-shm', '-journal'):
        if Path(str(path) + suffix).is_symlink():
            raise ValueError('symlink_store_path')
    resolved = path.resolve()
    if not any(resolved.is_relative_to(Path(root).resolve()) for root in roots):
        raise ValueError('store_outside_mounts')
    if not path.is_file():
        raise ValueError('store_missing')
    return resolved


def file_sizes(path):
    return {suffix or 'database': Path(str(path) + suffix).stat().st_size
            if Path(str(path) + suffix).exists() else 0 for suffix in ('', '-wal', '-shm')}


def fingerprint(connection, name):
    table, order = TABLES[name]
    digest = hashlib.sha256()
    rows = 0
    # Fixed identifiers only; values never appear in output or error messages.
    columns = 'rowid, *' if name == 'lexical' else '*'
    cursor = connection.execute(f'SELECT {columns} FROM {table} ORDER BY {order}')
    while batch := cursor.fetchmany(128):
        for row in batch:
            values = [({'blob': cell.hex()} if isinstance(cell, bytes) else cell) for cell in row]
            digest.update(json.dumps(values, ensure_ascii=True, separators=(',', ':')).encode())
            digest.update(b'\n')
            rows += 1
    return rows, digest.digest()


def checkpoint(connection):
    busy, _, _ = connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
    if busy:
        raise RuntimeError('checkpoint_busy')


def maintain_store(name, value, roots):
    if name not in TABLES:
        raise ValueError('unknown_store')
    path = checked_path(value, roots)
    before = file_sizes(path)
    # mode=rw prevents accidental creation of an empty replacement database.
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=1)) as connection:
        connection.execute('PRAGMA busy_timeout=1000')
        connection.execute('PRAGMA locking_mode=EXCLUSIVE')
        connection.execute('BEGIN EXCLUSIVE')
        connection.commit()
        if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise RuntimeError('integrity_check_failed')
        original = fingerprint(connection, name)
        pages = connection.execute('PRAGMA page_count').fetchone()[0]
        page_size = connection.execute('PRAGMA page_size').fetchone()[0]
        if shutil.disk_usage(path.parent).free < pages * page_size * 2 + 1024 * 1024:
            raise RuntimeError('insufficient_space')
        # An old reader must not cause a successful but untruncated WAL receipt.
        checkpoint(connection)
        connection.execute('PRAGMA secure_delete=ON')
        if name == 'lexical':
            # secure_delete alone does not merge FTS5's old index segments.
            connection.execute("INSERT INTO lexical_chunks(lexical_chunks) VALUES('optimize')")
            connection.execute("INSERT INTO lexical_chunks(lexical_chunks) VALUES('integrity-check')")
            connection.commit()
        connection.execute('VACUUM')
        checkpoint(connection)
        if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise RuntimeError('integrity_check_failed')
        if fingerprint(connection, name) != original:
            raise RuntimeError('logical_data_changed')
        if connection.execute('PRAGMA freelist_count').fetchone()[0] != 0:
            raise RuntimeError('free_pages_remain')
    after = file_sizes(path)
    if after['-wal']:
        raise RuntimeError('wal_not_truncated')
    return {'status': 'compacted', 'rows': original[0], 'logical_data_unchanged': True,
            'before_bytes': before, 'after_bytes': after}


def run(stores, roots):
    results = {}
    for name, path in stores.items():
        try:
            results[name] = maintain_store(name, path, roots)
        except Exception as error:
            # sqlite errors and paths can include private content; expose only a code.
            allowed = {'invalid_store_path', 'symlink_store_path', 'store_outside_mounts', 'store_missing',
                       'unknown_store', 'insufficient_space', 'checkpoint_busy', 'integrity_check_failed',
                       'logical_data_changed', 'free_pages_remain', 'wal_not_truncated'}
            code = str(error) if str(error) in allowed else 'storage_failure'
            results[name] = {'status': 'failed', 'code': code}
    return {'scope': 'online_sqlite_files_only', 'stores': results,
            'status': 'completed' if results and all(r['status'] == 'compacted' for r in results.values()) else 'failed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    if not (args.apply and args.offline):
        parser.error('use scripts/maintain_sqlite.py; apply requires stopped writers')
    data = json.load(sys.stdin)
    result = run(data['stores'], data['roots'])
    print(json.dumps(result))
    return 0 if result['status'] == 'completed' else 1


if __name__ == '__main__':
    sys.exit(main())
