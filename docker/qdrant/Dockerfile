# The upstream dashboard has separate npm advisories. Mneme only uses the API.
# Keep the official service binary, runtime libraries and complete Rust SBOM.
ARG QDRANT_BASE_IMAGE=qdrant/qdrant:v1.20.0@sha256:9bfc89f9914fc14876a88c05270685921a55b8877b254a98bcc1cc2f0a424cd2
FROM ${QDRANT_BASE_IMAGE}

RUN rm -rf /qdrant/static \
    && mkdir -p /qdrant/storage/snapshots \
    && chown -R 10001:10001 /qdrant/storage

ENV QDRANT__SERVICE__ENABLE_STATIC_CONTENT=false \
    QDRANT__STORAGE__SNAPSHOTS_PATH=/qdrant/storage/snapshots \
    QDRANT_INIT_FILE_PATH=/qdrant/storage/.qdrant-initialized \
    QDRANT__TELEMETRY_DISABLED=true

USER 10001:10001
