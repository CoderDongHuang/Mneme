# Chat stream contract

P3-06 uses `python-agent/app/models/chat_stream.py` as the canonical SSE payload definition. Export it using the project's locked Python 3.11 environment:

```sh
python python-agent/scripts/export_stream_contract.py
python python-agent/scripts/export_stream_contract.py --check
```

The exporter produces `contracts/chat-stream.schema.json`, the byte-identical Gateway classpath resource, and `frontend/src/api/generated/chat-stream.d.ts`. CI invokes the drift check through pytest. Unsupported nested schema constraints block generation; update both bounded validators and cross-language cases before expanding the vocabulary. Do not hand-edit generated files or generate with a different Pydantic version.

The public events are `start`, `meta`, `token`, `memory`, `done`, `error`, and `stopped`. Agent-originated events are limited to `meta`, `token`, `memory`, `done`, and `error`; ownership and stop receipts originate at the Gateway. The shared schema describes required and nullable fields, enums, bounds and unknown-field handling. A successful `done` must contain a nonnegative answer length or `ok: true`. Java integers used in citation page/rank fields remain within signed 32-bit bounds; generation/answer length use JavaScript's safe integer range. JSON integer values such as `1.0` agree across all three validators; booleans and numeric strings do not count as integers.

Agent validates before serialization. Gateway validates before accumulating, saving or forwarding payloads, including its own frames and successful answer replay. Browser validates parsed JSON before callbacks and completion. Unknown event names, malformed JSON or invalid payloads cannot be ignored and then followed by a successful `done`. Protocol failures use `INVALID_CHAT_EVENT` without returning payloads or parser exception text. Gateway persists that fixed failure code and the valid partial answer, and closes the upstream connection. The browser also cancels/releases its reader on invalid input. Existing generation fences, explicit stop and persistence-before-done behavior remain covered by their original regressions.

`contracts/chat-stream.cases.json` is consumed by Python, Java and frontend tests. The browser fixture is parsed as raw JSON using Node's file reader so own `__proto__` keys are preserved; it is not converted to a JavaScript object literal. Invalid frames followed by valid success are also tested against the actual HTTP proxy service and the browser client. `chat-contract-real.spec.js` adds a scoped bad upstream provider to a synthetic account on the real localhost stack, checks failed history after reload and upstream closure, then restores exact original bytes and deletes the account in `finally`. It requires both real-E2E and explicit fault-injection switches and never imports its hook in production. Test output must not include the private frame canary.

No dependency, configuration or database migration is added. Both frontend Dockerfile and its build-context allowlist include the root `contracts` directory. Deploy Gateway, Agent and frontend as a compatible set, stopping old writers first. Retain matching SQL, Redis/Agent data and old images/configuration for rollback; do not roll back code against newer unmatched state. Existing stored valid citations and answer receipts remain accepted.

This closes the SSE portion of P3-06. It does not claim shared contracts for every REST API, complete post-answer memory decoupling (P1-06), or physical erasure/retention (P2-12). The canonical contract validates event shape; persistence and authorization still require their own service checks.
