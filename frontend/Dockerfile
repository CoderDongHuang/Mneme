ARG NODE_BASE_IMAGE=node:22-alpine
ARG CADDY_BASE_IMAGE=caddy:2.9-alpine
FROM ${NODE_BASE_IMAGE} AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run audit
RUN npm run build

FROM ${CADDY_BASE_IMAGE}
COPY --from=build /app/dist /srv/frontend
COPY Caddyfile /etc/caddy/Caddyfile
