#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
RELEASE_ROOT="${PROJECT_DIR}/dist_release"
STAGE_DIR="${RELEASE_ROOT}/NikkSlicer_Release"
DMG_PATH="${RELEASE_ROOT}/NikkSlicer_macOS_Installer.dmg"
ZIP_PATH="${RELEASE_ROOT}/NikkSlicer_macOS_Installer.zip"

echo "==> 1. Asegurando compilación actualizada del frontend..."
(cd "${PROJECT_DIR}/frontend" && npm run build)

echo "==> 2. Preparando directorio de distribución ${STAGE_DIR}..."
rm -rf "${STAGE_DIR}" "${DMG_PATH}" "${ZIP_PATH}"
mkdir -p "${STAGE_DIR}/backend" "${STAGE_DIR}/frontend" "${STAGE_DIR}/docs"

# Copiar backend limpio (sin .venv, temp, .env ni __pycache__)
rsync -a \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='temp' \
  --exclude='.env' \
  --exclude='.DS_Store' \
  "${PROJECT_DIR}/backend/" "${STAGE_DIR}/backend/"

# Copiar frontend compilado + código fuente (sin node_modules)
rsync -a \
  --exclude='node_modules' \
  --exclude='.DS_Store' \
  "${PROJECT_DIR}/frontend/" "${STAGE_DIR}/frontend/"

# Copiar documentación, capturas y scripts raíz
cp -R "${PROJECT_DIR}/docs/screenshots" "${STAGE_DIR}/docs/"
cp "${PROJECT_DIR}/README.md" "${STAGE_DIR}/"
cp "${PROJECT_DIR}/desktop_launcher.py" "${STAGE_DIR}/"
cp "${PROJECT_DIR}/build_macos_app.sh" "${STAGE_DIR}/"
cp "${PROJECT_DIR}/install_on_mac.sh" "${STAGE_DIR}/"
cp "${PROJECT_DIR}/.gitignore" "${STAGE_DIR}/"

chmod +x "${STAGE_DIR}/desktop_launcher.py" "${STAGE_DIR}/build_macos_app.sh" "${STAGE_DIR}/install_on_mac.sh"

# Crear lanzador de doble clic para instalación automática en ~/Apps/NikkSlicer
cat > "${STAGE_DIR}/Instalar_Nikk_Slicer.command" <<'CMD'
#!/usr/bin/env bash
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="$HOME/Apps/NikkSlicer"

echo "=================================================="
echo "  Instalando Nikk Slicer en $TARGET_DIR"
echo "=================================================="
mkdir -p "$TARGET_DIR"

rsync -a \
  --exclude='backend/.env' \
  --exclude='backend/.venv' \
  --exclude='backend/temp' \
  "$SRC_DIR/" "$TARGET_DIR/"

cd "$TARGET_DIR"
chmod +x install_on_mac.sh build_macos_app.sh desktop_launcher.py
./install_on_mac.sh

echo ""
echo "Abriendo Nikk Slicer..."
open "/Applications/Nikk Slicer.app" || open "$TARGET_DIR/Nikk Slicer.app"
CMD
chmod +x "${STAGE_DIR}/Instalar_Nikk_Slicer.command"

echo "==> 3. Generando ${DMG_PATH} con hdiutil..."
hdiutil create \
  -volname "Nikk Slicer Installer" \
  -srcfolder "${STAGE_DIR}" \
  -ov \
  -format UDZO \
  "${DMG_PATH}" >/dev/null

echo "==> 4. Generando ${ZIP_PATH} con ditto..."
ditto -c -k --sequesterRsrc --keepParent "${STAGE_DIR}" "${ZIP_PATH}"

echo ""
echo "✅ Paquetes de distribución generados:"
ls -lh "${DMG_PATH}" "${ZIP_PATH}"
