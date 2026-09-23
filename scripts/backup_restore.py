#!/usr/bin/env python3
"""Versioned, checksummed backup and restore utility for Mneme."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from dotenv import load_dotenv


FORMAT = "mneme-backup"
VERSION = 2
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
DATA_SOURCES = {
    "payload/data/files": PROJECT_ROOT / "data" / "files",
    "payload/data/avatars": PROJECT_ROOT / "data" / "avatars",
    "payload/data/chroma": PROJECT_ROOT / "data" / "chroma",
    "payload/data/minio": PROJECT_ROOT / "data" / "minio",
    "payload/python-agent/data": PROJECT_ROOT / "python-agent" / "data",
}
ALLOWED_FILE_PREFIXES = tuple(f"{name}/" for name in DATA_SOURCES) + (
    "payload/mysql.sql",
)
APP_SERVICES = ("java-gateway", "python-agent", "chroma", "minio")
START_ORDER = ("chroma", "minio", "python-agent", "java-gateway")


class BackupError(RuntimeError):
    pass


def _secret_bytes(value: str | bytes | None, name: str) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        raw = value
    else:
        value = value.strip()
        if not value:
            return None
        try:
            raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        except ValueError:
            raw = value.encode("utf-8")
    if len(raw) < 16:
        raise BackupError(f"{name} must contain at least 16 bytes")
    return hashlib.sha256(raw).digest()


def _security_keys(
    encryption_key: str | bytes | None = None,
    signing_key: str | bytes | None = None,
) -> tuple[bytes | None, bytes | None]:
    encryption = _secret_bytes(
        encryption_key if encryption_key is not None else os.getenv("BACKUP_ENCRYPTION_KEY"),
        "BACKUP_ENCRYPTION_KEY",
    )
    signing = _secret_bytes(
        signing_key if signing_key is not None else os.getenv("BACKUP_SIGNING_KEY"),
        "BACKUP_SIGNING_KEY",
    )
    if os.getenv("BACKUP_REQUIRE_PROTECTION", "false").lower() in {"1", "true", "yes", "on"}:
        if encryption is None or signing is None:
            raise BackupError(
                "BACKUP_REQUIRE_PROTECTION requires BACKUP_ENCRYPTION_KEY and BACKUP_SIGNING_KEY"
            )
    return encryption, signing


def _signed_manifest(manifest: dict) -> bytes:
    copy = json.loads(json.dumps(manifest))
    security = copy.get("security", {})
    security.pop("signature", None)
    copy["security"] = security
    return json.dumps(copy, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return sha256_stream(stream)


def compose_command(compose_files: list[str], *args: str) -> list[str]:
    command = ["docker", "compose"]
    for compose_file in compose_files:
        command.extend(("-f", compose_file))
    return [*command, *args]


def run_compose(
    compose_files: list[str],
    *args: str,
    check: bool = True,
    input_data: bytes | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        compose_command(compose_files, *args),
        cwd=PROJECT_ROOT,
        check=check,
        input=input_data,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def compose_services(compose_files: list[str]) -> set[str]:
    result = run_compose(compose_files, "config", "--services", capture=True)
    return set(result.stdout.decode().splitlines())


def stop_application_services(compose_files: list[str]) -> None:
    available = compose_services(compose_files)
    for service in APP_SERVICES:
        if service in available:
            run_compose(compose_files, "stop", service)


def start_application_services(compose_files: list[str]) -> None:
    run_compose(compose_files, "up", "-d", "mysql", "redis")
    available = compose_services(compose_files)
    for service in START_ORDER:
        if service in available:
            run_compose(compose_files, "up", "-d", service)


def copy_tree(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, copy_function=shutil.copy2)


def create_archive(
    staging: Path,
    archive: Path,
    metadata: dict | None = None,
    encryption_key: str | bytes | None = None,
    signing_key: str | bytes | None = None,
) -> dict:
    encryption_secret, signing_secret = _security_keys(encryption_key, signing_key)
    payload = staging / "payload"
    if not (payload / "mysql.sql").is_file():
        raise BackupError("backup payload is missing mysql.sql")
    files = []
    for path in sorted(item for item in payload.rglob("*") if item.is_file()):
        relative = path.relative_to(staging).as_posix()
        if not relative.startswith(ALLOWED_FILE_PREFIXES):
            raise BackupError(f"backup payload contains an unsupported file: {relative}")
        plaintext_digest = sha256_file(path)
        if encryption_secret:
            plaintext = path.read_bytes()
            nonce = os.urandom(12)
            ciphertext = AESGCM(encryption_secret).encrypt(
                nonce, plaintext, relative.encode()
            )
            path.write_bytes(nonce + ciphertext)
        files.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
                **({"plaintext_sha256": plaintext_digest} if encryption_secret else {}),
            }
        )
    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "created_at": utc_now(),
        "files": files,
        "metadata": metadata or {},
        "security": {
            "encrypted": encryption_secret is not None,
            "signed": signing_secret is not None,
            "key_version": os.getenv("BACKUP_KEY_VERSION", "v1"),
        },
    }
    if signing_secret:
        manifest["security"]["signature"] = hmac.new(
            signing_secret, _signed_manifest(manifest), hashlib.sha256
        ).hexdigest()
    manifest_path = staging / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as bundle:
        bundle.add(manifest_path, arcname="manifest.json", recursive=False)
        bundle.add(payload, arcname="payload", recursive=True)
    return manifest


def _validated_name(member: tarfile.TarInfo) -> str:
    name = member.name.replace("\\", "/")
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts:
        raise BackupError(f"unsafe archive path: {member.name}")
    if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
        raise BackupError(f"unsupported archive member: {member.name}")
    return path.as_posix().rstrip("/")


def verify_archive(archive: Path) -> dict:
    if not archive.is_file():
        raise BackupError(f"backup archive does not exist: {archive}")
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members: dict[str, tarfile.TarInfo] = {}
            for member in bundle.getmembers():
                name = _validated_name(member)
                if name in members:
                    raise BackupError(f"duplicate archive member: {name}")
                members[name] = member
            manifest_member = members.get("manifest.json")
            if manifest_member is None or not manifest_member.isfile():
                raise BackupError("backup manifest is missing")
            manifest_stream = bundle.extractfile(manifest_member)
            if manifest_stream is None:
                raise BackupError("backup manifest cannot be read")
            manifest = json.load(manifest_stream)
            if manifest.get("format") != FORMAT or manifest.get("version") not in {1, VERSION}:
                raise BackupError("unsupported backup format or version")
            security = manifest.get("security", {}) if manifest.get("version") >= 2 else {}
            if security.get("signed"):
                _, signing_secret = _security_keys(signing_key=os.getenv("BACKUP_SIGNING_KEY"))
                signature = security.get("signature")
                if not signing_secret or not isinstance(signature, str):
                    raise BackupError("signed backup requires BACKUP_SIGNING_KEY")
                expected = hmac.new(
                    signing_secret, _signed_manifest(manifest), hashlib.sha256
                ).hexdigest()
                if not hmac.compare_digest(signature, expected):
                    raise BackupError("backup manifest signature mismatch")
            entries = manifest.get("files")
            if not isinstance(entries, list) or not entries:
                raise BackupError("backup manifest has no file inventory")
            declared: dict[str, dict] = {}
            for entry in entries:
                if not isinstance(entry, dict):
                    raise BackupError("invalid backup manifest entry")
                name = str(entry.get("path", ""))
                if name in declared:
                    raise BackupError(f"duplicate manifest entry: {name}")
                if not name.startswith(ALLOWED_FILE_PREFIXES):
                    raise BackupError(f"manifest contains an unsupported file: {name}")
                declared[name] = entry
            if "payload/mysql.sql" not in declared:
                raise BackupError("backup manifest is missing mysql.sql")
            actual = {name for name, member in members.items() if member.isfile()}
            actual.discard("manifest.json")
            if actual != set(declared):
                missing = sorted(set(declared) - actual)
                unknown = sorted(actual - set(declared))
                raise BackupError(f"archive inventory mismatch; missing={missing}, unknown={unknown}")
            for name, entry in declared.items():
                member = members[name]
                stream = bundle.extractfile(member)
                if stream is None:
                    raise BackupError(f"archive file cannot be read: {name}")
                digest = sha256_stream(stream)
                if member.size != entry.get("size") or digest != entry.get("sha256"):
                    raise BackupError(f"checksum or size mismatch: {name}")
            return manifest
    except (tarfile.TarError, json.JSONDecodeError, OSError) as error:
        raise BackupError(f"invalid backup archive: {error}") from error


def extract_verified(archive: Path, destination: Path) -> dict:
    manifest = verify_archive(archive)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as bundle:
        for entry in manifest["files"]:
            name = entry["path"]
            target = destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = bundle.extractfile(bundle.getmember(name))
            if stream is None:
                raise BackupError(f"archive file cannot be read: {name}")
            data = stream.read()
            if manifest.get("security", {}).get("encrypted"):
                encryption_secret, _ = _security_keys()
                if encryption_secret is None:
                    raise BackupError("encrypted backup requires BACKUP_ENCRYPTION_KEY")
                if len(data) < 12:
                    raise BackupError(f"encrypted archive file is truncated: {name}")
                try:
                    data = AESGCM(encryption_secret).decrypt(
                        data[:12], data[12:], name.encode()
                    )
                except InvalidTag as error:
                    raise BackupError(f"backup decryption authentication failed: {name}") from error
                if sha256_stream(io.BytesIO(data)) != entry.get("plaintext_sha256"):
                    raise BackupError(f"plaintext checksum mismatch: {name}")
            with target.open("wb") as output:
                output.write(data)
    return manifest


def backup(args: argparse.Namespace) -> int:
    started = time.monotonic()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = Path(args.output_dir).resolve() / f"mneme-{stamp}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="mneme-backup-") as temporary:
        staging = Path(temporary)
        payload = staging / "payload"
        payload.mkdir(parents=True)
        stop_application_services(args.compose_file)
        try:
            dump = run_compose(
                args.compose_file, "exec", "-T", "mysql", "sh", "-c",
                'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --events "$MYSQL_DATABASE"',
                capture=True,
            )
            (payload / "mysql.sql").write_bytes(dump.stdout)
            for archive_path, source in DATA_SOURCES.items():
                copy_tree(source, staging / archive_path)
            manifest = create_archive(
                staging, archive, {"backup_duration_seconds": round(time.monotonic() - started, 3)}
            )
        finally:
            start_application_services(args.compose_file)
    verify_archive(archive)
    print(json.dumps({"archive": str(archive), "created_at": manifest["created_at"]}))
    return 0


def replace_data_directories(extracted: Path) -> None:
    for archive_path, destination in DATA_SOURCES.items():
        source = extracted / archive_path
        if destination.exists():
            shutil.rmtree(destination)
        if source.is_dir():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination, copy_function=shutil.copy2)


def wait_for_mysql(compose_files: list[str], timeout: int = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = run_compose(
            compose_files, "exec", "-T", "mysql", "sh", "-c",
            'mysqladmin ping -h localhost -uroot -p"$MYSQL_ROOT_PASSWORD" --silent',
            check=False, capture=True,
        )
        if result.returncode == 0:
            return
        time.sleep(2)
    raise BackupError("MySQL did not become ready before restore timeout")


def restore(args: argparse.Namespace) -> int:
    if not args.yes:
        raise BackupError("restore overwrites current data; pass --yes to confirm")
    archive = Path(args.archive).resolve()
    manifest = verify_archive(archive)
    started = time.monotonic()
    stop_application_services(args.compose_file)
    try:
        with tempfile.TemporaryDirectory(prefix="mneme-restore-") as temporary:
            extracted = Path(temporary)
            extract_verified(archive, extracted)
            run_compose(args.compose_file, "up", "-d", "mysql")
            wait_for_mysql(args.compose_file)
            run_compose(
                args.compose_file, "exec", "-T", "mysql", "sh", "-c",
                r'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "DROP DATABASE IF EXISTS \`$MYSQL_DATABASE\`; CREATE DATABASE \`$MYSQL_DATABASE\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"',
            )
            sql = (extracted / "payload" / "mysql.sql").read_bytes()
            run_compose(
                args.compose_file, "exec", "-T", "mysql", "sh", "-c",
                'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"', input_data=sql,
            )
            replace_data_directories(extracted)
    finally:
        start_application_services(args.compose_file)
    finished = datetime.now(timezone.utc)
    created = datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
    report = {
        "archive": str(archive),
        "restored_at": finished.isoformat().replace("+00:00", "Z"),
        "rpo_seconds": round((finished - created).total_seconds(), 3),
        "rto_seconds": round(time.monotonic() - started, 3),
        "status": "completed",
    }
    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-file", action="append", default=[])
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--output-dir", default="backups")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("archive")
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("archive")
    restore_parser.add_argument("--yes", action="store_true")
    restore_parser.add_argument("--report", default="backups/last-restore-report.json")
    args = parser.parse_args(argv)
    if not args.compose_file:
        args.compose_file = ["docker-compose.yml"]
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "backup":
        return backup(args)
    if args.command == "verify":
        print(json.dumps(verify_archive(Path(args.archive).resolve()), ensure_ascii=False, indent=2))
        return 0
    if args.command == "restore":
        return restore(args)
    raise BackupError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BackupError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
