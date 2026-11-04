"""Real SQLite/WAL reclamation, tenant preservation and Docker stop guards."""
from contextlib import closing
import importlib.util
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.storage import sqlite_maintenance as maintenance


def create_privacy(path):
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('CREATE TABLE user_privacy(user_id TEXT PRIMARY KEY, cloud_allowed INTEGER, trace_days INTEGER)')
        connection.execute("INSERT INTO user_privacy VALUES('survivor',0,30)")
        connection.commit()


def test_crashed_writer_wal_is_recovered_compacted_and_surviving_rows_unchanged(tmp_path):
    path = tmp_path / 'privacy.sqlite3'
    subprocess.run([sys.executable, '-c', """
import os,sqlite3,sys
c=sqlite3.connect(sys.argv[1]); c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA wal_autocheckpoint=0')
c.execute('CREATE TABLE user_privacy(user_id TEXT PRIMARY KEY, cloud_allowed INTEGER, trace_days INTEGER)')
c.executemany('INSERT INTO user_privacy VALUES(?,0,30)', [('deleted-private-marker-'+str(i)+'x'*3000,) for i in range(500)])
c.execute("INSERT INTO user_privacy VALUES('survivor',0,30)"); c.commit()
c.execute("DELETE FROM user_privacy WHERE user_id!='survivor'"); c.commit(); os._exit(0)
""", str(path)], check=True)
    assert Path(str(path) + '-wal').stat().st_size > 1024 * 1024
    result = maintenance.maintain_store('privacy', str(path), [str(tmp_path)])
    assert result['logical_data_unchanged'] and result['rows'] == 1
    assert result['after_bytes']['-wal'] == 0
    assert result['after_bytes']['database'] < 100_000
    assert b'deleted-private-marker-' not in path.read_bytes()
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute('SELECT * FROM user_privacy').fetchall() == [('survivor', 0, 30)]


def test_fts_segments_compact_without_losing_other_tenant_or_generation_fences(tmp_path):
    fts = tmp_path / 'lexical.sqlite3'
    with closing(sqlite3.connect(fts)) as connection:
        connection.execute('CREATE VIRTUAL TABLE lexical_chunks USING fts5(user_id UNINDEXED,content)')
        connection.executemany('INSERT INTO lexical_chunks VALUES(?,?)', [('deleted', 'oldprivatemarker '*100)]*200)
        connection.execute("INSERT INTO lexical_chunks VALUES('other','surviving study material')")
        connection.commit()
        connection.execute("DELETE FROM lexical_chunks WHERE user_id='deleted'")
        connection.commit()
    generations = tmp_path / 'maintenance-generations.sqlite3'
    with closing(sqlite3.connect(generations)) as connection:
        connection.execute('CREATE TABLE knowledge_index_state(user_id TEXT PRIMARY KEY,state_json TEXT)')
        connection.executemany('INSERT INTO knowledge_index_state VALUES(?,?)', [('deleted', '{"deleted":true}'), ('other', '{}')])
        connection.commit()
    result = maintenance.run({'lexical': str(fts), 'generations': str(generations)}, [str(tmp_path)])
    assert result['status'] == 'completed'
    assert b'oldprivatemarker' not in fts.read_bytes()
    with closing(sqlite3.connect(fts)) as connection:
        assert connection.execute("SELECT user_id FROM lexical_chunks WHERE lexical_chunks MATCH 'surviving'").fetchall() == [('other',)]
        assert connection.execute("SELECT COUNT(*) FROM lexical_chunks WHERE lexical_chunks MATCH 'oldprivatemarker'").fetchone()[0] == 0
    with closing(sqlite3.connect(generations)) as connection:
        assert connection.execute("SELECT state_json FROM knowledge_index_state WHERE user_id='deleted'").fetchone()[0] == '{"deleted":true}'


def test_busy_writer_or_insufficient_space_does_not_claim_success(tmp_path, monkeypatch):
    path = tmp_path / 'privacy.sqlite3'
    create_privacy(path)
    with closing(sqlite3.connect(path)) as writer:
        writer.execute('BEGIN IMMEDIATE')
        assert maintenance.run({'privacy': str(path)}, [str(tmp_path)])['status'] == 'failed'
        writer.rollback()
    monkeypatch.setattr(maintenance.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
    result = maintenance.run({'privacy': str(path)}, [str(tmp_path)])
    assert result['stores']['privacy'] == {'status': 'failed', 'code': 'insufficient_space'}
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute('SELECT * FROM user_privacy').fetchall() == [('survivor', 0, 30)]


def test_missing_outside_corrupt_stores_and_symlinks_are_not_compacted(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    root = tmp_path / 'root'
    root.mkdir()
    path = outside / 'privacy.sqlite3'
    create_privacy(path)
    missing = root / 'missing.sqlite3'
    assert maintenance.run({'privacy': str(missing)}, [str(root)])['status'] == 'failed'
    assert not missing.exists()
    assert maintenance.run({'privacy': str(path)}, [str(root)])['status'] == 'failed'
    corrupt = root / 'bad.sqlite3'
    corrupt.write_bytes(b'private content is not an error message')
    result = maintenance.run({'privacy': str(corrupt)}, [str(root)])
    assert result['stores']['privacy'] == {'status': 'failed', 'code': 'storage_failure'}
    assert 'private content' not in str(result)
    link = root / 'link.sqlite3'
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip('symlinks unavailable on this host')
    assert maintenance.run({'privacy': str(link)}, [str(root)])['status'] == 'failed'


def host_script():
    path = Path(__file__).resolve().parents[2] / 'scripts' / 'maintain_sqlite.py'
    spec = importlib.util.spec_from_file_location('maintain_sqlite_host', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def container(service='python-agent', running=False, backend='sqlite'):
    return {'Config': {'Env': ['AUXILIARY_STORE_BACKEND='+backend], 'Labels': {
        'com.docker.compose.project': 'mneme', 'com.docker.compose.service': service}},
        'State': {'Running': running}, 'Mounts': [{'Source': 'D:/Mneme/python-agent/data', 'Destination': '/app/data', 'RW': True}]}


def test_mysql_mode_only_compacts_active_lexical_store_and_docker_writers_must_stop():
    host = host_script()
    target = container()
    project, data = host.config(target)
    assert len(data['stores']) == 5
    _, shared = host.config(container(backend='mysql'))
    assert list(shared['stores']) == ['lexical']
    for peer in (container(running=True), container('java-gateway', True)):
        with pytest.raises(ValueError, match='stop_all'):
            host.stopped_writers(project, target, [peer], data['stores'])
    peer = container('foreign', True)
    peer['Config']['Labels'] = {}
    peer['Mounts'][0]['Source'] = 'D:/Mneme/python-agent'
    with pytest.raises(ValueError, match='another_container'):
        host.stopped_writers(project, target, [peer], data['stores'])
    host.stopped_writers(project, target, [container()], data['stores'])


def test_unmounted_or_overlapping_configured_paths_are_rejected():
    host = host_script()
    target = container()
    target['Config']['Env'] += ['LEXICAL_INDEX_PATH=/unmounted/lexical.sqlite3']
    with pytest.raises(ValueError, match='writable_mount'):
        host.config(target)
    target = container()
    target['Config']['Env'] += ['LEXICAL_INDEX_PATH=/app/data/index-generations.sqlite3']
    with pytest.raises(ValueError, match='overlap'):
        host.config(target)


@pytest.mark.parametrize('suffix', ['-wal', '-shm', '-journal'])
def test_symlink_sidecars_are_rejected_without_touching_target(tmp_path, suffix):
    path = tmp_path / 'privacy.sqlite3'
    create_privacy(path)
    outside = tmp_path / 'private-target'
    outside.write_bytes(b'unchanged private content')
    try:
        Path(str(path) + suffix).symlink_to(outside)
    except OSError:
        pytest.skip('symlinks unavailable on this host')
    result = maintenance.run({'privacy': str(path)}, [str(tmp_path)])
    assert result['stores']['privacy'] == {'status': 'failed', 'code': 'symlink_store_path'}
    assert outside.read_bytes() == b'unchanged private content'


def test_busy_wal_reader_is_not_reported_as_compacted(tmp_path):
    path = tmp_path / 'privacy.sqlite3'
    create_privacy(path)
    with closing(sqlite3.connect(path)) as reader:
        reader.execute('PRAGMA journal_mode=WAL')
        reader.execute('BEGIN')
        reader.execute('SELECT * FROM user_privacy').fetchall()
        result = maintenance.run({'privacy': str(path)}, [str(tmp_path)])
        assert result['status'] == 'failed'
        assert reader.execute('SELECT * FROM user_privacy').fetchall() == [('survivor', 0, 30)]
        reader.rollback()
    assert maintenance.run({'privacy': str(path)}, [str(tmp_path)])['status'] == 'completed'


def test_partial_failure_requires_retry_and_preserves_successful_store(tmp_path):
    path = tmp_path / 'privacy.sqlite3'
    create_privacy(path)
    result = maintenance.run({'privacy': str(path), 'traces': str(tmp_path / 'missing.db')}, [str(tmp_path)])
    assert result['status'] == 'failed'
    assert result['stores']['privacy']['status'] == 'compacted'
    assert result['stores']['traces']['code'] == 'store_missing'
    assert maintenance.run({'privacy': str(path)}, [str(tmp_path)])['stores']['privacy']['rows'] == 1


def test_backend_and_shadowed_readonly_mounts_fail_closed():
    host = host_script()
    with pytest.raises(ValueError, match='unknown_auxiliary_backend'):
        host.config(container(backend='invalid'))
    target = container()
    target['Mounts'].append({'Source': '/readonly', 'Destination': '/app/data/lexical-index.sqlite3', 'RW': False})
    with pytest.raises(ValueError, match='writable_mount'):
        host.config(target)


def test_linux_sources_preserve_case_but_windows_sources_share_guard():
    host = host_script()
    assert host.source_path('/Data/private') != host.source_path('/data/private')
    assert host.source_path('D:\\Mneme\\data') == host.source_path('d:/mneme/DATA')
