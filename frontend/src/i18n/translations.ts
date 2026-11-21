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
