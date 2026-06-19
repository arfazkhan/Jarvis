#!/usr/bin/env bash
# Build the 3 AllGud images on YOUR machine and push them to GHCR.
# The DigitalOcean Droplet then just pulls them (no source on the server).
#
# One-time:  echo $GHCR_PAT | docker login ghcr.io -u arfazkhan --password-stdin
#            (PAT needs write:packages)
# Run:       REGISTRY=ghcr.io/arfazkhan TAG=latest ./build-and-push.sh
set -euo pipefail

REGISTRY="${REGISTRY:-ghcr.io/arfazkhan}"
TAG="${TAG:-latest}"
PLATFORM="linux/amd64"           # DO Droplets are amd64
cd "$(dirname "$0")"             # arvisx/deploy

echo ">> building (platform $PLATFORM, tag $TAG) -> $REGISTRY"
# context is arvisx/ (..) for api+web so Allgud/ and deploy/Caddyfile resolve.
docker build --platform "$PLATFORM" -f api.Dockerfile -t "$REGISTRY/allgud-api:$TAG" ..
docker build --platform "$PLATFORM" -f web.Dockerfile --build-arg VITE_API_BASE=/api/v1 -t "$REGISTRY/allgud-web:$TAG" ..
docker build --platform "$PLATFORM" -f ../bot/Dockerfile -t "$REGISTRY/allgud-bot:$TAG" ../bot

echo ">> pushing"
docker push "$REGISTRY/allgud-api:$TAG"
docker push "$REGISTRY/allgud-web:$TAG"
docker push "$REGISTRY/allgud-bot:$TAG"

echo ">> done. On the Droplet:  docker compose -f docker-compose.cloud.yml pull && up -d"
