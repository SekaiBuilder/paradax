#!/bin/bash
# publish_instagram.sh — Publica un reel en Instagram (y opcionalmente Facebook)
# vía Meta Graph API. Requiere cuenta Instagram Business/Creator vinculada a
# una página de Facebook y un token de larga duración.
#
# Credenciales: rellena media-manager/.env.media (ver .env.media.example)
#
# Uso:
#   ./publish_instagram.sh <video.mp4> "<caption>" [url_publica_del_video]
#
# NOTA: la Graph API exige que el video esté accesible por URL pública
# (no acepta subida binaria directa para reels). Opciones:
#   a) subir el mp4 a un bucket/hosting propio y pasar la URL
#   b) usar un túnel temporal (cloudflared/ngrok) servido desde output/
set -e

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$BASE/.env.media" ] && source "$BASE/.env.media"

VIDEO="$1"; CAPTION="$2"; VIDEO_URL="${3:-}"

: "${IG_USER_ID:?Falta IG_USER_ID en .env.media}"
: "${META_ACCESS_TOKEN:?Falta META_ACCESS_TOKEN en .env.media}"
[ -n "$VIDEO_URL" ] || { echo "Falta la URL pública del video (argumento 3)"; exit 1; }

# 1. Crear contenedor de media (reel)
CREATION_ID=$(curl -sf -X POST "https://graph.facebook.com/v21.0/${IG_USER_ID}/media" \
  -F "media_type=REELS" \
  -F "video_url=${VIDEO_URL}" \
  -F "caption=${CAPTION}" \
  -F "access_token=${META_ACCESS_TOKEN}" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")

echo "Contenedor creado: $CREATION_ID — esperando procesamiento…"

# 2. Esperar a que Meta procese el video
for _ in $(seq 1 30); do
  STATUS=$(curl -sf "https://graph.facebook.com/v21.0/${CREATION_ID}?fields=status_code&access_token=${META_ACCESS_TOKEN}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('status_code',''))")
  [ "$STATUS" = "FINISHED" ] && break
  [ "$STATUS" = "ERROR" ] && { echo "✗ Meta rechazó el video"; exit 1; }
  sleep 10
done

# 3. Publicar
curl -sf -X POST "https://graph.facebook.com/v21.0/${IG_USER_ID}/media_publish" \
  -F "creation_id=${CREATION_ID}" \
  -F "access_token=${META_ACCESS_TOKEN}" \
  | python3 -c "import json,sys; print('✓ Publicado en Instagram, id:', json.load(sys.stdin)['id'])"

# 4. Facebook Page (opcional, si hay FB_PAGE_ID + FB_PAGE_TOKEN)
if [ -n "$FB_PAGE_ID" ] && [ -n "$FB_PAGE_TOKEN" ]; then
  curl -sf -X POST "https://graph.facebook.com/v21.0/${FB_PAGE_ID}/videos" \
    -F "file_url=${VIDEO_URL}" \
    -F "description=${CAPTION}" \
    -F "access_token=${FB_PAGE_TOKEN}" \
    | python3 -c "import json,sys; print('✓ Publicado en Facebook, id:', json.load(sys.stdin)['id'])"
fi
