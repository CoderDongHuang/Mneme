#!/usr/bin/env python3
"""Read-only AWS CLI preflight and observed evidence for regional recovery."""

from __future__ import annotations

import json
import os
import re
import subprocess
from urllib.parse import urlsplit


class CloudPreflightError(RuntimeError):
    pass


def region_arguments() -> list[str]:
    region = os.getenv("BACKUP_RECOVERY_REGION") or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    return ["--region", region] if region else []


def s3_bucket(destination: str) -> str:
    parsed = urlsplit(destination)
    if (
        parsed.scheme != "s3" or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", parsed.netloc)
        or not parsed.path.lstrip("/") or parsed.path.endswith("/")
        or parsed.query or parsed.fragment
    ):
        raise CloudPreflightError("BACKUP_GEO_DESTINATION must be an explicit s3://bucket/object URI")
    return parsed.netloc


def s3_object(uri: str) -> tuple[str, str]:
    """Return a validated bucket/key pair for an object URI."""
    parsed = urlsplit(uri)
    if (
        parsed.scheme != "s3"
        or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", parsed.netloc)
        or not parsed.path.lstrip("/")
        or parsed.path.endswith("/")
        or parsed.query
        or parsed.fragment
    ):
        raise CloudPreflightError("S3 object URI must be an explicit s3://bucket/object")
    return parsed.netloc, parsed.path.lstrip("/")


def kms_key_id(version: str) -> str:
    name = f"BACKUP_KMS_KEY_ID_{version.upper().replace('-', '_')}"
    key = os.getenv(name, "").strip()
    if not key:
        raise CloudPreflightError(f"{name} is required")
    return key


def _aws_json(region: str, *arguments: str, allow_no_policy: bool = False) -> dict:
    try:
        result = subprocess.run(
            ["aws", *arguments, "--region", region, "--output", "json", "--no-cli-pager"],
            capture_output=True, text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CloudPreflightError(f"AWS preflight {arguments[0:2]} failed: {error}") from error
    if result.returncode:
        if allow_no_policy and "(NoSuchBucketPolicy)" in result.stderr:
            return {"PolicyStatus": {"IsPublic": False}, "PolicyAbsent": True}
        raise CloudPreflightError(f"AWS preflight {arguments[0:2]} failed: {result.stderr[-500:]}")
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError) as error:
        raise CloudPreflightError("AWS preflight returned invalid JSON") from error
    if not isinstance(data, dict):
        raise CloudPreflightError("AWS preflight returned a non-object response")
    return data


def preflight(primary_region: str, recovery_region: str, destination: str, version: str) -> dict:
    if not primary_region or not recovery_region or primary_region == recovery_region:
        raise CloudPreflightError("distinct explicit primary and recovery regions are required")
    bucket = s3_bucket(destination)
    identity = _aws_json(recovery_region, "sts", "get-caller-identity")
    if not identity.get("Account") or not identity.get("Arn"):
        raise CloudPreflightError("STS did not return caller identity")
    location = _aws_json(recovery_region, "s3api", "get-bucket-location", "--bucket", bucket)
    if "LocationConstraint" not in location:
        raise CloudPreflightError("S3 did not return bucket location")
    observed_region = location["LocationConstraint"] or "us-east-1"
    if observed_region == "EU":
        observed_region = "eu-west-1"
    if observed_region != recovery_region:
        raise CloudPreflightError("observed S3 bucket region differs from recovery region")
    public = _aws_json(recovery_region, "s3api", "get-public-access-block", "--bucket", bucket)
    block = public.get("PublicAccessBlockConfiguration", {})
    required = ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")
    if not isinstance(block, dict) or any(block.get(name) is not True for name in required):
        raise CloudPreflightError("S3 bucket must enable all four public access blocks")
    policy = _aws_json(recovery_region, "s3api", "get-bucket-policy-status", "--bucket", bucket, allow_no_policy=True)
    policy_status = policy.get("PolicyStatus")
    if not isinstance(policy_status, dict) or policy_status.get("IsPublic") is not False:
        raise CloudPreflightError("S3 bucket policy must be observed as non-public")
    versioning = _aws_json(recovery_region, "s3api", "get-bucket-versioning", "--bucket", bucket)
    if versioning.get("Status") != "Enabled":
        raise CloudPreflightError("S3 bucket versioning must be Enabled")
    key = _aws_json(recovery_region, "kms", "describe-key", "--key-id", kms_key_id(version)).get("KeyMetadata", {})
    if not isinstance(key, dict):
        raise CloudPreflightError("KMS did not return key metadata")
    arn = key.get("Arn", "")
    arn_parts = arn.split(":") if isinstance(arn, str) else []
    if len(arn_parts) < 6 or arn_parts[2] != "kms" or arn_parts[3] != recovery_region:
        raise CloudPreflightError("observed KMS key ARN must be in the recovery region")
    if key.get("Enabled") is not True or key.get("KeyState") != "Enabled":
        raise CloudPreflightError("KMS key must be enabled")
    if key.get("KeyUsage") != "ENCRYPT_DECRYPT" or key.get("KeySpec") != "SYMMETRIC_DEFAULT":
        raise CloudPreflightError("KMS key must be a symmetric encryption key")
    return {
        "status": "passed", "primary_region": primary_region, "recovery_region": recovery_region,
        "caller_identity": identity, "bucket": bucket, "observed_bucket_region": observed_region,
        "public_access_block": block, "bucket_policy_status": policy,
        "bucket_versioning": versioning, "kms_key": key, "key_version": version,
    }
