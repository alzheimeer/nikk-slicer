#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_BUNDLE="${PROJECT_DIR}/Nikk Slicer.app"
LEGACY_APP_BUNDLE="${PROJECT_DIR}/SlicerHub.app"
CONTENTS_DIR="${APP_BUNDLE}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"
PYTHON_BIN="${PROJECT_DIR}/backend/.venv/bin/python"
LOGO_SRC="${PROJECT_DIR}/frontend/public/nikk-logo.jpg"
ICONSET_DIR="$(mktemp -d /tmp/NikkSlicer_iconset.XXXXXX)/NikkSlicer.iconset"

echo "==> 1. Compilando frontend React (npm run build)..."
(cd "${PROJECT_DIR}/frontend" && npm run build)

echo "==> 2. Validando sintaxis de desktop_launcher.py..."
"${PYTHON_BIN}" -m py_compile "${PROJECT_DIR}/desktop_launcher.py"

echo "==> 3. Limpiando bundles anteriores y construyendo ${APP_BUNDLE}..."
rm -rf "${APP_BUNDLE}" "${LEGACY_APP_BUNDLE}"
if [[ -L "/Applications/SlicerHub.app" || -d "/Applications/SlicerHub.app" ]]; then
  rm -rf "/Applications/SlicerHub.app" 2>/dev/null || true
fi
mkdir -p "${MACOS_DIR}" "${RESOURCES_DIR}" "${ICONSET_DIR}"

echo "==> 4. Generando icono nativo NikkSlicer.icns con sips + iconutil..."
BASE_PNG="${ICONSET_DIR}/_base_1024.png"
if [[ -f "${LOGO_SRC}" ]]; then
  sips -s format png -z 1024 1024 "${LOGO_SRC}" --out "${BASE_PNG}" >/dev/null
else
  echo "Aviso: no se encontró ${LOGO_SRC}; creando icono PNG por defecto."
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
iconutil -c icns "${ICONSET_DIR}" -o "${RESOURCES_DIR}/NikkSlicer.icns"
rm -rf "$(dirname "${ICONSET_DIR}")"

echo "==> 5. Escribiendo Contents/Info.plist..."
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
  </array>
</dict>
</plist>
PLIST

echo "==> 6. Escribiendo ejecutable Contents/MacOS/Nikk Slicer..."
cat > "${MACOS_DIR}/Nikk Slicer" <<EOF
#!/usr/bin/env bash
set -euo pipefail
LOG_DIR="\$HOME/Library/Logs/NikkSlicer"
mkdir -p "\$LOG_DIR"
cd "${PROJECT_DIR}"
exec "${PYTHON_BIN}" "${PROJECT_DIR}/desktop_launcher.py" >> "\$LOG_DIR/launcher_boot.log" 2>&1
EOF
chmod +x "${MACOS_DIR}/Nikk Slicer"
chmod +x "${PROJECT_DIR}/desktop_launcher.py"

if [[ -w "/Applications" ]]; then
  ln -sfn "${APP_BUNDLE}" "/Applications/Nikk Slicer.app"
  echo "==> Enlace simbólico actualizado: /Applications/Nikk Slicer.app -> ${APP_BUNDLE}"
fi

LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [[ -x "${LSREGISTER}" ]]; then
  "${LSREGISTER}" -f "${APP_BUNDLE}" >/dev/null 2>&1 || true
fi

echo "==> Nikk Slicer.app generado exitosamente en ${APP_BUNDLE}"
