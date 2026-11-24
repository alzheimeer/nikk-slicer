export type Language = 'es' | 'en';

export const LANGUAGE_STORAGE_KEY = 'nikk_slicer_lang';

export function detectInitialLanguage(): Language {
  try {
    const saved = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (saved === 'es' || saved === 'en') return saved;
  } catch {
    // Ignore storage access errors
  }
  if (typeof navigator !== 'undefined' && navigator.language) {
    return navigator.language.toLowerCase().startsWith('es') ? 'es' : 'en';
  }
  return 'es';
}

export interface TranslationSchema {
  header: {
    wizard: string;
    liveMonitor: string;
    machines: string;
    quote: string;
    quoteTitle: string;
    journal: string;
    journalTitle: string;
    envMcp: string;
    envMcpTitle: string;
    settings: string;
    settingsTitle: string;
    languageTitle: string;
    newProjectTab: string;
    openInNewWindow: string;
    closeProject: string;
    closeProjectTitle: string;
  };
  startup: {
    title: string;
    subtitle: string;
    printerLabel: string;
    openProject: string;
    newProject: string;
    openLastProject: string;
  };
  projects: {
    galleryTitle: string;
    empty: string;
    open: string;
    delete: string;
    save: string;
    saveAs: string;
    newWindow: string;
    close: string;
  };
  step1: {
    title: string;
    addPrinter: string;
    volumetricLimit: string;
    highSpeedLimit: string;
  };
  step2: {
    title: string;
    dropzone: string;
    select: string;
    move: string;
    rotate: string;
    scale: string;
    place: string;
    cut: string;
    measure: string;
    dropZ0: string;
    splitObjects: string;
    autoArrange: string;
    autoOrient: string;
    autoOrientNoScale: string;
    selectAll: string;
    plateInstances: string;
  };
  step3: {
    title: string;
    dynamicProfiles: string;
    materials: string;
    multicolorMapping: string;
    qualityVsSpeed: string;
    lithophaneMode: string;
    scopeGlobal: string;
    scopePerPart: string;
    overrideInherit: string;
    overrideTree: string;
    overrideNormal: string;
    overrideNoSupport: string;
    overrideNoBrim: string;
    overrideBrim: string;
    overrideRaft: string;
    perPartSupportsHint: string;
    perPartAdhesionHint: string;
    partSupportsLabel: string;
    partAdhesionLabel: string;
    noPartsForOverride: string;
  };
  supportPainting: {
    title: string;
    editingObject: string;
    selectObjectFirst: string;
    toolSphere: string;
    toolSmartFill: string;
    brushActionEnforce: string;
    brushActionBlock: string;
    brushActionErase: string;
    brushSizeLabel: string;
    smartFillAngleLabel: string;
    overhangsOnlyLabel: string;
    overhangThresholdLabel: string;
    highlightOverhangsLabel: string;
    modeAutoBlockers: string;
    modeEnforcersOnly: string;
    blockAllObject: string;
    clearObjectPaint: string;
    mouseHint: string;
    paintedStats: string;
  };
  exportMenu: {
    exportSelection: string;
    export3mf: string;
    exportStl: string;
    exportObj: string;
    exportFullPlate3mf: string;
    applyTransforms: string;
    centerOnZ0: string;
    keepBedPosition: string;
    exporting: string;
  };
  projectLoading: {
    title: string;
    step1: string;
    step2: string;
    step3: string;
    step4: string;
  };
  step4: {
    title: string;
    scheduledPauses: string;
    addPause: string;
    sliceReady: string;
    aiAnalysis: string;
    sliceFirstForAi: string;
    saleCalculator: string;
    uploadOnly: string;
    uploadAndPrint: string;
  };
  simulator: {
    simulateLayer: string;
    play: string;
    pause: string;
    speed: string;
    realTimeTooltip: string;
    nextStep: string;
    autoAdvance: string;
    stepLabel: string;
  };
  profileInspector: {
    buttonLabel: string;
    disabledTooltip: string;
    savedBadge: string;
    currentGcodeHint: string;
    searchPlaceholder: string;
    applyAndReslice: string;
    reslicing: string;
    resetChanges: string;
    noMatches: string;
    tabs: {
      quality: string;
      strength: string;
      speed: string;
      support: string;
      multimaterial: string;
      others: string;
      filaments: string;
    };
    fields: Record<string, string>;
  };
  overlay: {
    loadingModel: string;
    slicing: string;
    uploadingLan: string;
    pleaseWait: string;
  };
  systemSetup: {
    title: string;
    subtitle: string;
    osDetected: string;
    rescan: string;
    scanning: string;
    installed: string;
    missing: string;
    downloadOfficial: string;
    browseManual: string;
    aiProvider: string;
    apiKey: string;
    saveAi: string;
    testConnection: string;
    mcpServer: string;
    copyMcpJson: string;
    copied: string;
    close: string;
  };
}

export const translations: Record<Language, TranslationSchema> = {
  es: {
    header: {
      wizard: 'Laminador (Wizard)',
      liveMonitor: 'Monitor en Vivo',
      machines: 'Máquinas',
      quote: 'Cotizar',
      quoteTitle: 'Calculadora comercial de cotización 3D',
      journal: 'Bitácora',
      journalTitle: 'Consultar bitácora de errores y fallos',
      envMcp: 'Entorno / MCP',
      envMcpTitle: 'Entorno del sistema, laminadores, IA (BYOK) y servidor MCP',
      settings: 'Configuración',
      settingsTitle: 'Configurar IPs, puertos USB/SD y API Keys de IA',
      languageTitle: 'Cambiar idioma (Español / English)',
      newProjectTab: 'Nuevo proyecto',
      openInNewWindow: 'Abrir nueva ventana de proyecto',
      closeProject: 'Cerrar proyecto',
      closeProjectTitle: 'Cerrar proyecto actual, limpiar todo y volver a la pantalla de inicio (Ctrl+W)',
    },
    startup: {
      title: '¿Continuar con el último proyecto?',
      subtitle: 'Se encontró tu sesión anterior guardada antes de cerrar:',
      printerLabel: 'Impresora:',
      openProject: 'Abrir proyecto',
      newProject: 'Proyecto nuevo',
      openLastProject: 'Abrir último proyecto',
    },
    projects: {
      galleryTitle: 'Proyectos guardados',
      empty: 'Aún no hay proyectos guardados.',
      open: 'Abrir',
      delete: 'Eliminar',
      save: 'Guardar proyecto',
      saveAs: 'Guardar como...',
      newWindow: 'Nueva ventana',
      close: 'Cerrar',
    },
    step1: {
      title: 'Paso 1 · Impresora',
      addPrinter: 'Agregar Impresora',
      volumetricLimit: 'Límite volumétrico',
      highSpeedLimit: 'Modo Alta Velocidad',
    },
    step2: {
      title: 'Paso 2 · Modelo 3D',
      dropzone: 'Arrastra un archivo .STL o .3MF aquí',
      select: 'Seleccionar / Clonar',
      move: 'Mover',
      rotate: 'Rotar',
      scale: 'Redimensionar',
      place: 'Colocar',
      cut: 'Cortar',
      measure: 'Medir',
      dropZ0: 'Z=0',
      splitObjects: 'Dividir Objetos',
      autoArrange: 'Ordenar',
      autoOrient: 'Auto-Orientar',
      autoOrientNoScale: 'Auto-Orientar sin Escalar',
      selectAll: 'Seleccionar Todo',
      plateInstances: 'Instancias en Plato',
    },
    step3: {
      title: 'Paso 3 · Perfil y Material',
      dynamicProfiles: 'Perfiles Dinámicos',
      materials: 'Materiales',
      multicolorMapping: 'Mapeo Multicolor (T0–T3)',
      qualityVsSpeed: 'Calidad vs. Velocidad',
      lithophaneMode: 'Modo Litofanía HD',
      scopeGlobal: 'Global',
      scopePerPart: 'Por Pieza',
      overrideInherit: 'Global',
      overrideTree: 'Árbol',
      overrideNormal: 'Normal',
      overrideNoSupport: 'No',
      overrideNoBrim: 'Sin Balsa',
      overrideBrim: 'Brim',
      overrideRaft: 'Balsa (Raft)',
      perPartSupportsHint: 'Anula soportes solo en piezas específicas (el resto hereda Global).',
      perPartAdhesionHint: 'Anula Brim o Balsa (Raft) solo en piezas específicas.',
      partSupportsLabel: 'Soportes de esta pieza',
      partAdhesionLabel: 'Balsa/Brim de esta pieza',
      noPartsForOverride: 'Importa o divide un modelo para ajustar piezas individuales.',
    },
    supportPainting: {
      title: 'Pintura de Soportes',
      editingObject: 'Editando soportes de:',
      selectObjectFirst: 'Haz clic en una pieza del plato para editar sus soportes.',
      toolSphere: 'Pincel Esférico',
      toolSmartFill: 'Relleno Inteligente',
      brushActionEnforce: 'Forzar (Verde)',
      brushActionBlock: 'Bloquear (Rojo)',
      brushActionErase: 'Borrar',
      brushSizeLabel: 'Tamaño del pincel',
      smartFillAngleLabel: 'Ángulo relleno inteligente',
      overhangsOnlyLabel: 'Solo en voladizos (> umbral°)',
      overhangThresholdLabel: 'Umbral de voladizo',
      highlightOverhangsLabel: 'Resaltar voladizos',
      modeAutoBlockers: 'Auto + Bloqueadores',
      modeEnforcersOnly: 'Solo Forzadores',
      blockAllObject: 'Bloquear todo este objeto',
      clearObjectPaint: 'Limpiar pintura de este objeto',
      mouseHint: 'Clic izq: acción activa · Clic der: bloquear · Shift+Clic: borrar',
      paintedStats: 'Triángulos pintados',
    },
    exportMenu: {
      exportSelection: 'Exportar Selección',
      export3mf: 'Exportar como .3MF (Multicolor + Config)',
      exportStl: 'Exportar como .STL (Binario)',
      exportObj: 'Exportar como .OBJ',
      exportFullPlate3mf: 'Exportar todo el plato como .3MF',
      applyTransforms: 'Aplicar rotación y escala actuales',
      centerOnZ0: 'Centrar en (0, 0) sobre Z=0',
      keepBedPosition: 'Conservar posición actual en cama',
      exporting: 'Exportando...',
    },
    projectLoading: {
      title: 'Cargando...',
      step1: 'Leyendo metadatos del proyecto y perfil guardado.',
      step2: 'Cargando geometría 3D y colores multicolor.',
      step3: 'Separando piezas divididas y restaurando posiciones en cama.',
      step4: 'Listo.',
    },
    step4: {
      title: 'Paso 4 · Laminado y Envío',
      scheduledPauses: 'Pausas Programadas',
      addPause: '+ Añadir',
      sliceReady: 'Laminado listo',
      aiAnalysis: 'Análisis IA',
      sliceFirstForAi: 'Lamina primero para activar Análisis IA',
      saleCalculator: 'Calculadora de Venta',
      uploadOnly: 'Subir sin Imprimir',
      uploadAndPrint: 'Subir e Imprimir Ahora',
    },
    simulator: {
      simulateLayer: 'Simular capa',
      play: 'Reproducir simulación (Espacio)',
      pause: 'Pausar simulación (Espacio)',
      speed: 'Velocidad',
      realTimeTooltip: 'Velocidad real 1:1 de la impresora',
      nextStep: 'Paso siguiente',
      autoAdvance: 'Auto-avanzar capa',
      stepLabel: 'Paso',
    },
    profileInspector: {
      buttonLabel: 'Perfil',
      disabledTooltip: 'Lamina el modelo o abre un proyecto laminado para inspeccionar su perfil',
      savedBadge: 'Perfil guardado del corte',
      currentGcodeHint: 'Corresponde al .gcode actual del proyecto',
      searchPlaceholder: 'Buscar parámetro (ej. Z, temperatura, ventilador, purga, relleno)...',
      applyAndReslice: 'Aplicar y Re-laminar',
      reslicing: 'Re-laminando...',
      resetChanges: 'Restaurar',
      noMatches: 'Sin parámetros que coincidan con la búsqueda.',
      tabs: {
        quality: 'Calidad',
        strength: 'Fuerza',
        speed: 'Velocidad',
        support: 'Soportes',
        multimaterial: 'Multimaterial',
        others: 'Otros',
        filaments: 'Filamentos',
      },
      fields: {
        layer_height: 'Altura de capa (mm)',
        initial_layer_height: 'Altura capa inicial (mm)',
        line_width: 'Ancho de línea (mm)',
        outer_wall_line_width: 'Ancho pared exterior (mm)',
        inner_wall_line_width: 'Ancho pared interior (mm)',
        top_surface_line_width: 'Ancho superficie superior (mm)',
        infill_line_width: 'Ancho de relleno (mm)',
        support_line_width: 'Ancho de soporte (mm)',
        wall_generator: 'Generador de paredes',
        seam_position: 'Posición de costura',
        ironing_type: 'Planchado superior (Ironing)',
        top_surface_pattern: 'Patrón superficie superior',
        wall_loops: 'Perímetros / Paredes',
        top_shell_layers: 'Capas sólidas superiores',
        bottom_shell_layers: 'Capas sólidas inferiores',
        sparse_infill_density: 'Densidad de relleno',
        sparse_infill_pattern: 'Patrón de relleno',
        infill_wall_overlap: 'Solapamiento relleno/pared',
        outer_wall_speed: 'Velocidad pared exterior (mm/s)',
        inner_wall_speed: 'Velocidad pared interior (mm/s)',
        initial_layer_speed: 'Velocidad capa inicial (mm/s)',
        sparse_infill_speed: 'Velocidad de relleno (mm/s)',
        top_surface_speed: 'Velocidad superficie superior (mm/s)',
        overhang_speed: 'Velocidad en voladizos (mm/s)',
        overhang_1_4_speed: 'Voladizo 10-25% (mm/s)',
        overhang_2_4_speed: 'Voladizo 25-50% (mm/s)',
        overhang_3_4_speed: 'Voladizo 50-75% (mm/s)',
        overhang_4_4_speed: 'Voladizo 75-100% (mm/s)',
        bridge_speed: 'Velocidad en puentes (mm/s)',
        travel_speed: 'Velocidad de viaje (mm/s)',
        max_volumetric_speed_qmax: 'Flujo volumétrico máx. Qmax (mm³/s)',
        acceleration_print: 'Aceleración de impresión (mm/s²)',
        enable_support: 'Soportes habilitados',
        support_type: 'Tipo de soporte',
        support_style: 'Estilo de soporte',
        support_threshold_angle: 'Ángulo umbral de soporte (°)',
        support_top_z_distance: 'Distancia Z superior soporte (mm)',
        support_bottom_z_distance: 'Distancia Z inferior soporte (mm)',
        support_object_xy_distance: 'Distancia X/Y soporte-pieza (mm)',
        support_interface_top_layers: 'Capas interfaz superior soporte',
        support_interface_bottom_layers: 'Capas interfaz inferior soporte',
        support_interface_spacing: 'Espaciado interfaz soporte (mm)',
        support_interface_pattern: 'Patrón interfaz soporte',
        active_tools: 'Herramientas activas (T0–T3)',
        tool_mapping: 'Mapeo de extrusores',
        enable_prime_tower: 'Torre de purga / prime',
        prime_tower_width: 'Ancho torre de purga (mm)',
        prime_tower_brim_width: 'Ancho brim torre de purga (mm)',
        flush_volumes: 'Volúmenes de purga',
        support_interface_filament: 'Filamento interfaz soporte',
        z_color_changes: 'Cambios de color por Z',
        brim_type: 'Tipo de adhesión (Brim)',
        brim_width: 'Ancho de Brim (mm)',
        skirt_loops: 'Vueltas de falda (Skirt)',
        layer_pauses: 'Pausas por capa programadas',
        anti_stringing_active: 'Anti-stringing / Retracción activa',
        chamber_temp: 'Temp. de cámara (°C)',
        gcode_filename: 'Archivo G-code',
        printer_name: 'Impresora',
        slicer_engine: 'Motor laminador',
        sliced_at_timestamp: 'Fecha del corte',
        nozzle_temp_initial: 'Temp. boquilla capa inicial (°C)',
        nozzle_temp: 'Temp. boquilla (°C)',
        bed_temp_initial: 'Temp. cama capa inicial (°C)',
        bed_temp: 'Temp. cama (°C)',
        fan_min_speed: 'Ventilador mínimo (%)',
        fan_max_speed: 'Ventilador máximo (%)',
        overhang_fan_speed: 'Ventilador en voladizos (%)',
        retraction_length: 'Longitud de retracción (mm)',
        retraction_speed: 'Velocidad de retracción (mm/s)',
        max_volumetric_flow: 'Flujo volumétrico máx. (mm³/s)',
        density_g_cm3: 'Densidad (g/cm³)',
        cost_per_kg_cop: 'Costo por kg (COP)',
      },
    },
    overlay: {
      loadingModel: 'Cargando modelo 3D...',
      slicing: 'Laminando modelo...',
      uploadingLan: 'Transfiriendo por LAN a impresora...',
      pleaseWait: 'Por favor espera, procesando operación en curso...',
    },
    systemSetup: {
      title: 'Entorno Multiplataforma, IA y MCP',
      subtitle: 'Auto-detección de laminadores, claves IA (BYOK) y servidor MCP interno',
      osDetected: 'Sistema Operativo',
      rescan: 'Volver a buscar en el equipo',
      scanning: 'Escaneando...',
      installed: 'Instalado',
      missing: 'Falta instalar',
      downloadOfficial: 'Descargar Oficial',
      browseManual: 'Ubicar manualmente...',
      aiProvider: 'Proveedor de IA (BYOK)',
      apiKey: 'API Key',
      saveAi: 'Guardar clave IA',
      testConnection: 'Probar conexión',
      mcpServer: 'Servidor MCP Interno',
      copyMcpJson: 'Copiar configuración JSON MCP',
      copied: 'Copiado',
      close: 'Cerrar',
    },
  },
  en: {
    header: {
      wizard: 'Slicer (Wizard)',
      liveMonitor: 'Live Monitor',
      machines: 'Machines',
      quote: 'Quote',
      quoteTitle: 'Commercial 3D printing quote calculator',
      journal: 'Logbook',
      journalTitle: 'View error and failure logbook',
      envMcp: 'Env / MCP',
      envMcpTitle: 'System environment, slicers, AI (BYOK), and MCP server',
      settings: 'Settings',
      settingsTitle: 'Configure IPs, USB/SD ports, and AI API Keys',
      languageTitle: 'Switch language (Español / English)',
      newProjectTab: 'New project',
      openInNewWindow: 'Open new project window',
      closeProject: 'Close project',
      closeProjectTitle: 'Close current project, clear workspace, and return to start screen (Ctrl+W)',
    },
    startup: {
      title: 'Continue with last project?',
      subtitle: 'Your previous saved session before closing was found:',
      printerLabel: 'Printer:',
      openProject: 'Open project',
      newProject: 'New project',
      openLastProject: 'Open last project',
    },
    projects: {
      galleryTitle: 'Saved projects',
      empty: 'No saved projects yet.',
      open: 'Open',
      delete: 'Delete',
      save: 'Save project',
      saveAs: 'Save as...',
      newWindow: 'New window',
      close: 'Close',
    },
    step1: {
      title: 'Step 1 · Printer',
      addPrinter: 'Add Printer',
      volumetricLimit: 'Volumetric limit',
      highSpeedLimit: 'High-Speed Mode',
    },
    step2: {
      title: 'Step 2 · 3D Model',
      dropzone: 'Drop an .STL or .3MF file here',
      select: 'Select / Clone',
      move: 'Move',
      rotate: 'Rotate',
      scale: 'Scale',
      place: 'Place on Face',
      cut: 'Cut',
      measure: 'Measure',
      dropZ0: 'Z=0',
      splitObjects: 'Split Objects',
      autoArrange: 'Auto-Arrange',
      autoOrient: 'Auto-Orient',
      autoOrientNoScale: 'Auto-Orient without Scaling',
      selectAll: 'Select All',
      plateInstances: 'Plate Instances',
    },
    step3: {
      title: 'Step 3 · Profile & Material',
      dynamicProfiles: 'Dynamic Profiles',
      materials: 'Materials',
      multicolorMapping: 'Multicolor Mapping (T0–T3)',
      qualityVsSpeed: 'Quality vs. Speed',
      lithophaneMode: 'HD Lithophane Mode',
      scopeGlobal: 'Global',
      scopePerPart: 'Per Part',
      overrideInherit: 'Global',
      overrideTree: 'Tree',
      overrideNormal: 'Normal',
      overrideNoSupport: 'No',
      overrideNoBrim: 'No Brim',
      overrideBrim: 'Brim',
      overrideRaft: 'Raft',
      perPartSupportsHint: 'Override supports on specific parts only (others inherit Global).',
      perPartAdhesionHint: 'Override Brim or Raft on specific parts only.',
      partSupportsLabel: 'Supports for this part',
      partAdhesionLabel: 'Brim/Raft for this part',
      noPartsForOverride: 'Import or split a model to configure individual parts.',
    },
    supportPainting: {
      title: 'Support Painting',
      editingObject: 'Editing supports for:',
      selectObjectFirst: 'Click a part on the bed to paint its supports.',
      toolSphere: 'Sphere Brush',
      toolSmartFill: 'Smart Fill',
      brushActionEnforce: 'Enforce (Green)',
      brushActionBlock: 'Block (Red)',
      brushActionErase: 'Erase',
      brushSizeLabel: 'Brush size',
      smartFillAngleLabel: 'Smart fill angle',
      overhangsOnlyLabel: 'On overhangs only (> threshold°)',
      overhangThresholdLabel: 'Overhang threshold',
      highlightOverhangsLabel: 'Highlight overhangs',
      modeAutoBlockers: 'Auto + Blockers',
      modeEnforcersOnly: 'Enforcers Only',
      blockAllObject: 'Block entire object',
      clearObjectPaint: 'Clear object painting',
      mouseHint: 'Left-click: active tool · Right-click: block · Shift+Click: erase',
      paintedStats: 'Painted triangles',
    },
    exportMenu: {
      exportSelection: 'Export Selection',
      export3mf: 'Export as .3MF (Multicolor + Settings)',
      exportStl: 'Export as .STL (Binary)',
      exportObj: 'Export as .OBJ',
      exportFullPlate3mf: 'Export entire plate as .3MF',
      applyTransforms: 'Apply current rotation & scale',
      centerOnZ0: 'Center at (0, 0) on Z=0',
      keepBedPosition: 'Keep current bed position',
      exporting: 'Exporting...',
    },
    projectLoading: {
      title: 'Loading...',
      step1: 'Reading project metadata and saved profile.',
      step2: 'Loading 3D geometry and multicolor attributes.',
      step3: 'Splitting parts and restoring bed positions.',
      step4: 'Ready.',
    },
    step4: {
      title: 'Step 4 · Slice & Send',
      scheduledPauses: 'Scheduled Pauses',
      addPause: '+ Add',
      sliceReady: 'Slice ready',
      aiAnalysis: 'AI Analysis',
      sliceFirstForAi: 'Slice first to enable AI Analysis',
      saleCalculator: 'Quote Calculator',
      uploadOnly: 'Upload without Printing',
      uploadAndPrint: 'Upload & Print Now',
    },
    simulator: {
      simulateLayer: 'Simulate layer',
      play: 'Play simulation (Space)',
      pause: 'Pause simulation (Space)',
      speed: 'Speed',
      realTimeTooltip: 'Real 1:1 printer speed',
      nextStep: 'Next step',
      autoAdvance: 'Auto-advance layer',
      stepLabel: 'Step',
    },
    profileInspector: {
      buttonLabel: 'Profile',
      disabledTooltip: 'Slice the model or open a sliced project to inspect its profile',
      savedBadge: 'Saved slice profile',
      currentGcodeHint: 'Matches current project .gcode',
      searchPlaceholder: 'Search parameter (e.g. Z, temperature, fan, purge, infill)...',
      applyAndReslice: 'Apply & Re-slice',
      reslicing: 'Re-slicing...',
      resetChanges: 'Reset',
      noMatches: 'No parameters match your search.',
      tabs: {
        quality: 'Quality',
        strength: 'Strength',
        speed: 'Speed',
        support: 'Supports',
        multimaterial: 'Multimaterial',
        others: 'Others',
        filaments: 'Filaments',
      },
      fields: {
        layer_height: 'Layer height (mm)',
        initial_layer_height: 'Initial layer height (mm)',
        line_width: 'Line width (mm)',
        outer_wall_line_width: 'Outer wall line width (mm)',
        inner_wall_line_width: 'Inner wall line width (mm)',
        top_surface_line_width: 'Top surface line width (mm)',
        infill_line_width: 'Infill line width (mm)',
        support_line_width: 'Support line width (mm)',
        wall_generator: 'Wall generator',
        seam_position: 'Seam position',
        ironing_type: 'Ironing type',
        top_surface_pattern: 'Top surface pattern',
        wall_loops: 'Wall loops',
        top_shell_layers: 'Top shell layers',
        bottom_shell_layers: 'Bottom shell layers',
        sparse_infill_density: 'Sparse infill density',
        sparse_infill_pattern: 'Sparse infill pattern',
        infill_wall_overlap: 'Infill/wall overlap',
        outer_wall_speed: 'Outer wall speed (mm/s)',
        inner_wall_speed: 'Inner wall speed (mm/s)',
        initial_layer_speed: 'Initial layer speed (mm/s)',
        sparse_infill_speed: 'Sparse infill speed (mm/s)',
        top_surface_speed: 'Top surface speed (mm/s)',
        overhang_speed: 'Overhang speed (mm/s)',
        overhang_1_4_speed: 'Overhang 10-25% (mm/s)',
        overhang_2_4_speed: 'Overhang 25-50% (mm/s)',
        overhang_3_4_speed: 'Overhang 50-75% (mm/s)',
        overhang_4_4_speed: 'Overhang 75-100% (mm/s)',
        bridge_speed: 'Bridge speed (mm/s)',
        travel_speed: 'Travel speed (mm/s)',
        max_volumetric_speed_qmax: 'Max volumetric speed Qmax (mm³/s)',
        acceleration_print: 'Print acceleration (mm/s²)',
        enable_support: 'Enable support',
        support_type: 'Support type',
        support_style: 'Support style',
        support_threshold_angle: 'Support threshold angle (°)',
        support_top_z_distance: 'Support top Z distance (mm)',
        support_bottom_z_distance: 'Support bottom Z distance (mm)',
        support_object_xy_distance: 'Support XY distance (mm)',
        support_interface_top_layers: 'Support interface top layers',
        support_interface_bottom_layers: 'Support interface bottom layers',
        support_interface_spacing: 'Support interface spacing (mm)',
        support_interface_pattern: 'Support interface pattern',
        active_tools: 'Active tools (T0–T3)',
        tool_mapping: 'Tool mapping',
        enable_prime_tower: 'Enable prime tower',
        prime_tower_width: 'Prime tower width (mm)',
        prime_tower_brim_width: 'Prime tower brim width (mm)',
        flush_volumes: 'Flush volumes',
        support_interface_filament: 'Support interface filament',
        z_color_changes: 'Z color changes',
        brim_type: 'Brim type',
        brim_width: 'Brim width (mm)',
        skirt_loops: 'Skirt loops',
        layer_pauses: 'Scheduled layer pauses',
        anti_stringing_active: 'Anti-stringing / Retraction active',
        chamber_temp: 'Chamber temp (°C)',
        gcode_filename: 'G-code file',
        printer_name: 'Printer',
        slicer_engine: 'Slicer engine',
        sliced_at_timestamp: 'Sliced at',
        nozzle_temp_initial: 'Initial nozzle temp (°C)',
        nozzle_temp: 'Nozzle temp (°C)',
        bed_temp_initial: 'Initial bed temp (°C)',
        bed_temp: 'Bed temp (°C)',
        fan_min_speed: 'Min fan speed (%)',
        fan_max_speed: 'Max fan speed (%)',
        overhang_fan_speed: 'Overhang fan speed (%)',
        retraction_length: 'Retraction length (mm)',
        retraction_speed: 'Retraction speed (mm/s)',
        max_volumetric_flow: 'Max volumetric flow (mm³/s)',
        density_g_cm3: 'Density (g/cm³)',
        cost_per_kg_cop: 'Cost per kg (COP)',
      },
    },
    overlay: {
      loadingModel: 'Loading 3D model...',
      slicing: 'Slicing model...',
      uploadingLan: 'Uploading over LAN to printer...',
      pleaseWait: 'Please wait, processing operation...',
    },
    systemSetup: {
      title: 'Cross-Platform Environment, AI & MCP',
      subtitle: 'Slicer auto-detection, AI keys (BYOK), and internal MCP server',
      osDetected: 'Operating System',
      rescan: 'Rescan computer',
      scanning: 'Scanning...',
      installed: 'Installed',
      missing: 'Not installed',
      downloadOfficial: 'Official Download',
      browseManual: 'Locate manually...',
      aiProvider: 'AI Provider (BYOK)',
      apiKey: 'API Key',
      saveAi: 'Save AI Key',
      testConnection: 'Test connection',
      mcpServer: 'Internal MCP Server',
      copyMcpJson: 'Copy MCP JSON Config',
      copied: 'Copied',
      close: 'Close',
    },
  },
};
