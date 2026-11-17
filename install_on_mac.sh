#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="${PROJECT_DIR}/backend"
FRONTEND_DIR="${PROJECT_DIR}/frontend"
VENV_DIR="${BACKEND_DIR}/.venv"

echo "=================================================="
echo "  Instalador Automático de Nikk Slicer (macOS)    "
echo "=================================================="

# 1. Verificar Python 3.10+
PYTHON_SYS=""
for cand in python3.12 python3.11 python3.10 python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "${cand}" >/dev/null 2>&1; then
    if "${cand}" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
      PYTHON_SYS="$(command -v "${cand}")"
      break
    fi
  fi
done

if [[ -z "${PYTHON_SYS}" ]]; then
  echo "Error: Se requiere Python 3.10 o superior."
  echo "Instálalo con Homebrew: brew install python@3.11"
  exit 1
fi
echo "==> Python detectado: ${PYTHON_SYS} ($("${PYTHON_SYS}" --version))"

# 2. Configurar archivo .env si no existe
if [[ ! -f "${BACKEND_DIR}/.env" && -f "${BACKEND_DIR}/.env.example" ]]; then
  cp "${BACKEND_DIR}/.env.example" "${BACKEND_DIR}/.env"
  echo "==> Archivo creado: ${BACKEND_DIR}/.env (edítalo para añadir tu DEEPSEEK_API_KEY)."
fi

# 3. Crear entorno virtual nativo e instalar dependencias Python
if [[ ! -d "${VENV_DIR}" ]]; then
  echo "==> Creando entorno virtual en ${VENV_DIR}..."
  "${PYTHON_SYS}" -m venv "${VENV_DIR}"
fi

echo "==> Instalando dependencias backend desde requirements.txt..."
"${VENV_DIR}/bin/python" -m pip install --upgrade pip >/dev/null
"${VENV_DIR}/bin/pip" install -r "${BACKEND_DIR}/requirements.txt"

# 4. Usar frontend/dist precompilado o compilar con npm si falta
if [[ ! -f "${FRONTEND_DIR}/dist/index.html" ]]; then
  if command -v npm >/dev/null 2>&1; then
    echo "==> Compilando frontend React (npm ci / npm run build)..."
    (cd "${FRONTEND_DIR}" && npm install && npm run build)
  else
    echo "Error: frontend/dist no existe y npm no está instalado para compilarlo."
    exit 1
  fi
else
  echo "==> Usando frontend/dist/ precompilado."
fi

# 5. Construir Nikk Slicer.app sin requerir npm si dist ya existe
APP_BUNDLE="${PROJECT_DIR}/Nikk Slicer.app"
if command -v npm >/dev/null 2>&1 && [[ -d "${FRONTEND_DIR}/node_modules" ]]; then
  chmod +x "${PROJECT_DIR}/build_macos_app.sh"
  "${PROJECT_DIR}/build_macos_app.sh"
else
  echo "==> Construyendo Nikk Slicer.app reutilizando frontend/dist/..."
  CONTENTS_DIR="${APP_BUNDLE}/Contents"
  MACOS_DIR="${CONTENTS_DIR}/MacOS"
  RESOURCES_DIR="${CONTENTS_DIR}/Resources"
  ICONSET_DIR="$(mktemp -d /tmp/NikkSlicer_iconset.XXXXXX)/NikkSlicer.iconset"
  LOGO_SRC="${FRONTEND_DIR}/public/nikk-logo.jpg"

  rm -rf "${APP_BUNDLE}" "${PROJECT_DIR}/SlicerHub.app"
  rm -rf "/Applications/SlicerHub.app" 2>/dev/null || true
  mkdir -p "${MACOS_DIR}" "${RESOURCES_DIR}" "${ICONSET_DIR}"

  BASE_PNG="${ICONSET_DIR}/_base_1024.png"
  if [[ -f "${LOGO_SRC}" ]]; then
    sips -s format png -z 1024 1024 "${LOGO_SRC}" --out "${BASE_PNG}" >/dev/null
    for sz in 16 32 128 256 512; do
      sips -z "${sz}" "${sz}" "${BASE_PNG}" --out "${ICONSET_DIR}/icon_${sz}x${sz}.png" >/dev/null
      sz2=$((sz * 2))
      sips -z "${sz2}" "${sz2}" "${BASE_PNG}" --out "${ICONSET_DIR}/icon_${sz}x${sz}@2x.png" >/dev/null
    done
    rm -f "${BASE_PNG}"
    iconutil -c icns "${ICONSET_DIR}" -o "${RESOURCES_DIR}/NikkSlicer.icns"
  fi
  rm -rf "$(dirname "${ICONSET_DIR}")"

  cat > "${CONTENTS_DIR}/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>es</string>
  <key>CFBundleDisplayName</key>
  <string>Nikk Slicer</string>
  <key>CFBundleExecutable</key>
  <string>Nikk Slicer</string>
  <key>CFBundleIconFile</key>
  <string>NikkSlicer</string>
  <key>CFBundleIdentifier</key>
  <string>com.nikk.nikkslicer</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Nikk Slicer</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.3.0</string>
  <key>CFBundleVersion</key>
  <string>1.3.0</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>LSUIElement</key>
  <false/>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSLocalNetworkUsageDescription</key>
  <string>Nikk Slicer requiere acceso a tu red local para controlar impresoras Klipper/Moonraker y FlashForge LAN.</string>
  <key>NSRemovableVolumesUsageDescription</key>
  <string>Nikk Slicer requiere acceso a volúmenes externos (tarjetas SD/USB) para guardar archivos G-code.</string>
  <key>NSDocumentsFolderUsageDescription</key>
  <string>Nikk Slicer requiere acceso a tus modelos STL y 3MF para laminarlos.</string>
</dict>
</plist>
PLIST

  cat > "${MACOS_DIR}/Nikk Slicer" <<EOF
#!/usr/bin/env bash
set -euo pipefail
LOG_DIR="\$HOME/Library/Logs/NikkSlicer"
mkdir -p "\$LOG_DIR"
cd "${PROJECT_DIR}"
exec "${VENV_DIR}/bin/python" "${PROJECT_DIR}/desktop_launcher.py" >> "\$LOG_DIR/launcher_boot.log" 2>&1
EOF
  chmod +x "${MACOS_DIR}/Nikk Slicer" "${PROJECT_DIR}/desktop_launcher.py"
  if [[ -w "/Applications" ]]; then
    ln -sfn "${APP_BUNDLE}" "/Applications/Nikk Slicer.app"
  fi
fi

echo ""
echo "✅ Instalación completada."
echo "   • App instalada en: ${APP_BUNDLE}"
if [[ -L "/Applications/Nikk Slicer.app" ]]; then
  echo "   • Acceso directo en: /Applications/Nikk Slicer.app"
fi
echo "   • Recuerda configurar tu DEEPSEEK_API_KEY en: ${BACKEND_DIR}/.env"
