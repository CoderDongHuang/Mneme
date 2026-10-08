# ADR 0001: Service and data boundaries

Status: accepted

## Decision

- The browser calls only Java Gateway.
- Java Gateway owns users, knowledge metadata, documents, chat sessions, messages, durable jobs, and pending-memory decisions in MySQL.
- Python Agent owns model orchestration, retrieval, embeddings, and semantic-memory execution. It does not own user identity or business records.
- Chroma stores vectors. Redis stores short-term context, shared counters and leases, and a reflection task stream; the stream is recoverable queue state and must be included in backup and recovery planning.
- Java authenticates users. Calls from Java to Python use `X-Internal-Service-Token`; Python rejects unsigned business calls.
- Flyway migrations under `java-gateway/src/main/resources/db/migration` are the only executable database schema source. Spring SQL initialization is disabled.

## Consequences

All cross-service payloads require versioned DTOs and contract tests. Business workflows must be recoverable from MySQL after process restart; pending reflection tasks also depend on Redis stream persistence. Loss of a disposable cache may reduce performance, while loss of Redis stream data can lose pending reflection work.
