ARG NODE_BASE_IMAGE=node:22-alpine
ARG CADDY_BASE_IMAGE=caddy:2.9-alpine
FROM ${NODE_BASE_IMAGE} AS build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
COPY LICENSE /app/LICENSE
ARG VITE_DEMO_MODE=false
ENV VITE_DEMO_MODE=${VITE_DEMO_MODE}
RUN npm run audit
RUN npm run build

FROM ${CADDY_BASE_IMAGE}
COPY --from=build /app/frontend/dist /srv/frontend
COPY frontend/Caddyfile /etc/caddy/Caddyfile
