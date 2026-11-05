# ADR 0001: Service and data boundaries

Status: accepted

## Decision

- The browser calls only Java Gateway.
- Java Gateway owns users, knowledge metadata, documents, chat sessions, messages, durable jobs, and pending-memory decisions in MySQL.
- Python Agent owns model orchestration, retrieval, embeddings, and semantic-memory execution. It does not own user identity or business records.
- Qdrant stores vectors. MySQL/SQLite auxiliary state is authoritative for SQL session history and delivery receipts; Redis may mirror that history for compatibility. Redis also stores short-term context, shared counters and leases, and a reflection task stream; the stream is recoverable queue state and must be included in backup and recovery planning. SQL session history contains private message content and follows the same backup access controls, encryption, retention, and matched rollback set as other account data.
- Java authenticates users. Calls from Java to Python use `X-Internal-Service-Token`; Python rejects unsigned business calls.
- Flyway migrations under `java-gateway/src/main/resources/db/migration` are the only executable database schema source. Spring SQL initialization is disabled.
- `KnowledgeQuotaService` owns tenant quota configuration, active-owner locking and locking reads of knowledge-base counts and retained version sizes. Its public methods require the caller's transaction (`MANDATORY`); allocation checks and catalog writes must commit together. Callers lock the active user before knowledge-base/document rows, then check storage capacity. All retained versions, including inactive versions and pending deletions, remain charged. The boundary preserves the existing API, limits and rejection messages; it does not implement retention or file garbage collection.

## Consequences

All cross-service payloads require versioned DTOs and contract tests. Business workflows must be recoverable from MySQL after process restart; pending reflection tasks also depend on Redis stream persistence. Loss of a disposable cache may reduce performance, while loss of Redis stream data can lose pending reflection work.
