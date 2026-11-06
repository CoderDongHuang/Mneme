"""Real-stack QA: age a fresh document, capture SQL/originals, sweep, restart."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import backup_restore as backup
import maintain_retention as retention


def restart_exact(peers):
    """Restore the captured deployment in dependency order, waiting for readiness."""
    def start_group(group):
        if not group:
            return
        retention.docker('start', *(peer['Id'] for peer in group))
        deadline = time.monotonic() + 90
        while True:
            states = [json.loads(retention.docker('inspect', peer['Id']))[0]['State'] for peer in group]
            if any(not state['Running'] for state in states):
                raise ValueError('service_exited_during_restart')
            if all(state.get('Health', {}).get('Status', 'healthy') == 'healthy' for state in states):
                return
            if time.monotonic() >= deadline:
                raise ValueError('service_restart_not_ready')
            time.sleep(1)

    services = {peer['Id']: peer['Config']['Labels'].get('com.docker.compose.service') for peer in peers}
    dependencies = [peer for peer in peers if services[peer['Id']] not in ('java-gateway', 'python-agent')]
    agents = [peer for peer in peers if services[peer['Id']] == 'python-agent']
    gateways = [peer for peer in peers if services[peer['Id']] == 'java-gateway']
    try:
        start_group(dependencies)
        start_group(agents)
    finally:
        # Restore the web entry point even when a dependency fails readiness.
        start_group(gateways)


def capture_recovery(mysql, root, folder):
    """Back up only affected domains using the deployed MySQL and all originals."""
    def exact_mysql(_files, *arguments, capture=False, **options):
        if arguments[:3] != ('exec', '-T', 'mysql'):
            raise ValueError('unexpected_backup_operation')
        return subprocess.run(['docker', 'exec', '-i', mysql['Id'], *arguments[3:]],
                              capture_output=True, check=True)

    with backup.operation_lock():
        previous = backup.run_compose
        previous_sources = backup.DATA_SOURCES
        backup.run_compose = exact_mysql
        backup.DATA_SOURCES = {'payload/data/files': root}
        try:
            archive = folder / 'recovery.tar.gz'
            backup.capture_snapshot([], folder / 'snapshot', archive)
            return archive
        finally:
            backup.run_compose = previous
            backup.DATA_SOURCES = previous_sources


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('user', type=int)
    parser.add_argument('document', type=int)
    args = parser.parse_args()
    if os.getenv('MNEME_REAL_E2E') != 'true' or min(args.user, args.document) < 1:
        raise ValueError('real_qa_only')
    gateway_ids = retention.docker('ps', '--filter', 'label=com.docker.compose.service=java-gateway', '-q').split()
    if len(gateway_ids) != 1:
        raise ValueError('ambiguous_gateway')
    gateway = json.loads(retention.docker('inspect', gateway_ids[0]))[0]
    project, env, stores, _ = retention.target_config(gateway)
    if env.get('STORAGE_BACKEND', 'local').lower() != 'local':
        # The remote deployment intentionally supports inventory only until its
        # recovery set can prove coverage of every object. Do not fake local QA.
        result = subprocess.run([sys.executable, str(Path(retention.__file__)), '--container', gateway['Id']],
                                capture_output=True, text=True, check=True, timeout=120)
        if json.loads(result.stdout)['status'] != 'planned':
            raise ValueError('remote_inventory_failed')
        try:
            retention.verify_recovery(backup, Path('unused'), gateway, env, stores)
        except ValueError as error:
            if str(error) != 'remote_recovery_coverage_not_verified':
                raise
        else:
            raise ValueError('remote_deletion_not_blocked')
        print(json.dumps({'status': 'remote_read_only'}))
        return
    ids = retention.docker('ps', '--filter', f'label=com.docker.compose.project={project}', '-q').split()
    peers = json.loads(retention.docker('inspect', *ids))
    mysql = [peer for peer in peers if peer['Config']['Labels'].get('com.docker.compose.service') == 'mysql']
    if len(mysql) != 1 or retention.mounted_paths(gateway, stores) != [retention.source_path(str(backup.DATA_SOURCES['payload/data/files']))]:
        raise ValueError('unexpected_deployment')

    def sql(query):
        return retention.docker('exec', '-i', mysql[0]['Id'], 'sh', '-c',
                                'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B "$MYSQL_DATABASE"', input=query).strip()

    if sql(f"SELECT COUNT(*) FROM user u JOIN knowledge_base b ON b.user_id=u.id JOIN knowledge_document d ON d.kb_id=b.id WHERE u.id={args.user} AND d.id={args.document} AND u.username REGEXP '^storageqa_[a-f0-9]{{12}}$';") != '1':
        raise ValueError('not_storage_qa_document')
    rows = [line.split('\t') for line in sql(f'SELECT version_number,file_path FROM knowledge_document_version WHERE document_id={args.document} ORDER BY version_number;').splitlines()]
    if [int(row[0]) for row in rows] != list(range(1, 12)):
        raise ValueError('qa_requires_eleven_versions')
    root = backup.DATA_SOURCES['payload/data/files']
    paths = []
    for _, location in rows:
        relative = Path(location).relative_to(stores['files'])
        path = root / relative
        if not path.is_file() or relative.parts[0] != str(args.user):
            raise ValueError('unexpected_qa_original')
        paths.append(path)
    # Only these services write the SQL/version/originals domains being swept.
    # Qdrant/Redis are untouched; copying their unrelated stores can create a
    # multi-gigabyte snapshot and a needless cold restart on a real installation.
    stopped_peers = [peer for peer in peers if peer['Config']['Labels'].get('com.docker.compose.service') in ('java-gateway', 'python-agent')]
    stopped = [peer['Id'] for peer in stopped_peers]
    # Exact existing IDs are restarted; compose up could silently replace local config.
    with tempfile.TemporaryDirectory(prefix='mneme-retention-qa-') as directory:
        folder = Path(directory)
        policy = folder / 'policy.json'
        policy.write_text(json.dumps(retention.DEFAULT_POLICY | {
            'versions': 2, 'version_days': 6000, 'task_days': 6000,
            'orphan_hours': 144000, 'cache_hours': 1000000, 'cache_bytes': 2**60,
            'pinned_locations': [rows[1][1]],
        }), encoding='utf-8')
        command = [sys.executable, str(Path(retention.__file__)), '--container', gateway['Id'], '--policy', str(policy)]

        def maintain(*options, success=True):
            result = subprocess.run(command + list(options), capture_output=True, text=True, timeout=120)
            if (result.returncode == 0) != success:
                raise ValueError('unexpected_maintenance_result')
            return json.loads(result.stdout) if success else None

        maintain('--apply', success=False)  # Recovery set is mandatory.
        maintain('--apply', '--recovery-archive', str(folder / 'missing'), success=False)  # Live writers rejected.
        try:
            retention.docker('stop', *stopped)
            sql(f"UPDATE knowledge_document_version SET created_at='2000-01-01' WHERE document_id={args.document}; UPDATE processing_task SET updated_at='2000-01-01' WHERE user_id={args.user};")
            for path in paths:
                # Docker Desktop clamps pre-epoch Windows bind timestamps to 1970.
                # Use a portable positive timestamp while keeping all ordinary
                # project data newer than the deliberately distant QA cutoff.
                os.utime(path, (946684800, 946684800))
            before = sql(f'SELECT COUNT(*) FROM knowledge_document_version WHERE document_id!={args.document};')
            plan = maintain()
            if plan['versions'] != 7 or plan['objects'] != 7 or plan['caches'] != 0:
                raise ValueError('unexpected_qa_plan: ' + json.dumps(plan))
            if not all(path.exists() for path in paths):
                raise ValueError('plan_mutated_originals')

            archive = capture_recovery(mysql[0], root, folder)
            receipt = maintain('--apply', '--recovery-archive', str(archive))
            if receipt != plan | {'status': 'completed'}:
                raise ValueError('apply_differs_from_plan')
            # Metadata changed: an old SQL snapshot must no longer authorize a
            # second destructive operation, even when the next plan is empty.
            maintain('--apply', '--recovery-archive', str(archive), success=False)
            archive = capture_recovery(mysql[0], root, folder / 'second')
            repeat = maintain('--apply', '--recovery-archive', str(archive))
            if any(repeat[key] for key in ('versions', 'tasks', 'objects', 'caches', 'bytes')):
                raise ValueError('maintenance_not_idempotent')
            if before != sql(f'SELECT COUNT(*) FROM knowledge_document_version WHERE document_id!={args.document};'):
                raise ValueError('other_account_versions_changed')
            if sql(f'SELECT GROUP_CONCAT(version_number ORDER BY version_number) FROM knowledge_document_version WHERE document_id={args.document};') != '1,2,10,11':
                raise ValueError('protected_versions_changed')
            if [path.exists() for path in paths] != [True, True, False, False, False, False, False, False, False, True, True]:
                raise ValueError('original_file_sweep_failed')
            print(json.dumps(receipt))
        finally:
            restart_exact(stopped_peers)


if __name__ == '__main__':
    run()
