#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_BUNDLE="${PROJECT_DIR}/Nikk Slicer.app"
RELEASE_DIR="${PROJECT_DIR}/dist_release"
DMG_PATH="${RELEASE_DIR}/NikkSlicer_macOS.dmg"
STAGING_DIR="$(mktemp -d /tmp/NikkSlicer_dmg_staging.XXXXXX)"

cleanup() {
  rm -rf "${STAGING_DIR}"
}
trap cleanup EXIT

echo "==> 1. Construyendo Nikk Slicer.app autónomo..."
"${PROJECT_DIR}/build_macos_app.sh"

if [[ ! -d "${APP_BUNDLE}" ]]; then
  echo "Error: no se encontró ${APP_BUNDLE}" >&2
  exit 1
fi

echo "==> 2. Preparando staging para DMG..."
mkdir -p "${RELEASE_DIR}"
rm -f "${DMG_PATH}"
cp -R "${APP_BUNDLE}" "${STAGING_DIR}/Nikk Slicer.app"
ln -s /Applications "${STAGING_DIR}/Applications"

echo "==> 3. Generando ${DMG_PATH} (UDZO comprimido)..."
hdiutil create \
  -volname "Nikk Slicer" \
  -srcfolder "${STAGING_DIR}" \
  -ov \
  -format UDZO \
  "${DMG_PATH}"

echo "==> DMG generado exitosamente: ${DMG_PATH}"
ls -lh "${DMG_PATH}"
