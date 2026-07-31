# Remediation baseline

- Baseline commit: `b2c5604107803d587c28d3d5ed0dfa80a1a54fe7`
- Baseline date: 2026-07-28
- Python: 60 tests passing; Ruff passing.
- Java: build passing; no tests existed at baseline.
- Frontend: production build passing; lint command failing because ESLint was not installed.
- Integration and browser end-to-end coverage did not exist.

## Protected workflows

1. Register or sign in through Java Gateway.
2. Create a knowledge base and upload a supported document.
3. Observe durable parsing status through completion or failure.
4. Create a chat session and receive a cited streaming response.
5. Review and resolve a server-stored pending memory.

Each remediation phase must keep these workflows contract-compatible or provide an explicit migration.
