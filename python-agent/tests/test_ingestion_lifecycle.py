import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import UploadFile

from app.api import knowledge
from app.knowledge import task_tracker
from app.models.knowledge import DocumentIngestRequest


@pytest.fixture(autouse=True)
def isolated_tasks(monkeypatch, tmp_path):
    monkeypatch.setattr(task_tracker, '_task_store', {})
    monkeypatch.setattr(knowledge, 'settings', SimpleNamespace(upload_max_mb=30, upload_dir=str(tmp_path)))


def upload():
    return asyncio.run(knowledge.upload_file(UploadFile(BytesIO(b'source evidence'), filename='source.txt'), 'qa', 'kb'))


@pytest.mark.parametrize('failure', ['write', 'close', 'task', 'submit'])
def test_failed_upload_handoff_removes_only_its_temporary_file(tmp_path, monkeypatch, failure):
    original = knowledge.tempfile.NamedTemporaryFile
    paths = []

    class Temporary:
        def __enter__(self):
            self.file = original(delete=False, dir=tmp_path, suffix='.txt')
            self.name = self.file.name
            paths.append(Path(self.name))
            return self

        def write(self, content):
            self.file.write(content[:3])
            if failure == 'write':
                raise OSError('injected partial write')
            self.file.write(content[3:])

        def __exit__(self, *_):
            self.file.close()
            if failure == 'close':
                raise OSError('injected close error')

    monkeypatch.setattr(knowledge.tempfile, 'NamedTemporaryFile', lambda **_: Temporary())
    if failure == 'task':
        monkeypatch.setattr(knowledge, 'create_task', Mock(side_effect=RuntimeError('injected task failure')))
    monkeypatch.setattr(knowledge, 'executor', SimpleNamespace(submit=Mock(side_effect=RuntimeError('injected submit failure'))))
    sentinel = tmp_path / 'unrelated.txt'
    sentinel.write_text('preserve')
    with pytest.raises((OSError, RuntimeError)):
        upload()
    assert paths and all(not path.exists() for path in paths)
    assert sentinel.read_text() == 'preserve'
    assert all(row['status'] == 'failed' for row in task_tracker._task_store.values())


def test_external_ingest_submit_failure_preserves_original_and_marks_terminal(tmp_path, monkeypatch):
    source = tmp_path / 'original.txt'
    source.write_text('permanent source')
    monkeypatch.setattr(knowledge, 'executor', SimpleNamespace(submit=Mock(side_effect=RuntimeError('queue closed'))))
    with pytest.raises(RuntimeError):
        asyncio.run(knowledge.ingest(DocumentIngestRequest(file_path=str(source), user_id='qa', kb_id='kb')))
    assert source.read_text() == 'permanent source'
    assert len(task_tracker._task_store) == 1
    assert next(iter(task_tracker._task_store.values()))['status'] == 'failed'


@pytest.mark.parametrize('cancel', [False, True])
def test_queued_upload_has_an_owner_after_request_loop_exits(tmp_path, monkeypatch, cancel):
    tmp_path = tmp_path / 'uploads'
    tmp_path.mkdir()
    original = knowledge.tempfile.NamedTemporaryFile
    monkeypatch.setattr(knowledge.tempfile, 'NamedTemporaryFile', lambda **kw: original(**(kw | {'dir': tmp_path})))
    gate = Event()
    parsed = Event()
    pool = ThreadPoolExecutor(max_workers=1)
    pool.submit(gate.wait)
    futures = []
    def submit(*args):
        future = pool.submit(*args)
        futures.append(future)
        return future
    def parse(*args, **_):
        assert Path(args[2]).read_bytes() == b'source evidence'
        parsed.set()
        return 'doc'
    monkeypatch.setattr(knowledge, 'executor', SimpleNamespace(submit=submit))
    monkeypatch.setattr(knowledge, 'ingest_document', parse)
    monkeypatch.setattr(knowledge.vector_store, 'get_collection', lambda *_: None)
    try:
        result = upload()
        assert len(list(tmp_path.iterdir())) == 1
        if cancel:
            assert futures[0].cancel()
        gate.set()
        pool.shutdown(wait=True)
        assert parsed.is_set() is (not cancel)
        assert not list(tmp_path.iterdir())
        assert task_tracker.get_task(result.task_id)['status'] == ('failed' if cancel else 'done')
    finally:
        gate.set()
        pool.shutdown(wait=True, cancel_futures=True)


def test_worker_removes_temporary_file_on_parser_failure(tmp_path, monkeypatch):
    source = tmp_path / 'upload.txt'
    source.write_bytes(b'private source')
    task_id = task_tracker.create_task()
    monkeypatch.setattr(knowledge, 'ingest_document', Mock(side_effect=ValueError('parse failed')))
    knowledge._run_ingestion('qa', 'kb', str(source), task_id, 'source.txt')
    assert not source.exists()
    assert task_tracker.get_task(task_id)['status'] == 'failed'


def test_cleanup_failure_does_not_report_success_or_leak_path(tmp_path, monkeypatch, caplog):
    source = tmp_path / 'private-filename.txt'
    source.write_bytes(b'private source')
    task_id = task_tracker.create_task()
    monkeypatch.setattr(knowledge, 'ingest_document', Mock(return_value='doc'))
    monkeypatch.setattr(knowledge.vector_store, 'get_collection', lambda *_: None)
    monkeypatch.setattr(knowledge.os, 'unlink', Mock(side_effect=PermissionError(str(source))))
    knowledge._run_ingestion('qa', 'kb', str(source), task_id, 'source.txt')
    result = task_tracker.get_task(task_id)
    assert source.exists() and result['status'] == 'failed'
    assert str(source) not in str(result) + caplog.text
    assert '清理' in result['error']


def test_running_task_outlives_retention_then_expires_from_completion(monkeypatch):
    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    clock = [now]
    monkeypatch.setattr(task_tracker, 'utc_now', lambda: clock[0])
    task_id = task_tracker.create_task()
    clock[0] += timedelta(seconds=task_tracker.TASK_TTL_SECONDS + 1)
    assert task_tracker.get_task(task_id)['status'] == 'processing'
    task_tracker.update_task(task_id, 'done', chunks=7)
    assert task_tracker.get_task(task_id)['chunks'] == 7
    clock[0] += timedelta(seconds=task_tracker.TASK_TTL_SECONDS - 1)
    assert task_tracker.get_task(task_id) is not None
    clock[0] += timedelta(seconds=2)
    task_tracker.create_task()  # No polling of the expired record is required.
    assert task_id not in task_tracker._task_store


def test_task_snapshots_cannot_mutate_internal_status():
    task_id = task_tracker.create_task()
    task_tracker.get_task(task_id)['status'] = 'done'
    assert task_tracker.get_task(task_id)['status'] == 'processing'


def test_terminal_updates_prune_expired_history_without_expiring_active_tasks(monkeypatch):
    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(task_tracker, 'utc_now', lambda: now)
    old = (now - timedelta(seconds=task_tracker.TASK_TTL_SECONDS + 1)).isoformat()
    task_tracker._task_store.update({
        'done': {'status': 'done', 'created_at': old, 'completed_at': old},
        'failed': {'status': 'failed', 'created_at': old, 'completed_at': old},
        'active': {'status': 'processing', 'created_at': old},
    })
    task_tracker.update_task('active', 'failed', error='queue stopped')
    assert set(task_tracker._task_store) == {'active'}
    assert task_tracker.get_task('active')['completed_at'] == now.isoformat()
