from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARADAX_ROOT = Path(os.getenv("PARADAX_ROOT", str(ROOT.parent))).resolve()
DATA_DIR = ROOT / "data"
RUNS_DIR = ROOT / "runs"
ARTIFACTS_DIR = ROOT / "artifacts"
# Carpeta VISIBLE de resultados: aquí se materializa el trabajo de cada run de
# proyecto como archivos reales (guías .md, configs .json…). Sin esto, todo lo
# que producen los agentes queda atrapado en SQLite y "la app no hace nada".
RESULTS_DIR = Path(os.getenv("PARADAX_RESULTS_DIR", str(PARADAX_ROOT / "resultados")))

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen3-coder:30b")

# Modelo LIGERO para el trabajo estructurado del sistema (Team Constructor,
# decisiones de tools): produce JSON cortos donde el 7B rinde igual que el
# 30B pero piensa en segundos y usa ~4x menos memoria. El 30B queda para
# runs de código donde la calidad extra compensa.
FAST_MODEL = os.getenv("PARADAX_FAST_MODEL", "qwen2.5:7b")

# 9router (github.com/decolua/9router): proxy OpenAI-compatible que hace de
# MAESTRO en el entrenamiento nocturno. Un modelo con prefijo "9r/" (p. ej.
# "9r/glm-4.6") va a 9router en vez de a ollama. Solo se admiten familias de
# licencia abierta: destilar salidas de modelos cerrados viola sus términos.
NINEROUTER_BASE_URL = os.getenv("NINEROUTER_BASE_URL", "http://127.0.0.1:20128/v1").rstrip("/")
NINEROUTER_API_KEY = os.getenv("NINEROUTER_API_KEY", "")
NINEROUTER_PREFIX = "9r/"
OPEN_LICENSE_FAMILIES = ("glm", "qwen", "deepseek")

# Modelo del Project Manager y su cadena (Team Planner → Skills Definer →
# Constructor): es el generalista que diseña equipos y fabrica agentes, así
# que usa el modelo POTENTE, no el ligero.
PM_MODEL = os.getenv("PARADAX_PM_MODEL", DEFAULT_MODEL)

# Ventana de contexto para las llamadas a ollama. El KV-cache es el gran
# consumidor de RAM (crece con num_ctx): 16k en vez de los 32k del modelo
# = la mitad de memoria por carga, y sobra para nuestros prompts.
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
# Hermano de local-agent-os dentro del repo, así que se deriva de PARADAX_ROOT.
# Estaba escrito como ruta absoluta y eso ataba el proyecto a una carpeta concreta.
MEDIA_MANAGER_ROOT = Path(
    os.getenv("MEDIA_MANAGER_ROOT", str(PARADAX_ROOT / "media-manager"))
)


def ensure_dirs() -> None:
    for path in (DATA_DIR, RUNS_DIR, ARTIFACTS_DIR):
        path.mkdir(parents=True, exist_ok=True)
