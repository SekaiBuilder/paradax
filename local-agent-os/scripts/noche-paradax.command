#!/bin/zsh
# Consola nocturna de Paradax: la abre launchd a la 1:00 en Terminal.
# ESC pausa y te devuelve el Mac · R reanuda · Q termina.
cd "$(dirname "$0")/.."
printf '\033]11;#000000\007\033]10;#d0d0d0\007'   # fondo negro, texto gris
export PYTHONPATH="$PWD"
exec /usr/bin/caffeinate -is .venv/bin/python -m agent_os.training.night_console
