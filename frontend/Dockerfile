FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run audit
RUN npm run build

FROM caddy:2.9-alpine
COPY --from=build /app/dist /srv/frontend
COPY Caddyfile /etc/caddy/Caddyfile
