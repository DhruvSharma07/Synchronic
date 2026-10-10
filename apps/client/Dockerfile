# Build context is the REPO ROOT (see docker-compose.prod.yml), so infra/Caddyfile is reachable.
FROM node:22-alpine AS build
WORKDIR /build/apps/client

COPY apps/client/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY apps/client/ ./
# Same-origin by default: the app calls /api and /sync, which Caddy proxies.
ARG VITE_API_URL=
ARG VITE_SYNC_SERVER_URL=
ENV VITE_API_URL=$VITE_API_URL VITE_SYNC_SERVER_URL=$VITE_SYNC_SERVER_URL
RUN npm run build

FROM caddy:2-alpine
COPY infra/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /build/apps/client/dist /srv
EXPOSE 80 443
