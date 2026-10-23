#!/bin/zsh
# Construye "Paradax.app" — doble click abre el control center como app nativa.
# El bundle es un lanzador transparente: ejecuta el venv del proyecto, así que
# los cambios de código aplican sin reconstruir la app.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/../Paradax.app"
PYTHON="$ROOT/.venv/bin/python"

# El icono ya está generado en el repo; solo se regenera si falta (necesita Pillow).
[[ -f "$ROOT/scripts/AgentOS.icns" ]] || "$PYTHON" "$ROOT/scripts/make_icon.py"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Paradax</string>
  <key>CFBundleDisplayName</key><string>Paradax</string>
  <key>CFBundleIdentifier</key><string>local.agentos.controlcenter</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>agent-os</string>
  <key>CFBundleIconFile</key><string>AgentOS</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict>
</plist>
EOF

cat > "$APP/Contents/MacOS/agent-os" <<EOF
#!/bin/zsh
cd "$ROOT"
exec "$PYTHON" -m agent_os.desktop
EOF
chmod +x "$APP/Contents/MacOS/agent-os"

cp "$ROOT/scripts/AgentOS.icns" "$APP/Contents/Resources/AgentOS.icns"

echo "Listo: $APP"
echo "Arrástrala al Dock o a /Applications si quieres."
