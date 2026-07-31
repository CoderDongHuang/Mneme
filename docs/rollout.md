# Remediation rollout and rollback

## Release sequence

1. Back up MySQL and Chroma, then deploy Flyway V3 with the old application still stopped.
2. Deploy Python Agent with both legacy asynchronous ingestion and durable synchronous ingestion enabled.
3. Deploy Java Gateway with the durable task scheduler disabled using `MNEME_TASK_POLL_DELAY_MS` only during schema verification, then enable normal polling.
4. Verify new uploads reach `ready`, failed jobs retry, and knowledge-base deletion removes vectors and files before metadata.
5. Deploy the frontend request-ID and memory-confirmation changes.
6. After one stable release window, remove the legacy Python upload/task endpoints and obsolete in-memory task tracker.

## Verification gates

- Flyway reports schema version 3 with no failed migration.
- No `processing` task remains locked for more than five minutes.
- A repeated task produces the same document vector IDs and no duplicate chat messages.
- Java `/actuator/health`, Java `/actuator/prometheus`, Python `/health/ready`, and Python `/metrics` respond as expected.
- Register, upload, parse, cited chat, pending-memory confirmation, and deletion pass end to end.

## Rollback

Application rollback is allowed while V3 remains in place because its new columns and tables are additive. Disable task polling before rolling Java back. Do not automatically reverse V3 or delete durable task records. Restore MySQL/Chroma backups only for confirmed data corruption, not for an application-only regression.
