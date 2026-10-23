#!/bin/bash
# publish_tiktok.sh — Sube un reel a TikTok vía Content Posting API.
# Requiere una app aprobada en developers.tiktok.com con el scope
# video.publish y un access token de usuario.
#
# Credenciales: rellena media-manager/.env.media (ver .env.media.example)
#
# Uso:
#   ./publish_tiktok.sh <video.mp4> "<titulo/caption>"
#
# Sube el archivo directamente (FILE_UPLOAD) — no necesita URL pública.
set -e

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$BASE/.env.media" ] && source "$BASE/.env.media"

VIDEO="$1"; TITULO="$2"

: "${TIKTOK_ACCESS_TOKEN:?Falta TIKTOK_ACCESS_TOKEN en .env.media}"
[ -f "$VIDEO" ] || { echo "Video no encontrado: $VIDEO"; exit 1; }

SIZE=$(stat -f%z "$VIDEO")

# 1. Inicializar la subida (publicación directa)
INIT=$(curl -sf -X POST "https://open.tiktokapis.com/v2/post/publish/video/init/" \
  -H "Authorization: Bearer ${TIKTOK_ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"post_info\": {
      \"title\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$TITULO"),
      \"privacy_level\": \"PUBLIC_TO_EVERYONE\",
      \"disable_comment\": false
    },
    \"source_info\": {
      \"source\": \"FILE_UPLOAD\",
      \"video_size\": ${SIZE},
      \"chunk_size\": ${SIZE},
      \"total_chunk_count\": 1
    }
  }")

UPLOAD_URL=$(echo "$INIT" | python3 -c "import json,sys; print(json.load(sys.stdin)['data']['upload_url'])")
PUBLISH_ID=$(echo "$INIT" | python3 -c "import json,sys; print(json.load(sys.stdin)['data']['publish_id'])")

# 2. Subir el archivo
curl -sf -X PUT "$UPLOAD_URL" \
  -H "Content-Type: video/mp4" \
  -H "Content-Range: bytes 0-$((SIZE-1))/${SIZE}" \
  --data-binary "@${VIDEO}" > /dev/null

echo "✓ Video subido a TikTok (publish_id: $PUBLISH_ID) — TikTok lo procesará y publicará."
