#!/bin/zsh
# Arranca SearXNG en 127.0.0.1:8888 (nunca expuesto a la red). Idempotente.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
colima status >/dev/null 2>&1 || colima start --cpu 2 --memory 2 --disk 10
docker inspect paradax-searxng >/dev/null 2>&1 && { docker start paradax-searxng >/dev/null; echo "SearXNG ya existe: arrancado"; exit 0; }
SECRET="$(openssl rand -hex 32)"
mkdir -p "$DIR/data"
sed "s/REEMPLAZAR_EN_EL_ARRANQUE/$SECRET/" "$DIR/settings.yml" > "$DIR/data/settings.yml"
docker run -d --name paradax-searxng --restart unless-stopped \
  -p 127.0.0.1:8888:8080 \
  -v "$DIR/data/settings.yml:/etc/searxng/settings.yml:ro" \
  searxng/searxng:latest
echo "SearXNG arrancado en http://127.0.0.1:8888"
