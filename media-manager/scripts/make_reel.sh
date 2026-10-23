#!/bin/bash
# make_reel.sh — Ensambla un reel vertical (1080x1920) a partir de:
#   - un GIF de la interfaz de la app de kanjis
#   - un guion de voz (texto) → voz femenina con edge-tts
#   - una pista de música de fondo (de media-manager/music/)
#
# Uso:
#   ./make_reel.sh <gif> <texto_voz> <idioma: es|en|it> <musica.mp3> <salida.mp4>
#
# Ejemplo:
#   ./make_reel.sh ../gifs/demo-kanji.gif "Aprende kanjis jugando" es ../music/koto-theme.mp3 ../output/reel-$(date +%Y%m%d).mp4
set -e

GIF="$1"; TEXTO="$2"; IDIOMA="${3:-es}"; MUSICA="$4"; SALIDA="$5"

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EDGE_TTS="$BASE/../local-agent-os/.venv/bin/edge-tts"

# Voces femeninas con entonación ajustada (definidas en tts_mixto.py):
#   es = Dalia (latina) · en = Jenny · it = Elsa
# Los tramos en escritura japonesa (こんにちは, 漢字…) se pronuncian
# automáticamente con la voz japonesa nativa Nanami.
case "$IDIOMA" in
  es|en|it) : ;;
  *) echo "Idioma no soportado: $IDIOMA (usa es|en|it)"; exit 1 ;;
esac

[ -f "$GIF" ]    || { echo "GIF no encontrado: $GIF"; exit 1; }
[ -f "$MUSICA" ] || { echo "Música no encontrada: $MUSICA"; exit 1; }
[ -n "$SALIDA" ] || { echo "Falta la ruta de salida"; exit 1; }

VOZ_MP3="$BASE/voiceovers/voz-$(date +%s).mp3"
python3 "$BASE/scripts/tts_mixto.py" "$TEXTO" "$IDIOMA" "$VOZ_MP3"

# Duración del reel = duración de la voz + 1.5s de cierre (mín. 6s para reels)
DUR_VOZ=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$VOZ_MP3")
DUR=$(python3 -c "print(max(6.0, $DUR_VOZ + 1.5))")

# GIF en loop, escalado/recortado a 1080x1920, voz + música (música al 18%)
ffmpeg -y -ignore_loop 0 -i "$GIF" -i "$VOZ_MP3" -stream_loop -1 -i "$MUSICA" \
  -filter_complex "\
    [0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,format=yuv420p[v];\
    [2:a]volume=0.18[m];\
    [1:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]" \
  -map "[v]" -map "[a]" -t "$DUR" \
  -c:v libx264 -preset medium -crf 21 -c:a aac -b:a 128k \
  -movflags +faststart "$SALIDA"

echo "✓ Reel creado: $SALIDA (${DUR}s, idioma: $IDIOMA + japonés nativo automático)"
