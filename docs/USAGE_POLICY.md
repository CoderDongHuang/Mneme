# Usage-derived policy reports

The collector and report generator produce reviewable JSON recommendations. They
do not update tenant settings, apply retention changes, or change budgets. The
configuration report is an export of the operator-supplied settings, not a
discovery of effective runtime configuration. Check those values against the
deployment before acting on recommendations.

## Collect measured usage

Run from the repository root in an environment with `mysql-connector-python`,
`redis`, and `prometheus-client` installed and access to the deployment's MySQL,
Redis, and metrics endpoint. Connection options use the existing environment
variables; prefer a read-only database account. Do not put credentials in reports.

```powershell
.venv\Scripts\python.exe scripts/collect_usage_policy_snapshot.py `
  --usage-report artifacts/usage-policy-snapshot.json `
  --config-report artifacts/usage-policy-config.json `
  --environment production `
  --cost-scope deployment-a/providers-primary-and-fallback
```

Set quotas, retention, session TTL, daily budget, window, and idle threshold to
the deployment's actual values using the collector's CLI options. The idle
threshold must be positive and no greater than the window. Quotas and durations
must be positive; a zero daily LLM budget means budget enforcement is disabled.
The default environment is `unspecified`, which cannot support calibration.
`cost_scope` identifies all deployment/account/provider traffic covered by the
shared Redis cost key; it must not describe just one tenant when the key is
shared. Use a sanitized identifier, not an account secret.

The collector keeps measurement bases separate:

| Measurement | Basis |
| --- | --- |
| Trace occupancy | All currently retained `agent_trace` rows / global row quota, including rows created before the window |
| Trace activity | Rows created within the bounded measurement window |
| Sample count | Maximum of windowed active sessions, trace activity, and learning observations; not a unique-user count or a sum |
| Idle sessions | Idle fraction of unrevoked, unexpired sessions seen within the window |
| Knowledge storage / base count | Largest per-user occupancy / corresponding per-user quota |
| Learning retention | Success fraction of learning outcome events in the window; not a longitudinal causal result |
| LLM cost | UTC-day cumulative reservation estimate from Redis, not a provider invoice |
| Prometheus request series | Diagnostic cumulative series; never counted as window samples |

Occupancy ratios can exceed one and remain visible in the recommendations.
Negative values, NaN, infinity, booleans posing as numbers, fractional counts,
invalid quotas, and impossible idle/trace subset counts are rejected. Old traces,
registered users, and historical metric counters alone cannot create a sample.
The MySQL queries assume the application's naive timestamps are UTC. The DB
window and Redis read end are recorded separately because these systems do not
provide an atomic cross-system snapshot. Collection across UTC midnight is
rejected and must be retried.

## Optional real billing reconciliation

```powershell
.venv\Scripts\python.exe scripts/usage_policy_report.py `
  --usage artifacts/usage-policy-snapshot.json `
  --config artifacts/usage-policy-config.json `
  --billing artifacts/provider-billing-normalized.json `
  --report artifacts/usage-policy-report.json `
  --history-dir artifacts/usage-policy-history
```

Omit `--billing` to generate recommendations with an explicit `unverified`
billing state. Merely adding `evidence.billing` to the usage JSON does not verify
costs. The output path must differ from all input files.

Normalize an actual provider export to this schema. This example describes the
format only and is not production evidence:

```json
{
  "schema_version": 1,
  "source": {
    "kind": "provider_billing_export",
    "reference": "sanitized-export-123"
  },
  "environment": "production",
  "cost_scope": "deployment-a/providers-primary-and-fallback",
  "currency": "USD",
  "period_start": "2026-09-30T00:00:00Z",
  "period_end": "2026-09-30T12:00:00Z",
  "exported_at": "2026-09-30T12:30:00Z",
  "complete": true,
  "actual_cost_usd": 9.40
}
```

Preserve the original export outside the repository for audit. `source.reference`
must identify that evidence. Sum attributable usage charges for all providers
covered by the Redis key, excluding unrelated account traffic, taxes, credits,
and other products. There is no currency conversion. `complete` means all
charges for precisely this interval and scope have been included, after billing
lag has settled; it is a JSON boolean. Do not mark provisional data complete.
All timestamps require timezones; equivalent UTC offsets compare equally.
`exported_at` must be at or after the period end and no more than five minutes
ahead of the report's current time.

The billing interval must exactly match the snapshot's `cost_period_start` and
`cost_period_end`, not its session/learning measurement window. A monthly invoice
or full-day export does not match a midday counter. Do not relabel a bill's
interval to force a match. If a provider cannot export charges for the captured
interval, keep the report unverified. Snapshot freshness checks still apply:
the report accepts a snapshot only within its measurement window plus five
minutes. Delayed billing may require a longer genuine collection window; it
does not justify changing the captured timestamp.

## Interpret the state

Malformed billing input fails validation. Valid input stays `unverified` with
machine-readable reasons when scope/interval differs, the counter is absent,
the source is a fixture or estimate, production provenance is absent, charges
are incomplete, costs are zero, or the cost difference exceeds tolerance.
Legacy or operator snapshots without collector provenance remain unverified.

`billing_reconciliation.status = calibrated` means a production collector
snapshot with a present, date-matched Redis key agrees with the supplied complete
production provider export for the same scope and interval. Both costs must be
positive. The allowed absolute difference is `max(0.05 USD, 10% of actual cost)`.
The report includes measured usage, actual and estimated costs, absolute and
relative differences, the tolerances, and the billing source, scope, completeness,
and export timestamp. Recommendations continue to use
the reservation estimate, matching the application's budget mechanism.

Calibration is limited to `llm_cost_only` and this one interval. These tools
validate supplied evidence structure and agreement; they do not authenticate
provider documents or attest that input files are genuine. The report explicitly
records `provenance_verification = operator_supplied_not_authenticated` and
`production_policy_verified = false`. Test fixtures demonstrate implementation
behavior and do not constitute real calibration. The reservation mechanism
counts estimated maximum output costs and can reserve for failed/fallback calls,
so a genuine mismatch with billing is possible and should be investigated.

Before manually approving a policy adjustment, review the actual export,
deployment settings, repeated representative usage, and learning outcomes.
Neither a successful reconciliation nor a recommendation authorizes an automatic
tenant configuration change.

## Production report history and scheduling

`--history-dir` is opt-in. Each distinct validated report is preserved under
`<history-dir>/<UTC-capture-date>/<SHA-256-of-report>.json`. Identical reruns reuse
the existing entry; a differing existing entry is rejected rather than
overwritten. A second report for the same snapshot with a new billing export
creates a separate entry. Unverified reports are preserved too, so missing bills
or failed reconciliation cannot disappear from the record. Invalid input fails
before report/history writes. The ordinary `--report` remains a replaceable
latest report; history is additional local evidence, not an authenticated audit
service. Back up history using the deployment's existing storage procedure.

For a production run, the two commands above are directly runnable from the
repository root after connection variables, actual quota/budget options, and the
normalized billing file have been supplied. Use a history directory outside the
checkout for operational runs, for example `D:\MnemeReports\usage-policy-history`.
The billing exporter is operator-owned: export the genuine charges for the
collector's recorded interval before running the report command. Until that
export is available, run the report without `--billing` and retain the unverified
entry; rerun against the same snapshot with the export while it is still fresh.
Never substitute this document's example JSON for actual charges.

Production scheduling is intentionally not enabled by these scripts. The current
repository CI usage job runs against its test stack and is not a production data
source. No AWS secrets or repository variables are required or configured for
this feature. A safe opt-in schedule belongs on a separately provisioned
production host using its existing scheduler, after all of these prerequisites
have been met:

1. Read-only production database access, protected Redis/metrics access, and
   explicit `--environment production` / matching `--cost-scope` are available.
2. Actual deployment settings are supplied, and a provider exporter can deliver
   complete charges for the exact captured interval while the snapshot is fresh.
3. Collection, export, and reporting run serially, with no concurrent writer to
   the latest report or history entry; failures are surfaced by the scheduler.
4. History resides in access-controlled, backed-up storage outside the repo;
   credentials remain in the host's existing secret mechanism.

If the exporter cannot meet the interval/freshness prerequisite, a scheduled
measurement report may still run without billing and remain `unverified`.
The scripts do not fetch provider bills, infer account attribution, authenticate
exports, or turn configuration labels into proof. A scheduled run must never
fall back to fixture billing or silently label an unverified report calibrated.
Production scheduling or policy approval therefore requires an operator's
deployment integration; the repository does not activate it automatically.

## Focused verification

```powershell
.venv\Scripts\python.exe -m pytest `
  python-agent/tests/test_usage_policy.py `
  python-agent/tests/test_usage_policy_report.py `
  python-agent/tests/test_usage_policy_snapshot.py -q
```

These tests cover validation, calibration and unverified states, interval/scope
matching, SQL measurement bases, CLI input preservation, and bounded suggestions.
Database, Redis, and metrics I/O in the collector test is mocked; live deployment
access and real billing exports are still needed for operational calibration.
