import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import backup_aws_preflight as cloud


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("BACKUP_KMS_KEY_ID_V1", "alias/recovery")
    replies = {
        "get-caller-identity": {"Account": "123456789012", "Arn": "arn:aws:sts::123456789012:assumed-role/recovery/test"},
        "get-bucket-location": {"LocationConstraint": "eu-west-1"},
        "get-public-access-block": {"PublicAccessBlockConfiguration": {
            name: True for name in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")
        }},
        "get-bucket-policy-status": {"PolicyStatus": {"IsPublic": False}},
        "get-bucket-versioning": {"Status": "Enabled"},
        "describe-key": {"KeyMetadata": {
            "Arn": "arn:aws:kms:eu-west-1:123456789012:key/mrk-test",
            "Enabled": True, "KeyState": "Enabled", "KeyUsage": "ENCRYPT_DECRYPT", "KeySpec": "SYMMETRIC_DEFAULT",
        }},
    }
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[command.index("--region") + 1] == "eu-west-1"
        assert kwargs["timeout"] == 30
        response = replies[command[2]]
        return response if isinstance(response, SimpleNamespace) else SimpleNamespace(returncode=0, stdout=json.dumps(response))

    monkeypatch.setattr(cloud.subprocess, "run", run)
    return replies, calls


def check(primary="us-east-1", secondary="eu-west-1"):
    return cloud.preflight(primary, secondary, "s3://mneme-recovery/drills/backup.tar.gz", "v1")


def test_cloud_preflight_records_observed_resources(aws):
    replies, calls = aws
    evidence = check()
    assert evidence["status"] == "passed"
    assert evidence["observed_bucket_region"] == "eu-west-1"
    assert evidence["kms_key"] == replies["describe-key"]["KeyMetadata"]
    assert evidence["public_access_block"] == replies["get-public-access-block"]["PublicAccessBlockConfiguration"]
    assert len(calls) == 6


@pytest.mark.parametrize("operation,field,value,match", [
    ("get-bucket-location", "LocationConstraint", "us-east-1", "bucket region"),
    ("get-bucket-versioning", "Status", "Suspended", "versioning"),
    ("get-bucket-versioning", "Status", None, "versioning"),
    ("get-bucket-policy-status", "PolicyStatus", {"IsPublic": True}, "non-public"),
    ("get-bucket-policy-status", "PolicyStatus", {}, "non-public"),
    ("get-bucket-policy-status", "PolicyStatus", None, "non-public"),
    ("get-public-access-block", "PublicAccessBlockConfiguration", {}, "four public access"),
    ("get-caller-identity", "Arn", None, "caller identity"),
])
def test_cloud_preflight_fails_closed_on_insecure_or_missing_evidence(aws, operation, field, value, match):
    aws[0][operation][field] = value
    with pytest.raises(cloud.CloudPreflightError, match=match):
        check()


@pytest.mark.parametrize("field,value,match", [
    ("Arn", "arn:aws:kms:us-east-1:123456789012:key/test", "recovery region"),
    ("Enabled", False, "enabled"),
    ("KeyState", "PendingDeletion", "enabled"),
    ("KeyUsage", "SIGN_VERIFY", "symmetric encryption"),
    ("KeySpec", "RSA_2048", "symmetric encryption"),
])
def test_cloud_preflight_rejects_unusable_kms_key(aws, field, value, match):
    aws[0]["describe-key"]["KeyMetadata"][field] = value
    with pytest.raises(cloud.CloudPreflightError, match=match):
        check()


@pytest.mark.parametrize("flag", ["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"])
def test_cloud_requires_each_public_access_block(aws, flag):
    aws[0]["get-public-access-block"]["PublicAccessBlockConfiguration"][flag] = False
    with pytest.raises(cloud.CloudPreflightError, match="four public access"):
        check()


@pytest.mark.parametrize("primary,secondary", [("", "eu-west-1"), ("us-east-1", ""), ("eu-west-1", "eu-west-1")])
def test_cloud_rejects_region_config_before_aws(aws, primary, secondary):
    with pytest.raises(cloud.CloudPreflightError, match="distinct explicit"):
        check(primary, secondary)
    assert not aws[1]


@pytest.mark.parametrize("response,match", [
    (SimpleNamespace(returncode=1, stderr="AccessDenied"), "AccessDenied"),
    (SimpleNamespace(returncode=0, stdout="not-json"), "invalid JSON"),
    (SimpleNamespace(returncode=0, stdout="[]"), "non-object"),
])
def test_cloud_rejects_aws_failures(aws, response, match):
    aws[0]["get-bucket-policy-status"] = response
    with pytest.raises(cloud.CloudPreflightError, match=match):
        check()


def test_cloud_records_absent_policy_only_for_specific_aws_response(aws):
    aws[0]["get-bucket-policy-status"] = SimpleNamespace(returncode=1, stderr="An error occurred (NoSuchBucketPolicy)")
    assert check()["bucket_policy_status"]["PolicyAbsent"] is True


@pytest.mark.parametrize("uri", ["C:/backups/test", "s3://bucket/", "s3://bucket", "s3://bucket/key?x=1", "s3://bucket/key#part", "s3://user@bucket/key"])
def test_cloud_rejects_non_object_destinations(uri):
    with pytest.raises(cloud.CloudPreflightError, match="explicit"):
        cloud.s3_bucket(uri)


def test_s3_object_returns_bucket_and_key():
    assert cloud.s3_object("s3://mneme-recovery/drills/backup.tar.gz") == (
        "mneme-recovery",
        "drills/backup.tar.gz",
    )


@pytest.mark.parametrize("uri", ["s3://bucket/", "s3://bucket", "s3://bucket/key?x=1", "s3://bucket/key#part"])
def test_s3_object_rejects_ambiguous_uri(uri):
    with pytest.raises(cloud.CloudPreflightError, match="object"):
        cloud.s3_object(uri)


def test_cloud_does_not_invent_a_kms_key(aws, monkeypatch):
    monkeypatch.delenv("BACKUP_KMS_KEY_ID_V1")
    with pytest.raises(cloud.CloudPreflightError, match="BACKUP_KMS_KEY_ID_V1"):
        check()


def test_cloud_normalizes_legacy_bucket_region(aws):
    aws[0]["get-bucket-location"]["LocationConstraint"] = "EU"
    assert check()["observed_bucket_region"] == "eu-west-1"


def test_cloud_rejects_missing_key_metadata(aws):
    aws[0]["describe-key"]["KeyMetadata"] = None
    with pytest.raises(cloud.CloudPreflightError, match="metadata"):
        check()


def test_cloud_cli_timeout_is_a_preflight_failure(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("aws", 30)

    monkeypatch.setattr(cloud.subprocess, "run", timeout)
    with pytest.raises(cloud.CloudPreflightError, match="failed"):
        check()
