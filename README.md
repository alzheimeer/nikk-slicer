# Nikk Slicer

[![macOS Apple Silicon & Intel](https://img.shields.io/badge/macOS-Apple%20Silicon%20%7C%20Intel-000000?logo=apple&logoColor=white)](https://github.com/alzheimeer/nikk-slicer/releases/latest)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React + Three.js](https://img.shields.io/badge/Frontend-React%20%2B%20Three.js-61DAFB?logo=react&logoColor=000000)](https://react.dev/)
[![DeepSeek AI](https://img.shields.io/badge/AI%20Copilot-DeepSeek%20API-4D6BFE)](https://www.deepseek.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Download macOS DMG](https://img.shields.io/badge/Download-NikkSlicer%20v1.3.0%20(.dmg)-22c55e?logo=apple&logoColor=white)](https://github.com/alzheimeer/nikk-slicer/releases/latest)

> **Unified 3D Slicer & Multi-Printer Farm Monitor for macOS — FLSUN Klipper/Moonraker + FlashForge LAN**  
> Native desktop app (`Nikk Slicer.app`) with multi-extruder `T0–T3` support, triangle-painted `.3mf` WebGL preview, Lithophane mode, automated AI support optimization, and continuous `0% → 100%` telemetry recording with DeepSeek AI post-print compendiums.

**Laminador 3D unificado, visor WebGL multicolor y centro de control de granja FDM con Copiloto IA (DeepSeek API) para macOS.**

📥 **Descarga directa para macOS (Apple Silicon M1–M4 e Intel):** [**NikkSlicer_macOS_Installer.dmg (v1.3.0)**](https://github.com/alzheimeer/nikk-slicer/releases/latest)

Nikk Slicer integra en una sola aplicación nativa (`Nikk Slicer.app`) un flujo de trabajo completo desde el análisis geométrico de archivos `.STL` y `.3MF` hasta el laminado headless con **Flash Studio / OrcaSlicer**, envío directo por red/USB/SD y monitoreo continuo en tiempo real con aprendizaje automático tras cada impresión.

---

## Galería de Interfaces

| Laminador (Wizard) | Visor 3D Multicolor (`T0–T3` · `paint_color`) |
| :---: | :---: |
| ![Laminador Wizard](docs/screenshots/01-laminador-wizard.png) | ![Visor 3D Multicolor](docs/screenshots/02-visor-3d-multicolor.png) |

| Modo Litofanía (Alta Definición) | Monitor en Vivo & Compendios IA |
| :---: | :---: |
| ![Modo Litofanía](docs/screenshots/03-modo-litofania.png) | ![Monitor en Vivo](docs/screenshots/04-monitor-en-vivo.png) |

---

## Características Principales

- **Laminado Inteligente con Perfiles Dinámicos:**
  - Cálculo automático de temperaturas (`1.ª Capa` e `Impresión`) a partir de los límites de caudal volumétrico (`mm³/s`), modo **Alta Velocidad (HS)**, diámetro de boquilla (`0.2 / 0.4 / 0.6 / 0.8 mm`) y el rango térmico de cada carrete (`min–max °C`).
  - Generadores de ancho de línea y altura de capa adaptativos, más perfiles dinámicos (`Arachne + Gyroid`, puenteo optimizado y separación calibrada de soportes Z/XY por material).
- **Soporte con IA (Antes vs. Después Real):**
  - Al pulsar **Soporte con IA (Ángulo Anti-Soportes)**, el sistema evalúa candidatos de orientación con `trimesh`, aplica la rotación y configuración recomendadas, **re-lamina realmente** en segundo plano y compara tiempo, gramos totales y peso de soporte contra el corte previo; si no mejora, revierte automáticamente a la configuración original.
- **Multicabezal 4 Extrusores (`T0–T3`) para FlashForge Creator 5 Pro:**
  - Decodificación nativa de archivos **`.3mf` pintados por triángulo** (`paint_color` de Bambu/Orca/Meshy AI y `pid`/`p1`) tanto en el visor 3D (sin sangrado entre vértices) como en el laminador headless.
  - Configuración térmica, de material (`PLA`, `PETG`, `ABS`, `TPU 95A`, `Soporte`), modo `HS`, rango de carrete y retracción **independiente por cabezal (`T0–T3`)**.
  - Negociación automática de temperatura de cama y techo de velocidades lineales gobernado por el carrete de menor caudal volumétrico (`mm³/s`), alertas de incompatibilidad entre materiales y **Torre de Purga Ultra-Ahorro** (`20 mm` + purga en relleno y soportes).
- **Modo Litofanía (Alta Definición a Contraluz):**
  - Bloqueo automático a **PLA / PLA HS**, capa fina (`0.12 mm`), relleno **`99%` rectilíneo**, 6 perímetros (`Arachne`), costura trasera, brim exterior de `8 mm`, desactivación de soportes sobre la cara de imagen y velocidades/aceleraciones anti-ringing por cinemática.
- **Monitor en Vivo y Aprendizaje Continuo con DeepSeek API:**
  - **Grabador continuo (`0% → 100%`)** en segundo plano: guarda muestras cada 20 s y en hitos de progreso (`backend/temp/telemetry_sessions/`).
  - Al finalizar la impresión (o bajo demanda a mitad de corrida), genera un **Compendio Final IA** por fases (`0–5%`, `5–85%`, `85–100%`) con calificación (`EXCELENTE`, `BUENA_CON_MEJORAS`, `REQUIERE_AJUSTE`) y mejoras concretas para el siguiente laminado.
  - **Aprendizaje real acumulado (`GET /api/telemetry/learnings`):** el historial completado (`completed_compendiums.json`) retroalimenta automáticamente a DeepSeek en el Paso 3 del Laminador según máquina y material.
  - Control aislado de **Luz LED**, gestor de **archivos remotos** (subir sin imprimir, subir e imprimir con/sin nivelación), reproductor/descarga de **Timelapses `.mp4`** y cancelación real (`END_PRINT` en Moonraker / FlashForge LAN).

---

## Impresoras Soportadas y Protocolos

| Impresora | Perfil Base | Cinemática | Volumen | Protocolo |
| :--- | :--- | :--- | :--- | :--- |
| **FLSUN T1 Pro #1 / #2** | `flsun_t1_pro` | Delta Klipper | `Ø260 × 330 mm` | Moonraker HTTP (`:7125`) + Cámara MJPEG |
| **FLSUN V400** | `flsun_v400` | Delta Klipper | `Ø300 × 410 mm` | Moonraker HTTP (`:80`) + Cámara MJPEG |
| **FlashForge Creator 5 Pro** | `creator5_pro` | CoreXY 4-Tool (`T0–T3`) | `256 × 256 × 256 mm` | FlashForge LAN (`:8898` / TCP `:8899`) |
| **FLSUN Super Racer** | `flsun_sr` | Delta Marlin/Klipper | `Ø260 × 330 mm` | USB Serial (`pyserial`) / SD |
| **Creality Ender 3 S1 Pro** | `ender3_s1_pro` | Cartesiana Marlin 2 | `220 × 220 × 270 mm` | USB Serial (`pyserial`) / Volumen SD |

---

## Arquitectura del Proyecto

```text
MaoSlicer/
├── backend/
│   ├── app/
│   │   ├── main.py                      # API FastAPI + servidor SPA unificado (:8000)
│   │   ├── config.py                    # Catálogo, temperaturas óptimas y negociación T0–T3
│   │   ├── connectors/                  # moonraker.py, flashforge_lan.py, marlin_serial.py
│   │   ├── core/                        # mesh_analyzer.py, json_patcher.py, slicer_router.py,
│   │   │                                # ai_copilot.py, print_telemetry_recorder.py
│   │   └── models/schemas.py            # Esquemas Pydantic
│   ├── profiles/                        # Perfiles JSON maestros (machines, filaments, process)
│   ├── printers_config.json             # IPs, puertos y metadatos de granja
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/components/                  # SlicerWizard.tsx, Viewport3D.tsx, FarmDashboard.tsx, etc.
│   ├── src/services/api.ts
│   ├── src/utils/threeMfPaint.ts        # Decodificador 3MF pintado por triángulo (WebGL)
│   └── dist/                            # Build React/Vite listo para servir desde FastAPI
├── docs/screenshots/                    # Capturas reales de la aplicación
├── desktop_launcher.py                  # Lanzador nativo macOS (puerto 8000 + ventana dedicada)
├── build_macos_app.sh                   # Empaquetador de Nikk Slicer.app + NikkSlicer.icns
├── install_on_mac.sh                    # Instalador automático (.venv + .env + Nikk Slicer.app)
├── package_release.sh                   # Generador de DMG y ZIP distribuibles
└── README.md
```

---

## Instalación en Otro Mac (Apple Silicon M1/M2/M3/M4 e Intel)

> **Requisitos previos en el Mac destino:**
> 1. **Python 3.10+** (`brew install python@3.11`).
> 2. **Flash Studio** (`/Applications/Flash Studio.app`) para el motor CLI headless de laminado.
> 3. **Google Chrome** (o `pywebview` opcional en `.venv`) para la ventana de escritorio dedicada.

### Método A: Instalación en un clic con `NikkSlicer_macOS_Installer.dmg`
1. Descarga **`NikkSlicer_macOS_Installer.dmg`** desde [GitHub Releases](https://github.com/alzheimeer/nikk-slicer/releases/latest) (o usa `dist_release/NikkSlicer_macOS_Installer.dmg`) y ábrelo con doble clic.
2. Ejecuta **`Instalar_Nikk_Slicer.command`** (copiará el proyecto a `~/Apps/NikkSlicer`, creará el `.venv`, instalará dependencias e instalará **`/Applications/Nikk Slicer.app`**).
3. Edita `~/Apps/NikkSlicer/backend/.env` y pega tu clave **`DEEPSEEK_API_KEY=...`**.
4. Abre **Nikk Slicer** desde `/Applications/Nikk Slicer.app` o desde el Dock.

### Método B: Clonado desde GitHub
```bash
git clone https://github.com/alzheimeer/nikk-slicer.git
cd nikk-slicer
./install_on_mac.sh
```
Luego edita `backend/.env` con tu `DEEPSEEK_API_KEY` y abre **`/Applications/Nikk Slicer.app`**.

### Método C: Acceso Directo por Red Local (sin instalar en el segundo Mac)
Si `NIKKSLICER_HOST=0.0.0.0` y `NIKKSLICER_PORT=8000` están configurados en `backend/.env`, basta con abrir Nikk Slicer en el Mac principal y entrar desde el navegador de cualquier otro Mac o iPad de tu red local en:
```text
http://<IP_DEL_MAC_PRINCIPAL>:8000
```

---

## Actualizar y Recompilar tras Cambios en el Código

- **Recompilar frontend y actualizar `Nikk Slicer.app` + `/Applications/Nikk Slicer.app`:**
  ```bash
  ./build_macos_app.sh
  ```
- **Generar nuevos instaladores `.dmg` y `.zip` en `dist_release/`:**
  ```bash
  ./package_release.sh
  ```

---

**Creador:** Niklauss Mauricio Quintero · `niklaussmauricio@gmail.com`
