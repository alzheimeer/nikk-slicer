# Empaquetador local de Nikk Slicer para Windows (Frontend + PyInstaller --onedir + .ico + Inno Setup)
$ErrorActionPreference = "Stop"

Write-Host "==> 1. Compilando frontend React (npm ci + npm run build)..."
Push-Location frontend
npm ci
npm run build
Pop-Location

Write-Host "==> 2. Instalando dependencias Python y PyInstaller..."
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
pip install pyinstaller pillow

Write-Host "==> 3. Generando icono multi-resolucion nikk_slicer.ico desde frontend/public/nikk-logo.jpg..."
python -c "from PIL import Image; img = Image.open('frontend/public/nikk-logo.jpg').convert('RGBA'); img.save('nikk_slicer.ico', format='ICO', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"

Write-Host "==> 4. Empaquetando 'Nikk Slicer' con PyInstaller (--onedir --windowed)..."
New-Item -ItemType Directory -Force -Path dist_win | Out-Null
New-Item -ItemType Directory -Force -Path dist_release | Out-Null

pyinstaller `
  --noconfirm `
  --clean `
  --onedir `
  --windowed `
  --name "Nikk Slicer" `
  --icon "nikk_slicer.ico" `
  --distpath "dist_win" `
  --add-data "frontend/dist;frontend/dist" `
  --add-data "backend;backend" `
  --add-data "nikk_slicer.ico;." `
  --paths "backend" `
  --hidden-import "app.main" `
  --hidden-import "uvicorn.logging" `
  --hidden-import "uvicorn.loops" `
  --hidden-import "uvicorn.loops.auto" `
  --hidden-import "uvicorn.protocols" `
  --hidden-import "uvicorn.protocols.http" `
  --hidden-import "uvicorn.protocols.http.auto" `
  --hidden-import "uvicorn.lifespan.on" `
  --hidden-import "fastapi" `
  --collect-submodules "fastapi" `
  --collect-submodules "starlette" `
  --hidden-import "pydantic" `
  --hidden-import "httpx" `
  --hidden-import "trimesh" `
  --hidden-import "serial" `
  --hidden-import "serial.tools.list_ports" `
  --hidden-import "multipart" `
  --hidden-import "webview" `
  --hidden-import "mcp.server.mcpserver" `
  --collect-submodules "mcp.server" `
  --collect-submodules "mcp.shared" `
  --collect-submodules "mcp.types" `
  --exclude-module "mcp.cli" `
  --collect-all "webview" `
  --collect-all "clr_loader" `
  --collect-all "pythonnet" `
  desktop_launcher.py

Copy-Item -Force "nikk_slicer.ico" "dist_win\Nikk Slicer\nikk_slicer.ico"
Write-Host "==> Build PyInstaller completado en dist_win/Nikk Slicer/"

$iscc = Get-Command "iscc.exe" -ErrorAction SilentlyContinue
if (-not $iscc) {
  $defaultIscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
  if (Test-Path $defaultIscc) {
    $iscc = Get-Item $defaultIscc
  }
}

if ($iscc) {
  Write-Host "==> 5. Compilando instalador con Inno Setup (installer_windows.iss)..."
  & $iscc installer_windows.iss
  Write-Host "==> Instalador generado: dist_release/NikkSlicer_Windows_Setup.exe"
} else {
  Write-Host "==> Inno Setup (ISCC.exe) no detectado localmente; omitiendo paso .exe instalador."
}
