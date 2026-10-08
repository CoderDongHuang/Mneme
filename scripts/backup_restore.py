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
import shlex
import stat
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
    "payload/data/redis": PROJECT_ROOT / "data" / "redis",
    "payload/data/files": PROJECT_ROOT / "data" / "files",
    "payload/data/avatars": PROJECT_ROOT / "data" / "avatars",
    "payload/data/chroma": PROJECT_ROOT / "data" / "chroma",
    "payload/data/minio": PROJECT_ROOT / "data" / "minio",
    "payload/python-agent/data": PROJECT_ROOT / "python-agent" / "data",
}
ALLOWED_FILE_PREFIXES = tuple(f"{name}/" for name in DATA_SOURCES) + (
    "payload/mysql.sql",
)
APP_SERVICES = ("java-gateway", "python-agent", "chroma", "minio", "redis")
START_ORDER = ("chroma", "minio", "python-agent", "java-gateway")


class BackupError(RuntimeError):
    pass


def split_command(command: str) -> list[str]:
    """Preserve quoted executable paths and backslashes on Windows."""
    if os.name == "nt":
        return [part.strip('"') for part in shlex.split(command, posix=False)]
    return shlex.split(command)


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
        if (encryption is None and not os.getenv("BACKUP_KMS_COMMAND")) or signing is None:
            raise BackupError(
                "BACKUP_REQUIRE_PROTECTION requires BACKUP_KMS_COMMAND (or BACKUP_ENCRYPTION_KEY) and BACKUP_SIGNING_KEY"
            )
    return encryption, signing


def _key_provider(action: str, version: str, value: bytes) -> bytes:
    command = os.getenv("BACKUP_KMS_COMMAND", "").strip()
    if not command:
        raise BackupError("envelope-encrypted backup requires BACKUP_KMS_COMMAND")
    try:
        result = subprocess.run(
            [*split_command(command), action, version],
            input=base64.b64encode(value),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BackupError(f"backup key provider {action} failed: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")[-500:]
        raise BackupError(f"backup key provider {action} failed: {detail}")
    try:
        output = base64.b64decode(result.stdout.strip(), validate=True)
    except ValueError as error:
        raise BackupError(f"backup key provider {action} returned invalid base64") from error
    if not output:
        raise BackupError(f"backup key provider {action} returned an empty key")
    return output


def _versioned_secret(name: str, version: str | None) -> str | None:
    """Prefer the archive key version, then fall back to the active key."""
    if version:
        candidate = os.getenv(f"{name}_{version.upper().replace('-', '_')}")
        if candidate:
            return candidate
    return os.getenv(name)


def _security_keys_for_version(
    version: str | None,
    encryption_key: str | bytes | None = None,
    signing_key: str | bytes | None = None,
) -> tuple[bytes | None, bytes | None]:
    if encryption_key is not None or signing_key is not None:
        return _security_keys(encryption_key, signing_key)
    return _security_keys(
        _versioned_secret("BACKUP_ENCRYPTION_KEY", version),
        _versioned_secret("BACKUP_SIGNING_KEY", version),
    )


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
    provider_command = os.getenv("BACKUP_KMS_COMMAND", "").strip()
    use_envelope = bool(provider_command and encryption_key is None)
    data_key = os.urandom(32) if use_envelope else encryption_secret
    key_version = os.getenv("BACKUP_KEY_VERSION", "v1")
    wrapped_data_key = _key_provider("wrap", key_version, data_key) if use_envelope else None
    payload = staging / "payload"
    if not (payload / "mysql.sql").is_file():
        raise BackupError("backup payload is missing mysql.sql")
    files = []
    for path in sorted(item for item in payload.rglob("*") if item.is_file()):
        relative = path.relative_to(staging).as_posix()
        if not relative.startswith(ALLOWED_FILE_PREFIXES):
            raise BackupError(f"backup payload contains an unsupported file: {relative}")
        plaintext_digest = sha256_file(path)
        if data_key:
            plaintext = path.read_bytes()
            nonce = os.urandom(12)
            ciphertext = AESGCM(data_key).encrypt(
                nonce, plaintext, relative.encode()
            )
            path.write_bytes(nonce + ciphertext)
        files.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
                **({"plaintext_sha256": plaintext_digest} if data_key else {}),
            }
        )
    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "created_at": utc_now(),
        "files": files,
        "metadata": metadata or {},
        "security": {
            "encrypted": data_key is not None,
            "signed": signing_secret is not None,
            "key_version": key_version,
            **(
                {
                    "envelope_encrypted": True,
                    "key_provider": os.getenv("BACKUP_KEY_PROVIDER", "external-command"),
                    "wrapped_data_key": base64.b64encode(wrapped_data_key).decode("ascii"),
                }
                if wrapped_data_key is not None
                else {"envelope_encrypted": False}
            ),
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
    name = member.name.rstrip("/") if member.isdir() else member.name
    path = PurePosixPath(name)
    parts = name.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789\u00b9\u00b2\u00b3")
    if (
        not name or path.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or any(character in name for character in '\\<>:"|?*')
        or any(ord(character) < 32 for character in name)
        or any(part.endswith((".", " ")) for part in parts)
        or any(part.split(".", 1)[0].upper() in reserved for part in parts)
    ):
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
            if os.getenv("BACKUP_REQUIRE_PROTECTION", "false").lower() in {"1", "true", "yes", "on"}:
                if not security.get("encrypted") or not security.get("signed"):
                    raise BackupError("protected restore requires an encrypted and signed backup")
            if security.get("envelope_encrypted") and not security.get("encrypted"):
                raise BackupError("envelope-encrypted backup must declare encrypted payload")
            if security.get("envelope_encrypted"):
                wrapped = security.get("wrapped_data_key")
                if (
                    not isinstance(wrapped, str) or not wrapped
                    or not isinstance(security.get("key_version"), str) or not security["key_version"]
                    or not security.get("key_provider")
                ):
                    raise BackupError("envelope-encrypted backup has invalid key metadata")
                try:
                    base64.b64decode(wrapped, validate=True)
                except ValueError as error:
                    raise BackupError("wrapped data key is invalid") from error
            if security.get("signed"):
                _, signing_secret = _security_keys_for_version(security.get("key_version"))
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
                _validated_name(tarfile.TarInfo(name))
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


def _empty_isolated_destination(destination: Path) -> Path:
    destination = destination.absolute()
    # Check ancestors before resolving: resolution would hide existing links/junctions.
    for path in (*reversed(destination.parents), destination):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise BackupError(f"restore destination has a symlink or reparse point: {path}")
        if not stat.S_ISDIR(info.st_mode):
            raise BackupError(f"restore destination is not a directory: {path}")
    if destination.exists() and any(destination.iterdir()):
        raise BackupError("restore destination must be an empty isolated directory")
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def extract_verified(archive: Path, destination: Path) -> dict:
    manifest = verify_archive(archive)
    destination = _empty_isolated_destination(destination)
    security = manifest.get("security", {})
    encryption_secret = None
    if security.get("encrypted"):
        if security.get("envelope_encrypted"):
            wrapped = base64.b64decode(security["wrapped_data_key"], validate=True)
            encryption_secret = _key_provider("unwrap", security["key_version"], wrapped)
            if len(encryption_secret) != 32:
                raise BackupError("backup key provider returned a data key with invalid length")
        else:
            encryption_secret, _ = _security_keys_for_version(security.get("key_version"))
        if encryption_secret is None:
            raise BackupError("encrypted backup requires BACKUP_ENCRYPTION_KEY")
    with tarfile.open(archive, "r:gz") as bundle:
        for entry in manifest["files"]:
            name = entry["path"]
            target = destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = bundle.extractfile(bundle.getmember(name))
            if stream is None:
                raise BackupError(f"archive file cannot be read: {name}")
            data = stream.read()
            if security.get("encrypted"):
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
            with target.open("xb") as output:
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
