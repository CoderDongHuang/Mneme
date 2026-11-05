# The upstream dashboard has separate npm advisories. Mneme only uses the API.
# Keep the official service binary, runtime libraries and complete Rust SBOM.
ARG QDRANT_BASE_IMAGE=qdrant/qdrant:v1.20.0@sha256:9bfc89f9914fc14876a88c05270685921a55b8877b254a98bcc1cc2f0a424cd2
FROM ${QDRANT_BASE_IMAGE}

# Patch the pinned upstream OS without replacing the Qdrant binary or its SBOM.
# apt/libapt-pkg7.0 >= 3.0.4 fixes CVE-2026-109518 in Debian 13.
RUN apt-get update \
    && apt-get install -y --only-upgrade --no-install-recommends apt libapt-pkg7.0 \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' apt)" ge 3.0.4 \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' libapt-pkg7.0)" ge 3.0.4 \
    && rm -rf /var/lib/apt/lists/* /qdrant/static \
    && mkdir -p /qdrant/storage/snapshots \
    && chown -R 10001:10001 /qdrant/storage

ENV QDRANT__SERVICE__ENABLE_STATIC_CONTENT=false \
    QDRANT__STORAGE__SNAPSHOTS_PATH=/qdrant/storage/snapshots \
    QDRANT_INIT_FILE_PATH=/qdrant/storage/.qdrant-initialized \
    QDRANT__TELEMETRY_DISABLED=true

USER 10001:10001
