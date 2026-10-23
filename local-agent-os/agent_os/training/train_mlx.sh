#!/bin/zsh
# Entrena un modelo ALUMNO con MLX LoRA y lo publica en Ollama.
#
# Dos modos (compatibles):
#   Legacy (Action Planner):  ./train_mlx.sh [version]
#       usa training/dataset/{train,valid}.jsonl → agent-os/action-planner:<version>
#   Por agente (constructor): ./train_mlx.sh <agente> <version> [dataset.jsonl]
#       parte un .jsonl en train/valid → agent-os/<agente>:<version>
#
# Requisitos: pip install mlx-lm (en el venv); Ollama corriendo.
# Variables opcionales: ITERS, BATCH, LR, MIN_EXAMPLES, FORCE=1 (saltar el guard).
set -euo pipefail  # pipefail: un fallo de mlx_lm no lo tapa el tee

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$ROOT/.venv/bin/python"
: ${BASE_MODEL:="Qwen/Qwen2.5-3B-Instruct"}   # punto dulce para 32GB; el generalista usa 7B-4bit
: ${MIN_EXAMPLES:=100}

if [[ $# -ge 2 ]]; then
  # ── modo por agente ───────────────────────────────────────────────────────
  AGENT="$1"; VERSION="$2"
  DATASET="${3:-$ROOT/data/datasets/$AGENT.jsonl}"
  PUBLISH="agent-os/${AGENT//_/-}:$VERSION"
  DATA_DIR="$ROOT/training/dataset_$AGENT"
  ADAPTER_DIR="$ROOT/training/adapters/$AGENT/$VERSION"
  FUSED_DIR="$ROOT/training/fused/$AGENT/$VERSION"
  [[ -f "$DATASET" ]] || { echo "No existe dataset: $DATASET" >&2; exit 1; }
  mkdir -p "$DATA_DIR"
  "$PY" - "$DATASET" "$DATA_DIR" <<'PYSPLIT'
import random, sys
src, out = sys.argv[1], sys.argv[2]
rows = [l for l in open(src, encoding="utf-8").read().splitlines() if l.strip()]
random.Random(42).shuffle(rows)
if len(rows) >= 5:
    nv = max(1, int(len(rows) * 0.1))
    valid, train = rows[:nv], rows[nv:]
else:
    # Pocos ejemplos (prueba de humo): mlx exige un valid NO vacío — se
    # duplica el primero en vez de restarlo del train.
    valid, train = rows[:1], rows
open(out + "/train.jsonl", "w", encoding="utf-8").write("\n".join(train) + ("\n" if train else ""))
open(out + "/valid.jsonl", "w", encoding="utf-8").write("\n".join(valid) + ("\n" if valid else ""))
print(f"split: {len(train)} train, {len(valid)} valid")
PYSPLIT
else
  # ── modo legacy (Action Planner) ──────────────────────────────────────────
  AGENT="action_planner"; VERSION="${1:-v1}"
  PUBLISH="agent-os/action-planner:$VERSION"
  DATA_DIR="$ROOT/training/dataset"
  ADAPTER_DIR="$ROOT/training/adapters/$VERSION"
  FUSED_DIR="$ROOT/training/fused/$VERSION"
fi

[[ -f "$DATA_DIR/train.jsonl" ]] || { echo "No hay train.jsonl en $DATA_DIR." >&2; exit 1; }
N=$(wc -l < "$DATA_DIR/train.jsonl")
if (( N < MIN_EXAMPLES )) && [[ "${FORCE:-0}" != "1" ]]; then
  echo "Solo $N ejemplos (<$MIN_EXAMPLES): con tan pocos el LoRA memoriza en vez de aprender." >&2
  echo "Genera más (sube --n) o fuerza con FORCE=1 (solo para una prueba de humo)." >&2
  exit 1
fi

# Liberar VRAM: el maestro (30B ≈ 20GB) sigue en GPU y mlx no entra → OOM.
# Descargamos de Ollama todo lo cargado antes de entrenar.
echo "── Liberando GPU: descargando modelos de Ollama (mlx necesita la VRAM) ──"
for m in $(ollama ps 2>/dev/null | awk 'NR>1{print $1}'); do
  curl -s http://127.0.0.1:11434/api/generate -d "{\"model\":\"$m\",\"keep_alive\":0}" >/dev/null 2>&1
  ollama stop "$m" >/dev/null 2>&1
done
sleep 6

echo "── Entrenando LoRA: $AGENT $VERSION ($N ejemplos, base $BASE_MODEL) → $PUBLISH ──"
mkdir -p "$ADAPTER_DIR"
# --mask-prompt: la pérdida solo cuenta la respuesta del asistente, no el prompt.
# --grad-checkpoint + --max-seq-length: acotan memoria (algunos ejemplos son largos).
"$PY" -m mlx_lm lora \
  --model "$BASE_MODEL" \
  --train \
  --fine-tune-type lora \
  --data "$DATA_DIR" \
  --adapter-path "$ADAPTER_DIR" \
  --mask-prompt \
  --iters "${ITERS:-600}" \
  --batch-size "${BATCH:-1}" \
  --learning-rate "${LR:-1e-5}" \
  --max-seq-length "${MAXSEQ:-5120}" \
  --save-every "${SAVE_EVERY:-50}" \
  --grad-checkpoint 2>&1 | tee "$ADAPTER_DIR/train.log"

# ── Guarda anti-NaN ─────────────────────────────────────────────────────────
# Si el loss se vuelve NaN, los adapters finales son basura (y el modelo
# publicado también). Nos quedamos con el último checkpoint ANTERIOR al NaN;
# si no hay ninguno sano, no se publica nada.
"$PY" - "$ADAPTER_DIR" <<'PYNAN' || exit 1
import re, shutil, sys
from pathlib import Path
d = Path(sys.argv[1])
text = re.sub(r"\x1b\[[0-9;]*m", "", (d / "train.log").read_text(errors="ignore"))
first_nan = None
for line in text.splitlines():
    m = re.match(r"\s*(\d+)\s+(?:val\s+)?(nan|inf)\b", line) or re.search(r"Iter (\d+):.*loss (nan|inf)", line)
    if m:
        first_nan = int(m.group(1)); break
if first_nan is None:
    sys.exit(0)
ckpts = sorted((int(p.name.split("_")[0]), p) for p in d.glob("*_adapters.safetensors"))
good = [p for it, p in ckpts if it < first_nan]
if not good:
    print(f"✗ NaN en la iteración {first_nan} y ningún checkpoint sano: NO se publica.", file=sys.stderr)
    sys.exit(1)
healthy = int(good[-1].name.split("_")[0])
iters = max(it for it, _ in ckpts)
if healthy < iters * 0.5:
    # Publicar un checkpoint tan temprano da un alumno que solo aprendió la
    # forma del JSON, no el contenido (constructor n20261020: iter 50 de 600).
    print(f"✗ NaN en la iteración {first_nan}: el último checkpoint sano ({healthy}/{iters}) "
          "está demasiado poco entrenado. NO se publica.", file=sys.stderr)
    sys.exit(1)
shutil.copy(good[-1], d / "adapters.safetensors")
print(f"⚠ NaN en la iteración {first_nan}: se publica el checkpoint sano {good[-1].name}")
PYNAN

echo "── Fusionando adapters en el modelo base ──"
"$PY" -m mlx_lm fuse \
  --model "$BASE_MODEL" \
  --adapter-path "$ADAPTER_DIR" \
  --save-path "$FUSED_DIR" \
  $([[ "$BASE_MODEL" == *4bit* ]] && echo --dequantize)

echo "── Publicando en Ollama: $PUBLISH ──"
# Plantilla ChatML de Qwen2.5 / Qwen3-Instruct-2507 + tokens de parada (sin esto Ollama no aplica el
# formato con el que se entrenó y el modelo produce basura).
cat > "$FUSED_DIR/Modelfile" <<'TEMPLATE_EOF'
FROM __FUSED_DIR__
PARAMETER temperature 0.1
PARAMETER num_ctx 8192
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|endoftext|>"
TEMPLATE """{{ if .System }}<|im_start|>system
{{ .System }}<|im_end|>
{{ end }}{{ if .Prompt }}<|im_start|>user
{{ .Prompt }}<|im_end|>
{{ end }}<|im_start|>assistant
{{ .Response }}<|im_end|>
"""
TEMPLATE_EOF
sed -i '' "s|__FUSED_DIR__|$FUSED_DIR|" "$FUSED_DIR/Modelfile"
# --quantize: el fuse de mlx guarda fp16 (un 3B pesa ~7GB y va LENTO —
# mueve más bytes/token que un 7B-Q4). Cuantizado: ~2GB y ~2.5x más rápido,
# con pérdida de calidad mínima para salidas JSON estructuradas.
# Desde Ollama 0.40 la importación de safetensors va por MLX y solo acepta
# int4/int8/nvfp4/mxfp4/mxfp8 (q4_K_M falla). OLLAMA_QUANT=q4_K_M para un Ollama viejo.
ollama create --quantize "${OLLAMA_QUANT:-int4}" "$PUBLISH" -f "$FUSED_DIR/Modelfile"

# Ollama ya guardó su copia cuantizada: el fusionado fp16 (~7 GB un 3B, ~15 GB
# un 7B) solo ocupa SSD. El adapter (MB) se conserva para reproducir el modelo.
if [[ "${KEEP_FUSED:-0}" != "1" ]]; then
  rm -rf "$FUSED_DIR"
  echo "── Fusionado fp16 borrado (KEEP_FUSED=1 para conservarlo) ──"
fi

echo ""
echo "Listo: ollama run $PUBLISH"
