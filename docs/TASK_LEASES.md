# Durable task ownership

Account deletion, document ingestion/deletion, knowledge-base deletion and ingestion
cancellation cleanup use the same MySQL owner lease protocol (Flyway V27).

Each claim has an independent UUID, monotonically increasing `lease_fence`, and
database-clock `lease_until`. Claiming is a conditional UPDATE, not SELECT followed
by an unconditional write. `TASK_LEASE_SECONDS` defaults to 300 and has a minimum
of 3 seconds. A separate bounded scheduler renews at one third of that interval,
including while the worker waits for HTTP or object storage. Workers also renew
before each stage. Expired leases cannot be renewed or resurrected.

Every business-state commit locks and checks the task's owner, fence, expiry and
active status. Document changes, deletion step receipts and terminal transitions
share that transaction. Completion, retry, failure and cancellation clear the
owner only when the same owner and fence still hold an unexpired lease. A failed
transaction rolls all dependent MySQL writes back. Notifications persist in that
transaction and are delivered after commit, never from a stale worker snapshot.
Legacy timestamp recovery is retained only for tasks created before V27.

Slow external calls run outside MySQL transactions. An already issued external
delete cannot be recalled if the process loses ownership; deletes must remain
idempotent and target a deleting entity. MySQL fencing prevents stale step/result
commits, not arbitrary external-storage writes. Python index generation fencing
is a separate P2-10 requirement and must not be inferred from this protocol.

## Upgrade and rollback

1. Back up the database and application data, record the current image versions,
   and stop **all** old Gateway workers before starting V27. Old workers do not
   understand ownership columns; mixed old/new deployment is unsupported.
2. Start the updated Gateway, let Flyway apply V27, and check readiness and the
   Flyway history. Existing pending/retry tasks are claimed with fresh UUIDs;
   abandoned legacy tasks become eligible after the five-minute timeout.
3. Verify a disposable upload, cancellation, document/KB deletion and account
   deletion. For multi-instance deployments inspect owner/fence/expiry while a
   slow task runs, then terminate one worker and verify takeover after expiry.
4. For application rollback stop all new workers first. Restore the matching
   pre-upgrade database and images as a set; do not restart an old worker against
   live V27-owned tasks. Verify readiness and the same disposable operations.

## Automated verification

`TaskLeaseConcurrencyTest` runs two independent service instances against real
MySQL with the actual Flyway migrations. It checks competing claims for both
queues, real heartbeat renewal beyond the original lease, cancellation ownership,
transaction/outbox rollback, and suspended account/ingestion workers resuming
after takeover. The expiry test moves the **persisted database lease** more than
five minutes into the past; it does not claim to wait five wall-clock minutes.
For literal wall-clock acceptance, run the suspended account-worker test with
`-Dmneme.test.pause-seconds=301`. This holds the old worker inside its external
call for more than five minutes without heartbeat or database-clock edits,
then lets a second instance take over before releasing the old worker.
No deployment-wide timeout or rate limit is disabled.
