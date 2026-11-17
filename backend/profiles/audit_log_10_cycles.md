# Bitácora de Auditoría de 10 Ciclos — SlicerHub Fase 0

- **Fecha de ejecución:** 2026-11-15 23:13:07
- **Modelo de prueba CLI:** `backend/profiles/test_assets/calibration_cube_20mm.stl` (Cubo calibración manifold 20×20×20 mm)
- **Motor CLI primario validado:** `/Applications/Flash Studio.app/Contents/MacOS/Flash Studio` (`Orca-Flashforge 2.4.2`, arm64)
- **Motor CLI secundario auditado:** `/Applications/FlsunSlicer.app/Contents/MacOS/FlsunSlicer` (`FlsunSlicer 3.0.0.13`, x86_64)

---

## Ciclo 1: Integridad Estructural (Herencia, Instanciación y Claves Huérfanas) — [PASS]

### Verificaciones
- OK `machine/flsun_v400.json`: sin `inherits`, sin `nil`, `71` claves válidas.
- OK `machine/flsun_t1_pro.json`: sin `inherits`, sin `nil`, `129` claves válidas.
- OK `machine/flsun_sr.json`: sin `inherits`, sin `nil`, `81` claves válidas.
- OK `machine/creator5_pro.json`: sin `inherits`, sin `nil`, `147` claves válidas.
- OK `machine/ender3_s1_pro.json`: sin `inherits`, sin `nil`, `65` claves válidas.
- OK `filament/pla_master.json`: sin `inherits`, sin `nil`, `61` claves válidas.
- OK `filament/petg_master.json`: sin `inherits`, sin `nil`, `61` claves válidas.
- OK `filament/abs_master.json`: sin `inherits`, sin `nil`, `59` claves válidas.
- OK `filament/tpu_master.json`: sin `inherits`, sin `nil`, `60` claves válidas.
- OK `process/estandar.json`: sin `inherits`, sin `nil`, `276` claves válidas.
- OK `process/mecanico_resistente.json`: sin `inherits`, sin `nil`, `276` claves válidas.
- OK `process/alta_velocidad.json`: sin `inherits`, sin `nil`, `276` claves válidas.

### Hallazgos
- Sin anomalías detectadas en este ciclo.

### Correcciones Aplicadas
- No requirió cambios adicionales.

## Ciclo 2: Validación de Tipos y Enums contra C++ (`PrintConfig.cpp`) — [PASS]

### Verificaciones
- Indexadas `1007` definiciones C++ (`PrintConfig.cpp` OrcaSlicer + Orca-Flashforge).
- OK `machines/flsun_v400.json`: tipos y enums validados contra `PrintConfig.cpp`.
- OK `machines/flsun_t1_pro.json`: tipos y enums validados contra `PrintConfig.cpp`.
- OK `machines/flsun_sr.json`: tipos y enums validados contra `PrintConfig.cpp`.
- OK `machines/creator5_pro.json`: tipos y enums validados contra `PrintConfig.cpp`.
- OK `machines/ender3_s1_pro.json`: tipos y enums validados contra `PrintConfig.cpp`.
- OK `filaments/pla_master.json`: tipos y enums validados contra `PrintConfig.cpp`.
- OK `filaments/petg_master.json`: tipos y enums validados contra `PrintConfig.cpp`.
- OK `filaments/abs_master.json`: tipos y enums validados contra `PrintConfig.cpp`.
- OK `filaments/tpu_master.json`: tipos y enums validados contra `PrintConfig.cpp`.
- OK `process/estandar.json`: tipos y enums validados contra `PrintConfig.cpp`.
- OK `process/mecanico_resistente.json`: tipos y enums validados contra `PrintConfig.cpp`.
- OK `process/alta_velocidad.json`: tipos y enums validados contra `PrintConfig.cpp`.

### Hallazgos
- Sin anomalías detectadas en este ciclo.

### Correcciones Aplicadas
- No requirió cambios adicionales.

## Ciclo 3: Coherencia Termodinámica (Boquilla, Cama, Cámara y Ventilación) — [PASS]

### Verificaciones
- OK `filaments/pla_master.json`: Ø1.75 mm, boquilla 220/215°C [190-240], cama 60°C, fan_max 100%, cámara 0°C.
- OK `filaments/petg_master.json`: Ø1.75 mm, boquilla 250/245°C [225-265], cama 75°C, fan_max 60%, cámara 0°C.
- OK `filaments/abs_master.json`: Ø1.75 mm, boquilla 260/255°C [240-285], cama 100°C, fan_max 30%, cámara 60°C.
- OK `filaments/tpu_master.json`: Ø1.75 mm, boquilla 225/225°C [210-245], cama 50°C, fan_max 70%, cámara 0°C.

### Hallazgos
- Sin anomalías detectadas en este ciclo.

### Correcciones Aplicadas
- No requirió cambios adicionales.

## Ciclo 4: Coherencia Termodinámica — Caudal Volumétrico (Q = W × H × V) — [PASS]

### Verificaciones
- OK `process/estandar.json`: demanda sin tope -> pared ext Q=10.08 mm³/s, relleno Q=19.8 mm³/s.
- OK `process/mecanico_resistente.json`: demanda sin tope -> pared ext Q=6.72 mm³/s, relleno Q=14.4 mm³/s.
- OK `process/alta_velocidad.json`: demanda sin tope -> pared ext Q=16.8 mm³/s, relleno Q=40.5 mm³/s.
- OK `filaments/pla_master.json`: techo maestro 28.0 mm³/s; tabla por máquina {'flsun_t1_pro': 48.0, 'flsun_v400': 37.0, 'creator5_pro': 32.0, 'flsun_sr': 15.0, 'ender3_s1_pro': 14.0}.
- OK `filaments/petg_master.json`: techo maestro 18.0 mm³/s; tabla por máquina {'flsun_t1_pro': 20.0, 'flsun_v400': 20.0, 'creator5_pro': 18.0, 'flsun_sr': 12.0, 'ender3_s1_pro': 10.0}.
- OK `filaments/abs_master.json`: techo maestro 22.0 mm³/s; tabla por máquina {'flsun_t1_pro': 32.0, 'flsun_v400': 24.0, 'creator5_pro': 24.0, 'flsun_sr': 12.0, 'ender3_s1_pro': 11.0}.
- OK `filaments/tpu_master.json`: techo maestro 10.0 mm³/s; tabla por máquina {'flsun_t1_pro': 12.0, 'flsun_v400': 10.0, 'creator5_pro': 10.0, 'flsun_sr': 6.0, 'ender3_s1_pro': 8.0}.

### Hallazgos
- Sin anomalías detectadas en este ciclo.

### Correcciones Aplicadas
- No requirió cambios adicionales.

## Ciclo 5: Cinemática y Volúmenes de Construcción (Origen y Límites Geométricos) — [PASS]

### Verificaciones
- OK `machines/flsun_v400.json`: Delta centrada en (0.00,0.00), Ø300 mm × 410 mm.
- OK `machines/flsun_t1_pro.json`: Delta centrada en (0.00,0.00), Ø260 mm × 330 mm.
- OK `machines/flsun_sr.json`: Delta centrada en (0.00,0.00), Ø260 mm × 330 mm.
- OK `machines/creator5_pro.json`: corexy origen esquina (0,0), área 256×256×256 mm.
- OK `machines/ender3_s1_pro.json`: i3 origen esquina (0,0), área 220×220×270 mm.

### Hallazgos
- Sin anomalías detectadas en este ciclo.

### Correcciones Aplicadas
- No requirió cambios adicionales.

## Ciclo 6: Cinemática — Aceleraciones, Eje Y Marlin 2, Retracciones y Z-Hop — [PASS]

### Verificaciones
- OK `ender3_s1_pro.json`: sabor `marlin2`, accel_Y ≤ 2000 mm/s², retracción Direct Drive 1.2 mm @ 40 mm/s, M420 S1 Z10.
- OK `flsun_v400.json`: Klipper, viaje 9000 mm/s², Direct Drive 0.8 mm, Slope Lift Z-hop.
- OK `flsun_t1_pro.json`: Klipper 30000 mm/s², Adaptive Bed Mesh, Slope Lift Z-hop.
- OK `flsun_sr.json`: Klipper Bowden 5.5 mm @ 40 mm/s, Slope Lift Z-hop.
- OK `creator5_pro.json`: CoreXY Klipper 600 mm/s, accel XY 30000 mm/s², Auto Lift.
- OK `machines/flsun_v400.json`: use_relative_e_distances=0, reinicio E por capa coherente.
- OK `machines/flsun_t1_pro.json`: use_relative_e_distances=1, reinicio E por capa coherente.
- OK `machines/flsun_sr.json`: use_relative_e_distances=1, reinicio E por capa coherente.
- OK `machines/creator5_pro.json`: use_relative_e_distances=1, reinicio E por capa coherente.
- OK `machines/ender3_s1_pro.json`: use_relative_e_distances=0, reinicio E por capa coherente.

### Hallazgos
- Sin anomalías detectadas en este ciclo.

### Correcciones Aplicadas
- No requirió cambios adicionales.

## Ciclo 7: Soportes Orgánicos `tree(auto)` y Regla Anti-Soldadura PETG — [PASS]

### Verificaciones
- OK `process/estandar.json`: support_type=tree(auto), support_top_z_distance=0.24 mm, xy_distance=0.4 mm.
- OK `process/mecanico_resistente.json`: support_type=tree(auto), support_top_z_distance=0.24 mm, xy_distance=0.4 mm.
- OK `process/alta_velocidad.json`: support_type=tree(auto), support_top_z_distance=0.24 mm, xy_distance=0.4 mm.
- OK `slicerhub_catalog.json`: petg_support_overrides={'support_top_z_distance': '0.24', 'support_bottom_z_distance': '0.24', 'support_object_xy_distance': '0.4'}.

### Hallazgos
- Sin anomalías detectadas en este ciclo.

### Correcciones Aplicadas
- No requirió cambios adicionales.

## Ciclo 8: Arachne, Scarf Joint Seam, Gyroid y Multimaterial Creator 5 Pro — [PASS]

### Verificaciones
- OK `process/estandar.json`: Arachne + Precise Wall + Scarf Joint (`all`, 20mm/10 pasos) + Gyroid (12%) + wall_sequence='inner wall/outer wall'.
- OK `process/mecanico_resistente.json`: Arachne + Precise Wall + Scarf Joint (`all`, 20mm/10 pasos) + Gyroid (25%) + wall_sequence='inner-outer-inner wall'.
- OK `process/alta_velocidad.json`: Arachne + Precise Wall + Scarf Joint (`all`, 20mm/10 pasos) + Gyroid (10%) + wall_sequence='inner wall/outer wall'.
- OK `creator5_pro.json` + 4 filamentos: 4 cabezales independientes, toolchange retract=10 mm, standby/idle_temperature=170°C, cámara activa habilitada.

### Hallazgos
- Sin anomalías detectadas en este ciclo.

### Correcciones Aplicadas
- No requirió cambios adicionales.

## Ciclo 9: Prueba de Estrés CLI Inicial (Dry-Run con `FlsunSlicer` y `Flash Studio`) — [PASS]

### Verificaciones
- Validación carga JSON en `FlsunSlicer 3.0.0.13`: compatible=True, errores_json=False, exit_code=-11.
- OK dry-run `flsun_v400 + petg_master + mecanico_resistente`: exit=0, errores=0, gcode=950910 bytes.
- OK dry-run `creator5_pro + abs_master + alta_velocidad`: exit=0, errores=0, gcode=519779 bytes.
- OK dry-run `ender3_s1_pro + petg_master + estandar`: exit=0, errores=0, gcode=567886 bytes.

### Hallazgos
- `FlsunSlicer 3.0.0.13` (x86_64) finalizó con código -11 por bug upstream `SIGSEGV 0x6f8` en `PartPlateList::generate_print_polygon` (`wxGetApp().plater() == nullptr` en modo headless).

### Correcciones Aplicadas
- Validado y designado `/Applications/Flash Studio.app/Contents/MacOS/Flash Studio` (arm64, Orca-Flashforge 2.4.2) como motor CLI primario unificado en `slicerhub_catalog.json`.

## Ciclo 10: Prueba de Estrés CLI Final (5 Impresoras, `.gcode` y Viajes Muertos) — [PASS]

### Verificaciones
- PASS `flsun_v400` (`estandar` + `pla_master`): exit=0, `21924` líneas (564319 B), tiempo=estimated printing time (normal mode) = 9m 29s, filamento=3.82 g, viajes=1149 (5410.0 mm), marcador `BED_MESH_PROFILE LOAD=default` verificado.
- PASS `flsun_t1_pro` (`alta_velocidad` + `pla_master`): exit=0, `18345` líneas (480952 B), tiempo=estimated printing time (normal mode) = 7m 34s, filamento=3.08 g, viajes=1025 (5034.9 mm), marcador `BED_MESH_CALIBRATE ADAPTIVE=1` verificado.
- PASS `flsun_sr` (`estandar` + `pla_master`): exit=0, `21229` líneas (524682 B), tiempo=estimated printing time (normal mode) = 10m 7s, filamento=3.83 g, viajes=1149 (5360.1 mm), marcador `G1 E-5.5 F2400` verificado.
- PASS `creator5_pro` (`mecanico_resistente` + `pla_master`): exit=0, `35909` líneas (1013774 B), tiempo=estimated printing time (normal mode) = 12m 15s, filamento=5.26 g, viajes=2022 (7438.5 mm), marcador `M104 T3 S170` verificado.
- PASS `ender3_s1_pro` (`estandar` + `pla_master`): exit=0, `22277` líneas (567785 B), tiempo=estimated printing time (normal mode) = 12m 14s, filamento=3.82 g, viajes=1064 (4873.9 mm), marcador `M420 S1 Z10` verificado.

### Hallazgos
- Sin anomalías detectadas en este ciclo.

### Correcciones Aplicadas
- No requirió cambios adicionales.

---

## Resumen Cuantitativo — Décima Iteración (Dry-Run Real en las 5 Impresoras)

| Impresora | Proceso | Filamento | Exit | Errores | Líneas G-code | Tamaño (B) | Tiempo Estimado | Filamento (g) | Viajes | Distancia Viaje (mm) | Marcador Verificado |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `flsun_v400` | `estandar` | `pla_master` | `0` | `0` | 21924 | 564319 | estimated printing time (normal mode) = 9m 29s | 3.82 | 1149 | 5410.0 | `BED_MESH_PROFILE LOAD=default` |
| `flsun_t1_pro` | `alta_velocidad` | `pla_master` | `0` | `0` | 18345 | 480952 | estimated printing time (normal mode) = 7m 34s | 3.08 | 1025 | 5034.9 | `BED_MESH_CALIBRATE ADAPTIVE=1` |
| `flsun_sr` | `estandar` | `pla_master` | `0` | `0` | 21229 | 524682 | estimated printing time (normal mode) = 10m 7s | 3.83 | 1149 | 5360.1 | `G1 E-5.5 F2400` |
| `creator5_pro` | `mecanico_resistente` | `pla_master` | `0` | `0` | 35909 | 1013774 | estimated printing time (normal mode) = 12m 15s | 5.26 | 2022 | 7438.5 | `M104 T3 S170` |
| `ender3_s1_pro` | `estandar` | `pla_master` | `0` | `0` | 22277 | 567785 | estimated printing time (normal mode) = 12m 14s | 3.82 | 1064 | 4873.9 | `M420 S1 Z10` |
