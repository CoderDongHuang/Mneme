# ADR 0001: Service and data boundaries

Status: accepted

## Decision

- The browser calls only Java Gateway.
- Java Gateway owns users, knowledge metadata, documents, chat sessions, messages, durable jobs, and pending-memory decisions in MySQL.
- Python Agent owns model orchestration, retrieval, embeddings, and semantic-memory execution. It does not own user identity or business records.
- Chroma stores vectors only. Redis stores disposable cache and short-term context only.
- Java authenticates users. Calls from Java to Python use `X-Internal-Service-Token`; Python rejects unsigned business calls.
- Flyway migrations under `java-gateway/src/main/resources/db/migration` are the only executable database schema source. Spring SQL initialization is disabled.

## Consequences

All cross-service payloads require versioned DTOs and contract tests. Durable workflows must be recoverable from MySQL after process restart. Cache loss may reduce performance but must not lose business state.
