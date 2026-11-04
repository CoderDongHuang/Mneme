"""Plan/apply SQLite compaction using the deployed image and its exact data mounts."""
import argparse
import json
from pathlib import PurePosixPath
import subprocess
import sys


PATHS = {
    'lexical': ('LEXICAL_INDEX_PATH', '/app/data/lexical-index.sqlite3'),
    'generations': ('INDEX_GENERATION_PATH', '/app/data/index-generations.sqlite3'),
    'memory_versions': ('MEMORY_VERSION_STORE_PATH', '/app/data/memory_versions.sqlite3'),
    'traces': ('AGENT_TRACE_STORE_PATH', '/app/data/agent_traces.sqlite3'),
}


def docker(*args, input=None):
    response = subprocess.run(['docker', *args], input=input, capture_output=True, text=True, encoding='utf-8')
    if response.returncode:
        raise RuntimeError('docker_operation_failed')
    return response.stdout


def config(info):
    labels = info['Config'].get('Labels') or {}
    if labels.get('com.docker.compose.service') != 'python-agent':
        raise ValueError('target_is_not_compose_python_agent')
    project = labels.get('com.docker.compose.project')
    if not project:
        raise ValueError('compose_project_missing')
    env = dict(value.split('=', 1) for value in info['Config']['Env'])
    stores = {name: env.get(key, default) for name, (key, default) in PATHS.items()}
    stores['privacy'] = str(PurePosixPath(stores['traces']).with_name('privacy.sqlite3'))
    backend = env.get('AUXILIARY_STORE_BACKEND', 'sqlite')
    if backend not in ('sqlite', 'mysql'):
        raise ValueError('unknown_auxiliary_backend')
    if backend == 'mysql':
        stores = {'lexical': stores['lexical']}
    roots = [mount['Destination'] for mount in info['Mounts'] if mount['RW']]
    for path in stores.values():
        p = PurePosixPath(path)
        mounts = [mount for mount in info['Mounts'] if p.is_relative_to(mount['Destination'])]
        if (not p.is_absolute() or '..' in p.parts or not mounts
                or not max(mounts, key=lambda mount: len(mount['Destination']))['RW']):
            raise ValueError('store_not_in_writable_mount')
    if len(set(stores.values())) != len(stores):
        raise ValueError('store_paths_overlap')
    return project, {'stores': stores, 'roots': roots}


def source_path(value):
    normalized = value.replace('\\', '/')
    # Windows bind sources are case-insensitive; Linux volumes and binds are not.
    if len(normalized) > 1 and normalized[1] == ':':
        normalized = normalized.casefold()
    return PurePosixPath(normalized)


def mounted_paths(info, stores):
    paths = []
    for value in stores.values():
        path = PurePosixPath(value)
        mounts = [m for m in info['Mounts'] if path.is_relative_to(m['Destination'])]
        mount = max(mounts, key=lambda m: len(m['Destination']))
        paths.append(source_path(mount['Source']) / path.relative_to(mount['Destination']))
    return paths


def stopped_writers(project, target, containers, stores):
    paths = mounted_paths(target, stores)
    # Do not compact a stopped rollback container's data while its replacement runs.
    for peer in containers:
        if not peer['State']['Running']:
            continue
        labels = peer['Config'].get('Labels') or {}
        if labels.get('com.docker.compose.project') == project and labels.get('com.docker.compose.service') in ('java-gateway', 'python-agent'):
            raise ValueError('stop_all_gateway_and_agent_replicas')
        # Also reject a foreign container mounted over the SQLite data directory.
        for mount in peer.get('Mounts', []):
            source = source_path(mount['Source'])
            if any(path.is_relative_to(source) or source.is_relative_to(path) for path in paths):
                raise ValueError('another_container_has_sqlite_mount')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', default='mneme-python-agent-1')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        info = json.loads(docker('inspect', args.container))[0]
        project, data = config(info)
        if not args.apply:
            print(json.dumps({'status': 'planned', 'stores': list(data['stores']),
                              'requires': 'stop all Gateway/Agent replicas; use a verified recovery set'}))
            return 0
        ids = docker('ps', '-q').split()
        stopped_writers(project, info, json.loads(docker('inspect', *ids)) if ids else [], data['stores'])
        result = subprocess.run(['docker', 'run', '--rm', '-i', '--network', 'none', '--read-only',
                                 '--tmpfs', '/tmp', '--volumes-from', info['Id'], '--entrypoint', 'python',
                                 info['Image'], '-m', 'app.storage.sqlite_maintenance', '--apply', '--offline'],
                                input=json.dumps(data), capture_output=True, text=True, encoding='utf-8')
        # Print only the worker's structured, content-free receipt.
        receipt = json.loads(result.stdout)
        print(json.dumps(receipt))
        return 0 if result.returncode == 0 and receipt.get('status') == 'completed' else 1
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError):
        print('FAIL: maintenance unavailable; verify stopped writers, image, paths and storage', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
