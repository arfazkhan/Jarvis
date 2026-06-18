# AllGud web — builds the React SPA and serves it via Caddy (auto-HTTPS + same-origin
# API proxy). VITE_API_BASE=/api/v1 is RELATIVE, so the SPA calls the same origin and
# Caddy proxies /api/* to the api container — no CORS, nothing host/port baked in.
# Build context = the arvisx/ directory (so both Allgud/ and deploy/Caddyfile resolve).
FROM node:20-alpine AS build
WORKDIR /app
COPY Allgud/package.json Allgud/package-lock.json ./
RUN npm ci
COPY Allgud/ ./
ARG VITE_API_BASE=/api/v1
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
COPY deploy/Caddyfile /etc/caddy/Caddyfile
EXPOSE 80 443
