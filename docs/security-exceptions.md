# Temporary security exceptions

## GHSA-qwww-vcr4-c8h2

- Dependency: `react-router` through `react-router-dom` 7.18.1.
- Scope of advisory: React Server Components Action processing.
- Project exposure: none. Mneme is a Vite client-only SPA and does not enable React Server Components, SSR, server actions, or React Router framework mode.
- Control: `audit-ci` allowlists only this advisory; every other high or critical advisory fails CI.
- Removal condition: remove the allowlist entry as soon as React Router publishes a fixed release that remains compatible with the client router.
