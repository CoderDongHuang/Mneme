"""Plan offline document/version/cache retention against the actual deployed Gateway.

Apply requires stopped writers and a verified SQL/original-file recovery archive.
External reference-only backups must supply pinned_locations in the policy file.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile

try:
    from .maintain_sqlite import docker, mounted_paths, source_path, stopped_writers
except ImportError:
    from maintain_sqlite import docker, mounted_paths, source_path, stopped_writers


ENVIRONMENT = frozenset({
    'SPRING_DATASOURCE_URL', 'SPRING_DATASOURCE_USERNAME', 'SPRING_DATASOURCE_PASSWORD',
    'FILE_STORAGE_PATH', 'STORAGE_BACKEND', 'OBJECT_STORAGE_ENDPOINT',
    'OBJECT_STORAGE_ACCESS_KEY', 'OBJECT_STORAGE_SECRET_KEY', 'OBJECT_STORAGE_BUCKET',
})
DEFAULT_POLICY = {'versions': 10, 'version_days': 30, 'task_days': 30,
                  'orphan_hours': 24, 'cache_hours': 24, 'cache_bytes': 1073741824,
                  'pinned_locations': []}


def policy_file(path):
    value = json.loads(Path(path).read_text(encoding='utf-8')) if path else {}
    if not isinstance(value, dict) or set(value) - DEFAULT_POLICY.keys():
        raise ValueError('invalid_policy')
    policy = DEFAULT_POLICY | value
    for key, number in policy.items():
        if key == 'pinned_locations':
            if not isinstance(number, list) or any(not isinstance(p, str) or not p.strip() for p in number):
                raise ValueError('invalid_pins')
        elif type(number) is not int or number < (0 if key == 'cache_bytes' else 1):
            raise ValueError('invalid_policy')
    return policy


def target_config(info):
    labels = info['Config'].get('Labels') or {}
    project = labels.get('com.docker.compose.project')
    if not project or labels.get('com.docker.compose.service') != 'java-gateway':
        raise ValueError('target_is_not_compose_gateway')
    env = dict(value.split('=', 1) for value in info['Config']['Env'])
    env = {key: value for key, value in env.items() if key in ENVIRONMENT}
    # Require explicit deployed settings; guessing defaults risks another database.
    if not env.get('SPRING_DATASOURCE_URL') or not env.get('SPRING_DATASOURCE_PASSWORD'):
        raise ValueError('explicit_database_configuration_required')
    path = PurePosixPath(env.get('FILE_STORAGE_PATH', ''))
    mounts = [m for m in info['Mounts'] if path.is_relative_to(m['Destination'])]
    if (not path.is_absolute() or '..' in path.parts or not mounts
            or not max(mounts, key=lambda m: len(m['Destination']))['RW']):
        raise ValueError('storage_not_in_writable_mount')
    networks = info['NetworkSettings']['Networks']
    matching = [name for name in networks if name == project + '_default']
    if len(networks) == 1:
        network = next(iter(networks))
    elif len(matching) == 1:
        network = matching[0]
    else:
        raise ValueError('ambiguous_gateway_network')
    return project, env, {'files': str(path)}, network


def check_writers(project, target, containers, stores, env):
    stopped_writers(project, target, containers, stores)
    # A foreign S3 writer has no shared local mount; compare remote destinations too.
    if env.get('STORAGE_BACKEND', 'local').lower() == 's3':
        endpoint = env.get('OBJECT_STORAGE_ENDPOINT', '').rstrip('/')
        bucket = env.get('OBJECT_STORAGE_BUCKET', 'mneme')
        for peer in containers:
            if not peer['State']['Running']:
                continue
            other = dict(item.split('=', 1) for item in peer['Config'].get('Env', []))
            if (other.get('STORAGE_BACKEND', '').lower() == 's3'
                    and other.get('OBJECT_STORAGE_ENDPOINT', '').rstrip('/') == endpoint
                    and other.get('OBJECT_STORAGE_BUCKET', 'mneme') == bucket):
                raise ValueError('another_object_storage_writer')


def execute(info, env, network, policy, apply):
    command = ['docker', 'run', '--rm', '-i', '--read-only', '--tmpfs', '/tmp',
               '--network', network, '--volumes-from', info['Id'] + ('' if apply else ':ro'),
               '--workdir', info['Config'].get('WorkingDir') or '/app']
    for name in sorted(env):
        command.extend(['--env', name])  # Secret values never appear in argv.
    command += ['--entrypoint', 'java', info['Image'],
                '-Dloader.main=com.mneme.maintenance.RetentionMain', '-cp', '/app/app.jar',
                'org.springframework.boot.loader.launch.PropertiesLauncher']
    if apply:
        command += ['--apply', '--offline']
    result = subprocess.run(command, input=json.dumps(policy), env=os.environ | env,
                            capture_output=True, text=True, encoding='utf-8')
    receipt = json.loads(result.stdout)
    expected = {'status', 'versions', 'tasks', 'objects', 'caches', 'bytes'}
    if (result.returncode or not isinstance(receipt, dict) or set(receipt) != expected
            or receipt['status'] != ('completed' if apply else 'planned')
            or any(type(receipt[key]) is not int or receipt[key] < 0 for key in expected - {'status'})):
        raise ValueError('maintenance_failed')
    return receipt


def verify_recovery(backup, archive, info, env, stores):
    # Remote objects are not included in an ordinary host file archive. Do not
    # mistake a valid SQL archive for proof that S3 originals can be recovered.
    if env.get('STORAGE_BACKEND', 'local').lower() != 'local':
        raise ValueError('remote_recovery_coverage_not_verified')
    root = backup.DATA_SOURCES['payload/data/files']
    if mounted_paths(info, stores) != [source_path(str(root))]:
        raise ValueError('backup_does_not_cover_deployed_storage')
    manifest = backup.verify_archive(archive)
    backup.validate_restore_schema(manifest)
    entries = {entry['path']: entry for entry in manifest['files']}
    # Authenticate/decrypt only SQL, without extracting unrelated vector stores.
    with tempfile.TemporaryDirectory(prefix='mneme-retention-sql-') as directory:
        destination = Path(directory) / 'verified'
        backup.extract_verified(archive, destination, selected_paths={'payload/mysql.sql'})
        archived_sql = (destination / 'payload/mysql.sql').read_bytes()
    if normalized_dump(archived_sql) != normalized_dump(current_sql(info, env)):
        raise ValueError('backup_database_is_not_current')
    encrypted = manifest.get('security', {}).get('encrypted', False)
    if not root.is_dir():
        raise ValueError('storage_directory_missing')
    for parent in (*reversed(root.parents), root):
        attributes = parent.lstat()
        if (stat.S_ISLNK(attributes.st_mode)
                or getattr(attributes, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError('unsafe_storage_link')
    # Hash every managed original while writers are stopped. A stale or partial
    # archive must not authorize deletion, even if its own checksums are valid.
    for path in root.rglob('*'):
        attributes = path.lstat()
        if (stat.S_ISLNK(attributes.st_mode)
                or getattr(attributes, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError('unsafe_storage_link')
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if not re.fullmatch(r'[1-9][0-9]*/[1-9][0-9]*/[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}-.+', relative):
            continue
        entry = entries.get('payload/data/files/' + relative)
        with path.open('rb') as stream:
            hasher = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                hasher.update(chunk)
            digest = hasher.hexdigest()
        # AES-GCM adds nonce/tag bytes; compare the signed plaintext digest.
        if (not entry or entry.get('plaintext_sha256' if encrypted else 'sha256') != digest
                or (not encrypted and entry['size'] != attributes.st_size)):
            raise ValueError('backup_missing_current_original')


def normalized_dump(value):
    # mysqldump's completion clock is not application state. Everything else,
    # including table data, DDL, routines and events, must match byte for byte.
    return re.sub(rb'^-- Dump completed on [^\r\n]*(?:\r?\n|$)', b'', value, flags=re.MULTILINE)


def current_sql(info, env):
    match = re.fullmatch(r'jdbc:mysql://([^/:?]+)(?::3306)?/([A-Za-z0-9_]+)(?:\?.*)?', env['SPRING_DATASOURCE_URL'])
    if not match:
        raise ValueError('database_recovery_target_unverified')
    hostname, database = match.groups()
    project = info['Config']['Labels']['com.docker.compose.project']
    ids = docker('ps', '--filter', f'label=com.docker.compose.project={project}',
                 '--filter', 'label=com.docker.compose.service=mysql', '-q').split()
    if len(ids) != 1:
        raise ValueError('database_recovery_target_unverified')
    mysql = json.loads(docker('inspect', ids[0]))[0]
    mysql_env = dict(item.split('=', 1) for item in mysql['Config'].get('Env', []))
    shared_networks = set(info['NetworkSettings']['Networks']) & set(mysql['NetworkSettings']['Networks'])
    if (mysql_env.get('MYSQL_DATABASE') != database or not any(
            hostname in (mysql['NetworkSettings']['Networks'][network].get('Aliases') or [])
            for network in shared_networks)):
        raise ValueError('database_recovery_target_unverified')
    result = subprocess.run(['docker', 'exec', '-i', mysql['Id'], 'sh', '-c',
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --routines --events "$MYSQL_DATABASE"'],
        capture_output=True, check=True)
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', default='mneme-java-gateway-1')
    parser.add_argument('--policy', help='JSON policy with explicit pins for reference-only backups')
    parser.add_argument('--recovery-archive', help='Verified archive covering SQL and every original; required for apply')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        try:
            from . import backup_restore
        except ImportError:
            import backup_restore
        with backup_restore.operation_lock():
            policy = policy_file(args.policy)
            info = json.loads(docker('inspect', args.container))[0]
            project, env, stores, network = target_config(info)
            if args.apply:
                if not args.recovery_archive:
                    raise ValueError('verified_recovery_archive_required')
                ids = docker('ps', '-q').split()
                peers = json.loads(docker('inspect', *ids)) if ids else []
                check_writers(project, info, peers, stores, env)
                verify_recovery(backup_restore, Path(args.recovery_archive), info, env, stores)
            # Always recompute candidates. A previous plan is never executable input.
            print(json.dumps(execute(info, env, network, policy, args.apply)))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, IndexError, TypeError, subprocess.SubprocessError):
        print('FAIL: retention unavailable; verify stopped writers, recovery archive, policy and deployed image', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
