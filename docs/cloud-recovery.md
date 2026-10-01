# AWS envelope and geo recovery

`scripts/backup_geo_recovery_drill.py` supports two independent selections:
the data source (`controlled-synthetic` by default, or `actual-archive` with
`--archive`) and the transport (isolated local copy, configured remote commands,
or strict AWS with `--require-cloud`). The JSON report labels both selections.
An AWS run over synthetic data validates the cloud path with a controlled
fixture. It does not establish recovery of production data.

## Archive recovery

Supply a local Mneme `.tar.gz` backup and the original signing key plus an
envelope key provider capable of unwrapping its data key. No archive-mode key
defaults are installed. Version-specific `BACKUP_SIGNING_KEY_<VERSION>` takes
precedence over `BACKUP_SIGNING_KEY` (uppercase, hyphens replaced with underscores).
The signed manifest's key version selects the provider key, regardless of the
currently active `BACKUP_KEY_VERSION`.

```powershell
.venv\Scripts\python.exe scripts\backup_geo_recovery_drill.py --archive D:\backups\mneme-backup.tar.gz --report artifacts\archive-recovery.json
```

Recovery requires a signed, encrypted **envelope** archive. Signature, inventory,
ciphertext digests, fetched archive digest, AES-GCM authentication and every
plaintext digest must pass. Restored files live in a private temporary directory
and are removed after verification. The input archive is copied, never edited.
The report records every restored file's path and plaintext digest, plus counts
and archive hashes. It never includes keys, ciphertext key material or plaintext.

## Strict AWS configuration

Set these explicitly; cloud runs never install local providers or fallback secrets:

| Configuration | Requirement |
| --- | --- |
| `BACKUP_PRIMARY_REGION` | Operator-declared source region |
| `BACKUP_RECOVERY_REGION` | Distinct secondary region used explicitly by every AWS adapter |
| `BACKUP_GEO_DESTINATION` or `--destination` | Exact `s3://bucket/object` recovery destination |
| `BACKUP_KEY_VERSION` | Required for synthetic creation; archive recovery uses the signed archive version |
| `BACKUP_KMS_KEY_ID_<VERSION>` | Key ID/ARN or alias resolvable in the secondary region |
| `BACKUP_SIGNING_KEY` or version-specific signing key | Real configured signing secret matching the archive |

```powershell
.venv\Scripts\python.exe scripts\backup_geo_recovery_drill.py --require-cloud --archive D:\backups\mneme-backup.tar.gz --report artifacts\aws-recovery.json
```

`--require-cloud` implies remote copy/readback/fetch verification and uses the
bundled AWS adapters. Custom `BACKUP_GEO_COPY_COMMAND`, `BACKUP_GEO_VERIFY_COMMAND`
and `BACKUP_GEO_FETCH_COMMAND` overrides are rejected in this mode.
AWS CLI credentials must already be available. The read-only preflight records
observed STS caller identity, bucket region, all four bucket public access block
flags, non-public bucket policy status and `Enabled` versioning. An absent bucket
policy is accepted only on the specific AWS `NoSuchBucketPolicy` response.
Missing configuration, access denial, malformed responses, suspended versioning
or a regional mismatch fail closed. KMS `describe-key` must observe an enabled
`SYMMETRIC_DEFAULT` key with `ENCRYPT_DECRYPT` usage and an ARN in the recovery
region. Successful wrapping/unwrapping proves operational key permissions;
`describe-key` alone does not.
The observed KMS key ARN is pinned for subsequent wrapping/unwrapping, so a
configured alias cannot change the key selected between preflight and recovery.

A primary-region single-region KMS ciphertext cannot simply move to a different
key in another region. Actual archive recovery needs the corresponding AWS KMS
multi-Region replica (explicitly mapped to the archive's version), or an archive
originally wrapped using the configured recovery key. Existing non-AWS envelope
archives can use the generic remote protocol but cannot pass AWS KMS recovery.

## GitHub Actions

Run **AWS envelope and geo recovery** manually on a trusted ref. Configure the
`aws-recovery` GitHub Environment, restrict deployment refs, and require reviewers
according to your production access policy. Configure these environment variables:

| GitHub variable/secret | Value |
| --- | --- |
| Variable `AWS_RECOVERY_ROLE_ARN` | OIDC role assumed by this workflow |
| Variables `BACKUP_PRIMARY_REGION`, `BACKUP_RECOVERY_REGION` | Explicit distinct regions |
| Variable `BACKUP_KEY_VERSION` | Synthetic version or the actual archive's version |
| Variable `BACKUP_RECOVERY_KMS_KEY_ID` | Matching recovery-region KMS key or replica |
| Variable `BACKUP_RECOVERY_S3_PREFIX` | Private versioned bucket and dedicated recovery object prefix |
| Secret `BACKUP_SIGNING_KEY` | Signing secret for the selected version; no dummy fallback |

The role trust policy should limit GitHub's OIDC audience to `sts.amazonaws.com`
and the subject to `repo:OWNER/REPO:environment:aws-recovery`. Grant scoped
`s3:GetBucketLocation`, `s3:GetBucketPublicAccessBlock`, `s3:GetBucketPolicyStatus`,
`s3:GetBucketVersioning`, destination `s3:PutObject`/`s3:GetObject`, and
`kms:DescribeKey`/`kms:Encrypt`/`kms:Decrypt` as needed. Actual archive mode also
needs `s3:GetObjectVersion` on the source object and access through the KMS key
policy. No static AWS access-key secrets are used. Restrict S3 writes to the drill
prefix and configure lifecycle retention there; the workflow leaves recovery
objects and their versions in S3 as evidence.

Select `controlled-synthetic` to create a fixture under real KMS, then copy and
recover it through S3. Select `actual-archive` and supply `archive_uri` and an
explicit `archive_version_id` to fetch an existing object from the primary region
and recover that backup. The configured version/key and signing secret must
match it. Object keys include data mode, run ID and attempt; the job, summary,
artifact and JSON all identify which data was tested. Only the JSON report is
uploaded to GitHub. Protect artifact access: paths, hashes, account IDs and key
ARNs are operational metadata. Reports are retained for 30 days.

## Local compatibility and limits

Running without arguments still performs the isolated synthetic drill. Local
synthetic runs generate fresh ephemeral signing/master secrets when not configured,
including the existing three-command local protocol with `--require-remote`.
These secrets are not retained and the report identifies the local provider;
this demonstrates the protocol, not AWS key custody. Generic `--require-remote`
alone makes no regional or cloud-policy assertion.

`extract_verified` accepts only an absent or empty isolated destination and
rejects symlink/junction ancestors, archive links, traversal, drive/UNC paths,
alternate data streams, reserved Windows device names and trailing dots/spaces.
Do not share the extraction directory with another writer. Failure can leave
partial files in a caller-supplied destination; use a new empty directory for retry.

This drill validates plaintext extraction, not database import, running-service
health, RPO/RTO or failover. Primary region is an operator declaration, while S3
and KMS secondary locations are observed. Preflight observes configuration at
run time; it does not prove continuous policy enforcement, replication settings,
an outage of the primary region or recoverability without the original local
archive. S3 readback and fetch must match the source hash; concurrent replacement
fails verification rather than selecting a pinned destination object version.
Real AWS acceptance still requires executing the workflow with your resources
and reviewing its evidence. Local tests mock AWS responses and cannot establish
that acceptance.
