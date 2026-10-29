import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import recovery_worker as worker


def test_restart_marks_inflight_jobs_interrupted(tmp_path):
    jobs = tmp_path / 'jobs'
    jobs.mkdir()
    (jobs / 'a.json').write_text(json.dumps({'id': 'a', 'status': 'running', 'created_at': 'now'}))
    executor = worker.RecoveryExecutor(tmp_path, ['docker-compose.yml'])
    assert executor.history()['jobs'][0]['status'] == 'interrupted'
    assert not executor.lock.locked()


def test_preview_rejects_traversal_and_archive_changes_release_lock(tmp_path, monkeypatch):
    executor = worker.RecoveryExecutor(tmp_path, [])
    with pytest.raises(ValueError):
        executor.archive('../escape.tar.gz')
    monkeypatch.setattr(executor, 'preview', lambda _: {'sha256': 'verified'})
    with pytest.raises(ValueError, match='changed'):
        executor.submit({'action': 'restore', 'confirmation': 'RESTORE SITE', 'archive': 'a.tar.gz', 'sha256': 'stale'})
    assert not executor.lock.locked()
    with pytest.raises(ValueError, match='confirmation'):
        executor.submit({'action': 'backup'})


def test_executor_runs_allowlisted_script_without_shell_and_persists_failure(tmp_path, monkeypatch):
    executor = worker.RecoveryExecutor(tmp_path, ['docker-compose.yml', 'docker-compose.selfhost.yml'])
    process = Mock(returncode=1)
    run = Mock(return_value=process)
    monkeypatch.setattr(worker.subprocess, 'run', run)
    executor.lock.acquire()
    executor.execute({'id': 'test', 'action': 'backup', 'created_at': 'now', 'status': 'queued'})
    record = executor.history()['jobs'][0]
    assert record['status'] == 'failed'
    assert record['exit_code'] == 1
    assert not executor.lock.locked()
    args = run.call_args.args[0]
    assert args[0] == sys.executable
    assert args.count('--compose-file') == 2
    assert run.call_args.kwargs['shell'] is False


def test_second_operation_cannot_run_during_site_recovery(tmp_path):
    executor = worker.RecoveryExecutor(tmp_path, [])
    executor.lock.acquire()
    with pytest.raises(ValueError, match='Another'):
        executor.submit({'action': 'backup', 'confirmation': 'BACKUP SITE'})
    assert executor.lock.locked()
    executor.lock.release()
