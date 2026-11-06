"""Backup retention must leave recoverable rollback archives before any deletion."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import backup_restore as backup, maintain_backups as retention  # noqa: E402


NOW = datetime(2026, 11, 6, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_backup_settings(monkeypatch):
    for name in list(os.environ):
        if name.startswith('BACKUP_'):
            monkeypatch.delenv(name)


def archive(root, age, monkeypatch, *, encrypted=False, metadata=None):
    created = NOW - timedelta(days=age)
    stamp = created.strftime('%Y%m%d-%H%M%S')
    staging = root.parent / ('staging-' + stamp)
    (staging / 'payload/data/files').mkdir(parents=True)
    (staging / 'payload/mysql.sql').write_bytes(b'CREATE TABLE marker(id INT);')
    (staging / 'payload/data/files/note.txt').write_bytes(b'recoverable original')
    monkeypatch.setattr(backup, 'utc_now', lambda: created.isoformat())
    if encrypted:
        monkeypatch.setenv('BACKUP_ENCRYPTION_KEY', 'backup-test-encryption-secret')
        monkeypatch.setenv('BACKUP_SIGNING_KEY', 'backup-test-independent-signing-secret')
    path = root / ('mneme-' + stamp + '.tar.gz')
    backup.create_archive(staging, path, metadata=metadata)
    os.utime(path, (created.timestamp(),) * 2)
    return path


def collect(root, protected, **options):
    return retention.collect(root, protect=[protected.name], now=NOW, **options)


def test_plan_apply_rollback_protection_restore_and_idempotence(tmp_path, monkeypatch):
    root = tmp_path / 'backups'
    pinned = archive(root, 100, monkeypatch, encrypted=True)
    old = archive(root, 90, monkeypatch, encrypted=True)
    recent = archive(root, 10, monkeypatch, encrypted=True)
    newest = archive(root, 1, monkeypatch, encrypted=True)
    checkpoint = root / 'pre-restore-123.tar.gz'
    checkpoint.write_bytes(b'operator checkpoint')
    (root / 'jobs').mkdir()
    unknown = root / 'notes.md'
    unknown.write_bytes(b'operator notes')
    before = {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}
    plan = collect(root, pinned, keep=2)
    assert plan == dict(status='planned', files=1, bytes=old.stat().st_size, retained=3, unknown=3)
    assert before == {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}
    assert collect(root, pinned, keep=2, apply=True) == plan | {'status': 'completed'}
    assert not old.exists()
    assert collect(root, pinned, keep=2, apply=True)['files'] == 0
    for index, path in enumerate((pinned, recent, newest)):
        target = tmp_path / f'restore-{index}'
        backup.extract_verified(path, target)
        assert (target / 'payload/data/files/note.txt').read_bytes() == b'recoverable original'
    assert checkpoint.read_bytes() == before[checkpoint.name]
    assert unknown.read_bytes() == before[unknown.name]


@pytest.mark.parametrize('keep,days', [(0, 30), (1, 30), (True, 30), (2, 0), (2, False)])
def test_invalid_policy(tmp_path, keep, days):
    with pytest.raises(backup.BackupError):
        retention.collect(tmp_path, protect=['mneme-20260101-010101.tar.gz'], keep=keep, days=days)


@pytest.mark.parametrize('protect', [[], ['../mneme-20260101-010101.tar.gz'], ['pre-restore-a.tar.gz'], ['mneme-20260101-010101.tar.gz']])
def test_requires_existing_explicit_rollback(tmp_path, protect):
    with pytest.raises(backup.BackupError):
        retention.collect(tmp_path, protect=protect)


def test_recently_copied_old_archive_is_retained(tmp_path, monkeypatch):
    pinned = archive(tmp_path / 'backups', 100, monkeypatch)
    copied = archive(pinned.parent, 90, monkeypatch)
    archive(pinned.parent, 1, monkeypatch)
    archive(pinned.parent, 2, monkeypatch)
    os.utime(copied, (NOW.timestamp(),) * 2)
    assert collect(pinned.parent, pinned, keep=2, apply=True)['files'] == 0
    assert copied.exists()


@pytest.mark.parametrize('failure', ['corrupt', 'missing_key', 'wrong_key', 'bad_time', 'future_time'])
def test_bad_archive_blocks_all_deletion(tmp_path, monkeypatch, failure):
    root = tmp_path / 'backups'
    pinned = archive(root, 100, monkeypatch, encrypted=True)
    old = archive(root, 90, monkeypatch, encrypted=True)
    survivor = archive(root, 1, monkeypatch, encrypted=True)
    if failure == 'corrupt':
        survivor.write_bytes(b'invalid archive')
    elif failure == 'missing_key':
        monkeypatch.delenv('BACKUP_ENCRYPTION_KEY')
    elif failure == 'wrong_key':
        monkeypatch.setenv('BACKUP_ENCRYPTION_KEY', 'unrelated-backup-encryption-key')
    else:
        verify = backup.verify_archive

        def altered(*args, **kwargs):
            value = verify(*args, **kwargs)
            value['created_at'] = 'invalid' if failure == 'bad_time' else (NOW + timedelta(days=1)).isoformat()
            return value

        monkeypatch.setattr(backup, 'verify_archive', altered)
    with pytest.raises((backup.BackupError, ValueError)):
        collect(root, pinned, keep=2, apply=True)
    assert old.exists() and pinned.exists()


@pytest.mark.parametrize('link_type', ['hardlink', 'symlink', 'directory_symlink'])
def test_links_block_deletion(tmp_path, monkeypatch, link_type):
    root = tmp_path / 'backups'
    pinned = archive(root, 100, monkeypatch)
    if link_type == 'hardlink':
        os.link(pinned, root / 'mneme-20260101-010101.tar.gz')
    else:
        link = tmp_path / 'linked' if link_type == 'directory_symlink' else root / 'mneme-20260101-010101.tar.gz'
        try:
            link.symlink_to(root if link_type == 'directory_symlink' else pinned,
                            target_is_directory=link_type == 'directory_symlink')
        except OSError:
            pytest.skip('symlink creation unavailable on this host')
        if link_type == 'directory_symlink':
            root = link
    with pytest.raises(backup.BackupError):
        collect(root, pinned, apply=True)
    assert pinned.exists()


def test_inventory_changed_during_verification_blocks_all_deletion(tmp_path, monkeypatch):
    root = tmp_path / 'backups'
    pinned = archive(root, 100, monkeypatch)
    old = archive(root, 90, monkeypatch)
    archive(root, 2, monkeypatch)
    latest = archive(root, 1, monkeypatch)
    verify = backup.verify_archive

    def altered(path, **options):
        result = verify(path, **options)
        if options.get('decrypt'):
            latest.touch()
        return result

    monkeypatch.setattr(backup, 'verify_archive', altered)
    with pytest.raises(backup.BackupError, match='inventory changed'):
        collect(root, pinned, keep=2, apply=True)
    assert old.exists()


def test_cli_uses_shared_lock_and_redacts_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(backup, 'PROJECT_ROOT', tmp_path)
    with backup.operation_lock():
        assert retention.main(['--directory', str(tmp_path), '--protect', 'mneme-20260101-010101.tar.gz', '--apply']) == 1
    output = capsys.readouterr()
    assert output.out == '' and 'blocked' in output.err
    assert str(tmp_path) not in output.err


@pytest.mark.parametrize('failure', ['schema', 'migration', 'model_key'])
def test_incompatible_survivor_blocks_deletion(tmp_path, monkeypatch, failure):
    root = tmp_path / 'backups'
    pinned = archive(root, 100, monkeypatch)
    old = archive(root, 90, monkeypatch)
    archive(root, 2, monkeypatch)
    metadata = {'application_schema_max': backup.supported_schema_version() + 1} if failure == 'schema' else {
        'application_schema_max': 1, 'schema_history_format': 1,
        'flyway_schema_history': [{'version': 1, 'checksum': 0, 'script': 'V1__unavailable.sql'}]
    } if failure == 'migration' else {
        'model_config_keys': {'required_versions': ['missing-key-version']}
    }
    archive(root, 1, monkeypatch, metadata=metadata)
    if failure == 'model_key':
        import json
        import subprocess

        def config(files, *args, **kwargs):
            assert files == ['docker-compose.yml', 'docker-compose.selfhost.yml']
            return subprocess.CompletedProcess([], 0, json.dumps({'services': {'java-gateway': {'environment': {
                'MODEL_CONFIG_ENCRYPTION_KEY': 'independent-current-model-secret-12345678',
                'MODEL_CONFIG_KEY_VERSION': 'current', 'MNEME_PRODUCTION': 'true'
            }}}}).encode())

        monkeypatch.setattr(backup, 'run_compose', config)
    with pytest.raises(backup.BackupError):
        collect(root, pinned, keep=2, apply=True,
                compose_files=['docker-compose.yml', 'docker-compose.selfhost.yml'])
    assert old.exists() and pinned.exists()


def test_partial_deletion_fails_and_rerun_completes(tmp_path, monkeypatch):
    root = tmp_path / 'backups'
    pinned = archive(root, 100, monkeypatch)
    oldest = archive(root, 90, monkeypatch)
    newer = archive(root, 80, monkeypatch)
    archive(root, 2, monkeypatch)
    archive(root, 1, monkeypatch)
    unlink = Path.unlink

    def fail_one(path, *args, **kwargs):
        if path == oldest:
            raise PermissionError('PRIVATE_PATH_AND_ERROR')
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', fail_one)
    with pytest.raises(PermissionError):
        collect(root, pinned, keep=2, apply=True)
    assert pinned.exists() and oldest.exists() and not newer.exists()
    monkeypatch.setattr(Path, 'unlink', unlink)
    assert collect(root, pinned, keep=2, apply=True)['files'] == 1
    assert collect(root, pinned, keep=2, apply=True)['files'] == 0


def test_cli_io_error_is_redacted(tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise OSError('PRIVATE_PATH_AND_ERROR')

    monkeypatch.setattr(backup, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(retention, 'collect', fail)
    assert retention.main(['--protect', 'mneme-20260101-010101.tar.gz', '--apply']) == 1
    output = capsys.readouterr()
    assert output.out == '' and 'blocked' in output.err and 'PRIVATE' not in output.err
    assert not (tmp_path / '.backup-restore.lock').exists()


def test_directory_replacement_blocks_deletion(tmp_path, monkeypatch):
    root = tmp_path / 'backups'
    pinned = archive(root, 100, monkeypatch)
    old = archive(root, 90, monkeypatch)
    archive(root, 2, monkeypatch)
    archive(root, 1, monkeypatch)
    verify = backup.verify_archive
    previous = tmp_path / 'previous'

    def replace_directory(path, **options):
        result = verify(path, **options)
        if options.get('decrypt') and not previous.exists():
            root.rename(previous)
            root.mkdir()
            for item in previous.iterdir():
                import shutil
                shutil.copy2(item, root / item.name)
        return result

    monkeypatch.setattr(backup, 'verify_archive', replace_directory)
    with pytest.raises(backup.BackupError, match='directory changed'):
        collect(root, pinned, keep=2, apply=True)
    assert old.exists() and (previous / old.name).exists()


def test_cli_plan_apply_and_recovery_use_real_encrypted_archives(tmp_path, monkeypatch):
    import json
    import shutil
    import subprocess

    root = tmp_path / 'backups'
    pinned = archive(root, 100, monkeypatch, encrypted=True)
    old = archive(root, 90, monkeypatch, encrypted=True)
    archive(root, 2, monkeypatch, encrypted=True)
    archive(root, 1, monkeypatch, encrypted=True)
    # Run the actual CLI from an isolated checkout so its lock never touches a
    # live deployment. No collectors, archive readers or crypto are mocked.
    checkout = tmp_path / 'checkout'
    scripts = checkout / 'scripts'
    scripts.mkdir(parents=True)
    for source in (Path(backup.__file__), Path(retention.__file__)):
        shutil.copyfile(source, scripts / source.name)
    command = [sys.executable, str(scripts / 'maintain_backups.py'),
               '--directory', str(root), '--protect', pinned.name, '--keep', '2']
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    plan = subprocess.run(command, capture_output=True, check=True, text=True, timeout=30)
    assert json.loads(plan.stdout)['files'] == 1 and not plan.stderr
    assert before == {path.name: path.read_bytes() for path in root.iterdir()}
    result = subprocess.run(command + ['--apply'], capture_output=True, check=True, text=True, timeout=30)
    assert json.loads(result.stdout) == json.loads(plan.stdout) | {'status': 'completed'}
    assert not old.exists() and not result.stderr
    repeated = subprocess.run(command + ['--apply'], capture_output=True, check=True, text=True, timeout=30)
    assert json.loads(repeated.stdout)['files'] == 0
    assert not (checkout / '.backup-restore.lock').exists()
    for index, path in enumerate(root.iterdir()):
        target = tmp_path / f'cli-restore-{index}'
        backup.extract_verified(path, target)
        assert (target / 'payload/data/files/note.txt').read_bytes() == b'recoverable original'


