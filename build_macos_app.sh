#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_BUNDLE="${PROJECT_DIR}/Nikk Slicer.app"
LEGACY_APP_BUNDLE="${PROJECT_DIR}/SlicerHub.app"
BUILD_WORK_DIR="$(mktemp -d /tmp/NikkSlicer_pyi_build.XXXXXX)"
DIST_TMP_DIR="$(mktemp -d /tmp/NikkSlicer_pyi_dist.XXXXXX)"
ICONSET_PARENT="$(mktemp -d /tmp/NikkSlicer_iconset.XXXXXX)"
ICONSET_DIR="${ICONSET_PARENT}/NikkSlicer.iconset"
ICON_ICNS="${ICONSET_PARENT}/NikkSlicer.icns"
LOGO_SRC="${PROJECT_DIR}/frontend/public/nikk-logo.jpg"

cleanup() {
  rm -rf "${BUILD_WORK_DIR}" "${DIST_TMP_DIR}" "${ICONSET_PARENT}"
}
trap cleanup EXIT

if [[ -x "${PROJECT_DIR}/backend/.venv/bin/python" ]]; then
  PYTHON_BIN="${PROJECT_DIR}/backend/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

echo "==> 1. Compilando frontend React (npm run build)..."
(cd "${PROJECT_DIR}/frontend" && npm run build)

echo "==> 2. Validando sintaxis de desktop_launcher.py..."
"${PYTHON_BIN}" -m py_compile "${PROJECT_DIR}/desktop_launcher.py"

if ! "${PYTHON_BIN}" -c "import PyInstaller" >/dev/null 2>&1; then
  echo "==> Instalando PyInstaller en el entorno Python..."
  "${PYTHON_BIN}" -m pip install pyinstaller
fi

echo "==> 3. Generando icono nativo NikkSlicer.icns con sips + iconutil..."
mkdir -p "${ICONSET_DIR}"
BASE_PNG="${ICONSET_DIR}/_base_1024.png"
if [[ -f "${LOGO_SRC}" ]]; then
  sips -s format png -z 1024 1024 "${LOGO_SRC}" --out "${BASE_PNG}" >/dev/null
else
  "${PYTHON_BIN}" - <<PY
import struct, zlib
w, h = 1024, 1024
row = b"\x00" + b"\x0f\x17\x2a\xff" * w
raw = row * h
def chunk(tag, data):
    return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", zlib.crc32(tag + data) & 0xffffffff)
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
open("${BASE_PNG}", "wb").write(png)
PY
fi

for sz in 16 32 128 256 512; do
  sips -z "${sz}" "${sz}" "${BASE_PNG}" --out "${ICONSET_DIR}/icon_${sz}x${sz}.png" >/dev/null
  sz2=$((sz * 2))
  sips -z "${sz2}" "${sz2}" "${BASE_PNG}" --out "${ICONSET_DIR}/icon_${sz}x${sz}@2x.png" >/dev/null
done
rm -f "${BASE_PNG}"
iconutil -c icns "${ICONSET_DIR}" -o "${ICON_ICNS}"

echo "==> 4. Limpiando bundles anteriores y empaquetando Nikk Slicer.app (100% autónomo con PyInstaller)..."
rm -rf "${APP_BUNDLE}" "${LEGACY_APP_BUNDLE}"
if [[ -L "/Applications/SlicerHub.app" || -d "/Applications/SlicerHub.app" ]]; then
  rm -rf "/Applications/SlicerHub.app" 2>/dev/null || true
fi

"${PYTHON_BIN}" -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --windowed \
  --name "Nikk Slicer" \
  --icon "${ICON_ICNS}" \
  --osx-bundle-identifier "com.nikk.nikkslicer" \
  --distpath "${DIST_TMP_DIR}" \
  --workpath "${BUILD_WORK_DIR}" \
  --specpath "${BUILD_WORK_DIR}" \
  --add-data "${PROJECT_DIR}/frontend/dist:frontend/dist" \
  --add-data "${PROJECT_DIR}/frontend/public/nikk-logo.jpg:frontend/public" \
  --add-data "${PROJECT_DIR}/backend/app:backend/app" \
  --add-data "${PROJECT_DIR}/backend/profiles:backend/profiles" \
  --add-data "${PROJECT_DIR}/backend/printers_config.json:backend" \
  --hidden-import "uvicorn.logging" \
  --hidden-import "uvicorn.loops" \
  --hidden-import "uvicorn.loops.auto" \
  --hidden-import "uvicorn.protocols" \
  --hidden-import "uvicorn.protocols.http" \
  --hidden-import "uvicorn.protocols.http.auto" \
  --hidden-import "uvicorn.lifespan.on" \
  --hidden-import "fastapi" \
  --hidden-import "pydantic" \
  --hidden-import "httpx" \
  --hidden-import "trimesh" \
  --hidden-import "webview" \
  --hidden-import "mcp.server.mcpserver" \
  --collect-submodules "mcp.server" \
  --collect-submodules "mcp.shared" \
  --collect-submodules "mcp.types" \
  --exclude-module "mcp.cli" \
  --collect-submodules "webview" \
  "${PROJECT_DIR}/desktop_launcher.py"

mv "${DIST_TMP_DIR}/Nikk Slicer.app" "${APP_BUNDLE}"

CONTENTS_DIR="${APP_BUNDLE}/Contents"
echo "==> 5. Actualizando Contents/Info.plist (.3mf, .stl, .nikkproj)..."
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
  <string>Nikk Slicer requiere acceso a tus modelos STL, 3MF y proyectos para laminarlos.</string>
  <key>CFBundleDocumentTypes</key>
  <array>
    <dict>
      <key>CFBundleTypeExtensions</key>
      <array>
        <string>stl</string>
        <string>STL</string>
      </array>
      <key>CFBundleTypeName</key>
      <string>STL 3D Model</string>
      <key>CFBundleTypeOSTypes</key>
      <array>
        <string>****</string>
      </array>
      <key>CFBundleTypeRole</key>
      <string>Editor</string>
      <key>LSHandlerRank</key>
      <string>Alternate</string>
      <key>LSItemContentTypes</key>
      <array>
        <string>public.standard-tesselated-geometry-format</string>
        <string>public.3d-content</string>
        <string>public.data</string>
        <string>public.item</string>
      </array>
    </dict>
    <dict>
      <key>CFBundleTypeExtensions</key>
      <array>
        <string>3mf</string>
        <string>3MF</string>
      </array>
      <key>CFBundleTypeName</key>
      <string>3MF 3D Manufacturing Format</string>
      <key>CFBundleTypeOSTypes</key>
      <array>
        <string>****</string>
      </array>
      <key>CFBundleTypeRole</key>
      <string>Editor</string>
      <key>LSHandlerRank</key>
      <string>Alternate</string>
      <key>LSItemContentTypes</key>
      <array>
        <string>com.microsoft.3dmanufacturing-format</string>
        <string>public.3d-content</string>
        <string>public.zip-archive</string>
        <string>public.data</string>
        <string>public.item</string>
      </array>
    </dict>
    <dict>
      <key>CFBundleTypeExtensions</key>
      <array>
        <string>nikkproj</string>
        <string>NIKKPROJ</string>
      </array>
      <key>CFBundleTypeName</key>
      <string>Nikk Slicer Project</string>
      <key>CFBundleTypeOSTypes</key>
      <array>
        <string>****</string>
      </array>
      <key>CFBundleTypeRole</key>
      <string>Editor</string>
      <key>LSHandlerRank</key>
      <string>Owner</string>
      <key>LSItemContentTypes</key>
      <array>
        <string>com.nikk.nikkslicer.project</string>
        <string>public.json</string>
        <string>public.data</string>
      </array>
    </dict>
  </array>
</dict>
</plist>
PLIST

echo "==> 6. Aplicando firma ad-hoc limpia (codesign --force --deep --sign -)..."
codesign --force --deep --sign - "${APP_BUNDLE}"

if [[ -z "${CI:-}" && -w "/Applications" ]]; then
  ln -sfn "${APP_BUNDLE}" "/Applications/Nikk Slicer.app"
  echo "==> Enlace simbólico actualizado: /Applications/Nikk Slicer.app -> ${APP_BUNDLE}"
fi

LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [[ -x "${LSREGISTER}" ]]; then
  "${LSREGISTER}" -f "${APP_BUNDLE}" >/dev/null 2>&1 || true
fi

echo "==> Nikk Slicer.app generado exitosamente en ${APP_BUNDLE}"
