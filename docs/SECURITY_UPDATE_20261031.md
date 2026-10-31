# 2026-10-31 PDF dependency security update

CI identified seven pypdf 6.21.2 advisories (GHSA-62m5-6wh8-28x7, GHSA-42gh-23hr-vphw, GHSA-x3rh-gjgm-fmqc, GHSA-4vqv-7265-gm2w, GHSA-5849-834g-hvw5, GHSA-mfr5-77xh-9j7h, GHSA-cggf-277g-3q54). Upgrade to 6.21.4, including the Linux and Windows hash-pinned lock files.

The downloaded universal wheel was verified as SHA-256 `33e4fb41ca352810eb4e9838aa0d82d6888a5f8bf682f43e99cce5faa666255c`. In the production Python 3.11 image, lint and all 657 Python tests passed, including document parsing. CI must also pass both locked dependency audits and runtime image scans before merge.
