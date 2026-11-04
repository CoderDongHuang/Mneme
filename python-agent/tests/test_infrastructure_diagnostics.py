import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from qdrant_client import QdrantClient

from app.core.storage_diagnostics import check_storage

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import backup_key_diagnostics as keys
from scripts import recovery_worker


def test_real_local_multishard_qdrant_roundtrip_and_no_residual_collections(tmp_path):
    clients = [QdrantClient(path=str(tmp_path / str(i))) for i in range(2)]
    try:
        for raw in clients:
            raw.create_collection('retained', vectors_config={})
        result = check_storage([SimpleNamespace(raw=raw) for raw in clients])
        assert result['connection'] == result['operation'] == result['cleanup'] == 'passed'
        assert result['code'] == 'OK'
        assert all([item.name for item in raw.get_collections().collections] == ['retained'] for raw in clients)
    finally:
        for raw in clients:
            raw.close()


def test_qdrant_failed_write_attempt_still_cleans_and_never_exposes_error():
    raw = Mock()
    raw.upsert.side_effect = RuntimeError('private-api-key')
    raw.collection_exists.return_value = False
    result = check_storage([SimpleNamespace(raw=raw)])
    assert result['connection'] == 'passed'
    assert result['operation'] == 'failed'
    assert result['cleanup'] == 'passed'
    raw.delete_collection.assert_called_once()
    assert 'private-api-key' not in json.dumps(result)
    raw.delete_collection.side_effect = RuntimeError('private-endpoint')
    assert check_storage([SimpleNamespace(raw=raw)])['code'] == 'CLEANUP_FAILED'


def test_qdrant_connection_failure_and_unconfigured_do_not_claim_success():
    raw = Mock()
    raw.get_collections.side_effect = ConnectionError('secret')
    result = check_storage([SimpleNamespace(raw=raw)])
    assert result['connection'] == 'failed'
    assert result['operation'] == 'not_run'
    assert result['cleanup'] == 'not_required'
    raw.create_collection.assert_not_called()
    assert check_storage([])['configuration'] == 'missing'


def test_qdrant_deadline_preserves_cleanup_and_rejects_unchecked_shards(monkeypatch):
    from app.core import storage_diagnostics as diagnostics
    clock = [0.0]
    monkeypatch.setattr(diagnostics.time, 'monotonic', lambda: clock[0])
    raw, unchecked = Mock(), Mock()
    raw.create_collection.side_effect = lambda *a, **kw: clock.__setitem__(0, 46.0)
    raw.collection_exists.return_value = False
    result = check_storage([SimpleNamespace(raw=raw), SimpleNamespace(raw=unchecked)])
    assert result['code'] != 'OK'
    assert result['operation'] == 'failed'
    assert result['cleanup'] == 'passed'
    raw.upsert.assert_not_called()
    raw.delete_collection.assert_called_once()
    unchecked.get_collections.assert_not_called()


def test_qdrant_concurrent_diagnostic_is_busy_without_touching_storage():
    from app.core import storage_diagnostics as diagnostics
    raw = Mock()
    diagnostics._probe_lock.acquire()
    try:
        assert check_storage([SimpleNamespace(raw=raw)])['code'] == 'BUSY'
        raw.get_collections.assert_not_called()
    finally:
        diagnostics._probe_lock.release()


def test_diagnostic_client_bounds_http_without_changing_business_client(monkeypatch):
    from app.knowledge import qdrant_store
    business, diagnostic = MagicMock(), MagicMock()
    factory = MagicMock(side_effect=[business, diagnostic])
    monkeypatch.setattr(qdrant_store, 'QdrantClient', factory)
    client = qdrant_store.VectorClient(url='http://configured-qdrant:6333', api_key='private-key')
    assert client.raw is business
    with client.diagnostic_client() as probe:
        assert probe is not business
    assert client.raw is business
    assert factory.call_args.kwargs == {'url': 'http://configured-qdrant:6333', 'api_key': 'private-key',
                                      'timeout': 2, 'check_compatibility': False}
    diagnostic.close.assert_called_once()
    business.close.assert_not_called()


def test_real_http_diagnostic_client_connects_and_closes_after_failure():
    from app.knowledge.qdrant_store import VectorClient

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({'result': {'collections': []}, 'status': 'ok', 'time': 0}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Use the actual pinned Qdrant client, including its real HTTP transport.
    client = VectorClient.__new__(VectorClient)
    client._diagnostic_options = {'url': f'http://127.0.0.1:{server.server_port}', 'api_key': None}
    try:
        with pytest.raises(ValueError, match='synthetic failure'):
            with client.diagnostic_client() as probe:
                assert probe.get_collections().collections == []
                raise ValueError('synthetic failure')
        assert probe._client.openapi_client.client._client.is_closed
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.fixture
def isolated_keys(monkeypatch):
    for name in ('BACKUP_SIGNING_KEY', 'BACKUP_ENCRYPTION_KEY', 'BACKUP_KMS_COMMAND'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('BACKUP_SIGNING_KEY', 'a' * 64)
    monkeypatch.setenv('BACKUP_ENCRYPTION_KEY', 'b' * 64)


def test_current_backup_keys_encrypt_sign_decrypt_and_reject_corruption(isolated_keys, monkeypatch):
    monkeypatch.setattr(keys.backup_restore, '_security_keys', lambda: (b'e' * 32, b's' * 32))
    result = keys.check_keys()
    assert result['code'] == 'OK'
    assert result['operation'] == 'passed'
    assert result['connection'] == 'not_applicable'
    monkeypatch.setattr(keys.backup_restore, '_security_keys', lambda: (b'invalid', b's' * 32))
    assert keys.check_keys()['code'] == 'KEY_CHECK_FAILED'
    monkeypatch.delenv('BACKUP_SIGNING_KEY')
    assert keys.check_keys()['configuration'] == 'missing'


def test_kms_wrap_unwrap_mismatch_fails_closed_and_strips_secret(isolated_keys, monkeypatch):
    monkeypatch.setenv('BACKUP_KMS_COMMAND', 'operator-owned-provider')
    monkeypatch.setattr(keys.backup_restore, '_security_keys', lambda: (None, b's' * 32))
    provider = Mock(side_effect=[b'wrapped-private-key', b'wrong' * 6])
    monkeypatch.setattr(keys.backup_restore, '_key_provider', provider)
    result = keys.check_keys()
    assert result['code'] == 'KEY_CHECK_FAILED'
    assert 'private' not in json.dumps(result)
    assert provider.call_args_list[0].args[0] == 'wrap'
    assert provider.call_args_list[1].args[0] == 'unwrap'


def test_real_host_route_requires_auth_is_exclusive_and_never_creates_backup_job(tmp_path, monkeypatch, isolated_keys):
    executor = recovery_worker.RecoveryExecutor(tmp_path, [])
    real_check = keys.check_keys
    check = Mock(return_value={'configuration': 'present', 'connection': 'not_applicable',
                              'operation': 'passed', 'cleanup': 'not_required', 'code': 'OK'})
    monkeypatch.setattr(keys, 'check_keys', check)
    server = ThreadingHTTPServer(('127.0.0.1', 0), recovery_worker.handler(executor, 'test-token'))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/site/keys/check'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(token):
        with opener.open(urllib.request.Request(url, data=b'', headers={'Authorization': 'Bearer ' + token}), timeout=3) as response:
            return json.load(response)

    try:
        with pytest.raises(urllib.error.HTTPError) as denied:
            request('wrong')
        assert denied.value.code == 403
        check.assert_not_called()
        executor.lock.acquire()
        try:
            assert request('test-token')['code'] == 'BUSY'
            check.assert_not_called()
        finally:
            executor.lock.release()
        assert request('test-token')['code'] == 'OK'
        assert not executor.lock.locked()
        assert executor.history()['jobs'] == []
        check.assert_called_once_with()
        # Exercise the real key implementation over HTTP as well as routing.
        monkeypatch.setattr(keys, 'check_keys', real_check)
        assert request('test-token')['code'] == 'OK'
        assert executor.history()['jobs'] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize('check_fails', [False, True])
def test_key_check_releases_operation_lock_before_http_response(tmp_path, monkeypatch, check_fails):
    from concurrent.futures import ThreadPoolExecutor

    executor = recovery_worker.RecoveryExecutor(tmp_path, [])
    response_started = threading.Event()
    allow_response = threading.Event()
    lock_states = []
    handler = recovery_worker.handler(executor, 'test-token')
    respond = handler.respond

    def slow_respond(self, code, body):
        lock_states.append(executor.lock.locked())
        response_started.set()
        if not allow_response.wait(3):
            raise TimeoutError('Test response gate timed out')
        return respond(self, code, body)

    def check():
        assert executor.lock.locked()  # Protect the actual key operation.
        if check_fails:
            raise RuntimeError('private-provider-error')
        return {'code': 'OK'}

    monkeypatch.setattr(handler, 'respond', slow_respond)
    monkeypatch.setattr(keys, 'check_keys', check)
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request():
        req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/site/keys/check',
                                     data=b'', headers={'Authorization': 'Bearer test-token'})
        try:
            with opener.open(req, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(request)
            try:
                assert response_started.wait(3)
                assert lock_states == [False]
                # A blocked response must not keep the backup/restore gate busy.
                assert executor.lock.acquire(blocking=False)
                executor.lock.release()
            finally:
                allow_response.set()
            status, body = pending.result(timeout=5)
        assert status == (500 if check_fails else 200)
        assert body == ({'message': 'Host recovery service failed'} if check_fails else {'code': 'OK'})
        assert executor.history()['jobs'] == []
    finally:
        allow_response.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
