#!/bin/zsh
# Abre Paradax: si el servidor ya corre, abre el navegador; si no, arranca la app de escritorio.
cd "$(dirname "$0")/local-agent-os"
if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8791/api/health 2>/dev/null | grep -q 200; then
  open "http://127.0.0.1:8791"
else
  # 30 min de margen por llamada al LLM: un modelo de 30B puede tardar en cargar.
  export OLLAMA_READ_TIMEOUT=1800
  nohup .venv/bin/python -m agent_os.desktop >/tmp/paradax.log 2>&1 &
fi
echo "
  Paradax is opening…
  You can close this window; the app keeps running."
sleep 2
