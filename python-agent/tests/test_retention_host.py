"""Deletion guard tests use inspected deployment metadata, never host credentials."""
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from contextlib import nullcontext

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('maintain_retention_host', ROOT / 'scripts/maintain_retention.py')
host = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(ROOT / 'scripts'))
try:
    spec.loader.exec_module(host)
finally:
    sys.path.pop(0)


def target():
    return {'Id': 'deployed-id', 'Image': 'sha256:actual-image',
            'Config': {'WorkingDir': '/app', 'Labels': {'com.docker.compose.project': 'mneme',
                       'com.docker.compose.service': 'java-gateway'}, 'Env': [
                       'SPRING_DATASOURCE_URL=jdbc:mysql://mysql/mneme',
                       'SPRING_DATASOURCE_PASSWORD=synthetic-secret',
                       'FILE_STORAGE_PATH=/app/files', 'UNRELATED_SECRET=do-not-forward']},
            'State': {'Running': False}, 'NetworkSettings': {'Networks': {'mneme_default': {}}},
            'Mounts': [{'Source': 'D:/Mneme/data/files', 'Destination': '/app/files', 'RW': True}]}


@pytest.mark.parametrize('value', [{'versions': True}, {'version_days': 0}, {'cache_bytes': -1},
                                  {'unknown': 1}, {'pinned_locations': [None]}, [], None])
def test_invalid_policy_fails_closed(tmp_path, value):
    file = tmp_path / 'policy.json'
    file.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError):
        host.policy_file(file)


def test_config_requires_explicit_database_and_exact_writable_storage():
    info = target()
    _, env, stores, network = host.target_config(info)
    assert 'UNRELATED_SECRET' not in env
    assert stores == {'files': '/app/files'} and network == 'mneme_default'
    info['Mounts'][0]['RW'] = False
    with pytest.raises(ValueError, match='writable_mount'):
        host.target_config(info)
    info = target()
    info['Config']['Env'] = ['FILE_STORAGE_PATH=/app/files']
    with pytest.raises(ValueError, match='database'):
        host.target_config(info)


def test_stopped_replicas_shared_mount_and_foreign_s3_writers_are_checked():
    info = target()
    project, env, stores, _ = host.target_config(info)
    peer = target()
    peer['State']['Running'] = True
    with pytest.raises(ValueError, match='stop_all'):
        host.check_writers(project, info, [peer], stores, env)
    peer['Config']['Labels'] = {}
    peer['Mounts'][0]['Source'] = 'd:/mneme/data'
    with pytest.raises(ValueError, match='another_container'):
        host.check_writers(project, info, [peer], stores, env)
    peer['Mounts'] = []
    env.update(STORAGE_BACKEND='s3', OBJECT_STORAGE_ENDPOINT='http://minio:9000/', OBJECT_STORAGE_BUCKET='mneme')
    peer['Config']['Env'] = [f'{k}={v}' for k, v in env.items()]
    with pytest.raises(ValueError, match='object_storage_writer'):
        host.check_writers(project, info, [peer], stores, env)
    host.check_writers(project, info, [], stores, env)


def test_worker_uses_actual_image_mounts_environment_and_read_only_plan(monkeypatch):
    info = target()
    _, env, _, network = host.target_config(info)
    calls = []
    receipt = {'status': 'planned', 'versions': 2, 'tasks': 1, 'objects': 3, 'caches': 1, 'bytes': 42}

    def run(command, **options):
        calls.append((command, options))
        return SimpleNamespace(returncode=0, stdout=json.dumps(receipt))

    monkeypatch.setattr(host.subprocess, 'run', run)
    assert host.execute(info, env, network, host.DEFAULT_POLICY, False) == receipt
    command, options = calls[0]
    assert 'sha256:actual-image' in command and 'deployed-id:ro' in command
    assert 'synthetic-secret' not in ' '.join(command)
    assert options['env']['SPRING_DATASOURCE_PASSWORD'] == 'synthetic-secret'
    assert '--apply' not in command
    receipt['status'] = 'completed'
    host.execute(info, env, network, host.DEFAULT_POLICY, True)
    assert calls[-1][0][-2:] == ['--apply', '--offline']
    receipt['private_path'] = '/private/content'
    with pytest.raises(ValueError):
        host.execute(info, env, network, host.DEFAULT_POLICY, True)


def test_recovery_requires_actual_mount_and_every_original_current_bytes(tmp_path, monkeypatch):
    root = tmp_path / 'files'
    original = root / '1/2/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee-example.txt'
    original.parent.mkdir(parents=True)
    original.write_bytes(b'current original')
    entry = {'path': 'payload/data/files/' + original.relative_to(root).as_posix(),
             'size': original.stat().st_size, 'sha256': hashlib.sha256(original.read_bytes()).hexdigest()}
    manifest = {'files': [entry]}
    def extract(_archive, destination, **options):
        assert options['selected_paths'] == {'payload/mysql.sql'}
        (destination / 'payload').mkdir(parents=True)
        (destination / 'payload/mysql.sql').write_bytes(b'current sql')
    backup = SimpleNamespace(DATA_SOURCES={'payload/data/files': root},
                             verify_archive=lambda _: manifest, validate_restore_schema=lambda _: None,
                             extract_verified=extract)
    monkeypatch.setattr(host, 'current_sql', lambda *_: b'current sql')
    info = target()
    info['Mounts'][0]['Source'] = str(root)
    _, env, stores, _ = host.target_config(info)
    host.verify_recovery(backup, tmp_path / 'archive', info, env, stores)
    manifest['security'] = {'encrypted': True}
    entry['plaintext_sha256'] = entry['sha256']
    entry['sha256'] = 'ciphertext digest'
    entry['size'] += 28
    host.verify_recovery(backup, tmp_path / 'archive', info, env, stores)
    monkeypatch.setattr(host, 'current_sql', lambda *_: b'changed database')
    with pytest.raises(ValueError, match='database_is_not_current'):
        host.verify_recovery(backup, tmp_path / 'archive', info, env, stores)
    monkeypatch.setattr(host, 'current_sql', lambda *_: b'current sql')
    original.write_bytes(b'changed original')
    with pytest.raises(ValueError, match='missing_current'):
        host.verify_recovery(backup, tmp_path / 'archive', info, env, stores)
    info['Mounts'][0]['Source'] = str(tmp_path / 'other')
    with pytest.raises(ValueError, match='deployed_storage'):
        host.verify_recovery(backup, tmp_path / 'archive', info, env, stores)
    env['STORAGE_BACKEND'] = 's3'
    with pytest.raises(ValueError, match='remote_recovery'):
        host.verify_recovery(backup, tmp_path / 'archive', info, env, stores)


def test_current_sql_requires_exact_deployed_database_and_normalizes_only_clock(monkeypatch):
    info = target()
    _, env, _, _ = host.target_config(info)
    mysql = target()
    mysql['Id'] = 'actual-mysql'
    mysql['Config']['Env'] = ['MYSQL_DATABASE=mneme']
    mysql['NetworkSettings']['Networks']['mneme_default']['Aliases'] = ['mysql']
    monkeypatch.setattr(host, 'docker', lambda *args: 'actual-mysql' if args[0] == 'ps' else json.dumps([mysql]))
    calls = []
    def run(command, **options):
        calls.append(command)
        assert options['check']
        return SimpleNamespace(stdout=b'current sql')
    monkeypatch.setattr(host.subprocess, 'run', run)
    assert host.current_sql(info, env) == b'current sql'
    assert calls[0][:4] == ['docker', 'exec', '-i', 'actual-mysql']
    env['SPRING_DATASOURCE_URL'] = 'jdbc:mysql://foreign/mneme'
    with pytest.raises(ValueError, match='target_unverified'):
        host.current_sql(info, env)
    env['SPRING_DATASOURCE_URL'] = 'jdbc:mysql://mysql/other'
    with pytest.raises(ValueError, match='target_unverified'):
        host.current_sql(info, env)
    assert host.normalized_dump(b'state\n-- Dump completed on 2026-01-01\n') == b'state\n'
    assert host.normalized_dump(b'state changed\n') != b'state\n'


def load_qa():
    spec = importlib.util.spec_from_file_location('retention_qa', ROOT / 'scripts/check_retention.py')
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / 'scripts'))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def test_qa_restart_waits_for_agent_before_gateway_and_restores_entry_on_failure(monkeypatch):
    qa = load_qa()
    peers = [{'Id': service, 'Config': {'Labels': {'com.docker.compose.service': service}}}
             for service in ('java-gateway', 'python-agent')]
    starts = []
    ready = {'python-agent': False}

    def docker(*args):
        if args[0] == 'start':
            starts.append(args[1])
            if args[1] == 'java-gateway':
                assert ready['python-agent']
            return ''
        ready[args[1]] = True
        return json.dumps([{'State': {'Running': True, 'Health': {'Status': 'healthy'}}}])

    monkeypatch.setattr(qa.retention, 'docker', docker)
    qa.restart_exact(peers)
    assert starts == ['python-agent', 'java-gateway']

    def failure(*args):
        if args[0] == 'start':
            starts.append(args[1])
            return ''
        return json.dumps([{'State': {'Running': args[1] != 'python-agent'}}])

    starts.clear()
    monkeypatch.setattr(qa.retention, 'docker', failure)
    with pytest.raises(ValueError, match='service_exited'):
        qa.restart_exact(peers)
    assert starts == ['python-agent', 'java-gateway']


def test_qa_recovery_excludes_unrelated_large_stores_and_resets_globals(monkeypatch, tmp_path):
    qa = load_qa()
    original_sources, original_runner = qa.backup.DATA_SOURCES, qa.backup.run_compose
    monkeypatch.setattr(qa.backup, 'operation_lock', nullcontext)

    def capture(*_):
        assert qa.backup.DATA_SOURCES == {'payload/data/files': tmp_path / 'files'}
        qa.backup.run_compose([], 'exec', '-T', 'mysql', 'sh', '-c', 'synthetic-query', capture=True)
        raise RuntimeError('snapshot failed')

    def run(command, **_):
        assert command == ['docker', 'exec', '-i', 'actual-mysql', 'sh', '-c', 'synthetic-query']

    monkeypatch.setattr(qa.backup, 'capture_snapshot', capture)
    monkeypatch.setattr(qa.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='snapshot failed'):
        qa.capture_recovery({'Id': 'actual-mysql'}, tmp_path / 'files', tmp_path)
    assert qa.backup.DATA_SOURCES is original_sources
    assert qa.backup.run_compose is original_runner
