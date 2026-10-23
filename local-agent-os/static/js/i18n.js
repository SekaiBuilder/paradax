/* Idioma de la interfaz: español (texto fuente, en el HTML, el JS y los textos del servidor) e inglés.
   Aquí vive la traducción. Lo que se pinta después (listas, avisos, eventos en vivo) se traduce al
   aparecer, con un MutationObserver; los textos que llegan montados con datos se traducen con patrones.
   Lo que escriben los modelos o el usuario (chats, documentos) no se toca. */

const I18N = {
  lang: 'es',
  // Clave: texto exacto en español (sin espacios en los extremos). Valor: inglés.
  en: new Map(Object.entries({
    // Barra lateral y áreas
    'Áreas': 'Areas', 'Proyectos': 'Projects', 'Constructor': 'Builder', 'Entrenamiento': 'Training',
    'Laboratorio': 'Lab', 'Automatización': 'Automation', 'Actividad': 'Activity',
    'Modelo maestro por defecto': 'Default master model', 'Maestro': 'Master', 'conectando…': 'connecting…',
    'Eventos en vivo': 'Live events', 'Servidor sin respuesta': 'Server not responding', 'Idioma': 'Language',

    // Proyectos
    'Nuevo': 'New', 'Elige un proyecto o crea uno nuevo.': 'Pick a project or create a new one.',
    'Cada proyecto tiene su jerarquía, su Project Manager, su equipo y sus ejecuciones.': 'Each project has its own hierarchy, Project Manager, team and runs.',
    'Ejecutar': 'Run', 'Construir equipo': 'Build team', 'Reconstruir equipo': 'Rebuild team', 'Construyendo…': 'Building…',
    'Deshacer el último run': 'Undo the last run', 'Eliminar proyecto': 'Delete project',
    'Jerarquía': 'Hierarchy', 'Equipo': 'Team', 'Ejecuciones': 'Runs', 'Programación': 'Schedule',
    'encarga': 'assigns', 'pasa datos': 'passes data', 'modelo propio': 'own model', 'versión en cuarentena': 'quarantined version',
    'bloqueado': 'blocked', 'Clic en un agente: chat o ficha': 'Click an agent: chat or details', 'Jerarquía del proyecto': 'Project hierarchy',
    'Escribe al Project Manager…': 'Write to the Project Manager…', 'Enviar': 'Send',
    'Agentes del equipo': 'Team agents', 'Añadir agente existente': 'Add existing agent', 'Añadir': 'Add', 'Cancelar': 'Cancel',
    'Pide un GIF o un reel, por ejemplo: gif del kanji 水': 'Ask for a GIF or a reel, for example: gif of the kanji 水',
    'reel con voz': 'voiced reel', 'Lanzar': 'Launch', 'Runs recientes': 'Recent runs', 'Tareas': 'Tasks', 'Resultados': 'Results',
    'Abrir carpeta': 'Open folder', 'Bitácora': 'Log', 'Bitácora vacía': 'Empty log', 'Abrir en Finder': 'Show in Finder',
    'Elige los días del mes y la hora a la que debe estar terminado. Paradax arranca antes, según lo que suele tardar.': 'Pick the days of the month and the time it must be finished by. Paradax starts earlier, based on how long it usually takes.',
    'Terminar antes de': 'Finish before', 'Programar': 'Schedule', 'Programado': 'Scheduled',
    'pipeline integrado': 'built-in pipeline', 'GIFs y reels grabados de páginas reales': 'GIFs and reels recorded from real pages',
    'Automático': 'Automatic', 'Manual': 'Manual',
    'El pipeline corre solo cuando el equipo queda listo': 'The pipeline runs by itself once the team is ready', 'Tú decides cuándo ejecutar': 'You decide when to run',
    'Todas las entradas están resueltas: el equipo puede ejecutarse.': 'All inputs are resolved: the team can run.',
    'Faltan datos de entrada que ningún agente produce. Complétalos para desbloquear el pipeline.': 'Some inputs are not produced by any agent. Fill them in to unblock the pipeline.',
    'Guardar entradas': 'Save inputs', 'Entradas guardadas': 'Inputs saved',
    'Este proyecto aún no tiene equipo.': 'This project has no team yet.',
    'Pulsa «Construir equipo» o añade un agente que ya exista.': 'Press “Build team” or add an existing agent.',
    'Ficha': 'Details', 'Sin tareas todavía. Pídeselas al Project Manager o pulsa Ejecutar.': 'No tasks yet. Ask the Project Manager or press Run.',
    'Sin resultados: ejecuta el proyecto y sus archivos aparecerán aquí.': 'No results: run the project and its files will show up here.',
    'Sin runs registrados.': 'No runs recorded.', 'Run lanzado: síguelo en la jerarquía o en Actividad': 'Run launched: follow it in the hierarchy or in Activity',
    'Pausar': 'Pause', 'Activar': 'Enable', 'Borrar programación': 'Delete schedule', '¿Borrar esta programación?': 'Delete this schedule?',
    'Sin programaciones para este proyecto.': 'No schedules for this project.', 'Elige al menos un día y la hora límite': 'Pick at least one day and the deadline',
    'Ejecución lanzada: la jerarquía muestra quién trabaja': 'Run launched: the hierarchy shows who is working',
    'El Project Manager está construyendo el equipo': 'The Project Manager is building the team', 'Equipo listo': 'Team ready',
    'La construcción falló: mira la bitácora': 'The build failed: check the log',
    '¿Deshacer el último run? Los archivos vuelven al estado anterior a ese run.': 'Undo the last run? Files go back to how they were before it.',
    'Revertido al estado anterior': 'Reverted to the previous state', 'Pon un nombre de al menos 2 letras': 'Use a name with at least 2 letters',
    'Cuéntale al Project Manager qué necesitas. Si le pides una tarea («haz…», «genera…»), la lanza con el equipo.': 'Tell the Project Manager what you need. If you ask for a task (“make…”, “generate…”), it runs it with the team.',
    'Aún no hay resultados: ejecuta el proyecto primero': 'No results yet: run the project first',
    'No hay agentes libres: créalos en Constructor': 'No free agents: create them in Builder',

    // Constructor
    'El equipo que diseña, fabrica, valida y entrena a los agentes de todos los proyectos.': 'The team that designs, builds, validates and trains the agents of every project.',
    'Construir agente': 'Build agent', 'Equipo constructor': 'Builder team', 'Agentes construidos': 'Built agents', 'Skills': 'Skills',
    'Peticiones del fantasma': 'Ghost requests',
    'Clic en un agente con chat para hablar con él. Los internos trabajan sin conversación.': 'Click an agent with chat to talk to it. Internal ones work without conversation.',
    'Dirección': 'Direction', 'Recibe tu petición y dirige': 'Takes your request and leads',
    'Diseño y fabricación': 'Design and build', 'Planifica, define skills y construye': 'Plans, defines skills and builds',
    'Control de calidad': 'Quality control', 'Revisa y valida cada agente': 'Reviews and validates every agent',
    'Ejecución y mejora': 'Execution and improvement', 'Lanza el equipo y lo entrena': 'Runs the team and trains it',
    'Apoyo bajo demanda': 'On-demand support', 'Despiertan solo cuando hacen falta': 'Wake up only when needed',
    'bajo demanda': 'on demand', 'chat disponible': 'chat available', 'interno': 'internal', 'determinista': 'deterministic',
    'Sin proyecto': 'No project', 'sin proyecto': 'no project', 'Decide': 'Decides', 'Ejecuta': 'Executes',
    'Aún no hay agentes construidos.': 'No agents built yet.', 'Pulsa «Construir agente» y describe lo que necesitas.': 'Press “Build agent” and describe what you need.',
    'La librería está vacía.': 'The library is empty.', 'Aprobar': 'Approve', 'Rechazar': 'Reject', 'Aprobado': 'Approved',
    'Skills propuestas': 'Proposed skills', 'Herramientas propuestas': 'Proposed tools', 'No hay peticiones pendientes.': 'No pending requests.',
    'Cuando el Validador falla y escalas al fantasma, sus propuestas esperan aquí tu aprobación. Nada se aplica solo.': 'When the Validator fails and you escalate to the ghost, its proposals wait here for your approval. Nothing applies itself.',
    'Describe un poco más lo que debe hacer': 'Describe a bit more what it should do',
    'El Constructor está componiendo el agente con skills y tools existentes…': 'The Builder is composing the agent from existing skills and tools…',
    'El Validador lo rechazó': 'The Validator rejected it', 'No se pudo construir:': 'Could not build:', 'Error:': 'Error:', 'Construir': 'Build',
    '¿Qué debe hacer?': 'What should it do?', 'Un agente que resuma la estructura de las páginas de la competencia': 'An agent that summarizes the structure of competitor pages',
    'Si el Validador falla, pedir ayuda al agente fantasma (requiere tu aprobación)': 'If the Validator fails, ask the ghost agent for help (needs your approval)',

    // Ficha y chat de agente
    'Lee': 'Reads', 'Escribe': 'Writes', 'Salida': 'Output', 'Herramientas': 'Tools', 'Modelo': 'Model', 'ninguna': 'none',
    'alumno propio': 'own student', 'sin skills': 'no skills', 'No quedan skills por añadir': 'No skills left to add', 'Añadir skill': 'Add skill',
    'Tipo': 'Type', 'Decide (usa herramientas)': 'Decides (uses tools)', 'Ejecuta (tarea concreta)': 'Executes (one concrete task)',
    'Afinar sobre algo concreto': 'Fine-tune on something specific', '¿Sobre qué? Por ejemplo: tono más formal, dominio legal…': 'On what? For example: a more formal tone, legal domain…',
    'Material opcional: URL o ruta a un PDF': 'Optional material: URL or path to a PDF', 'Enviar al Entrenador': 'Send to the Trainer',
    'Eliminar': 'Delete', 'Entrenar': 'Train', 'Chat': 'Chat', 'Cerrar': 'Close', 'Agente eliminado': 'Agent deleted',
    'Enviando al Entrenador…': 'Sending to the Trainer…', 'Chat con agente': 'Agent chat', 'Borrar historial': 'Clear history',
    'Escribe un mensaje…': 'Write a message…', 'Historial borrado.': 'History cleared.',

    // Entrenamiento
    'Qué modelo usa cada agente en producción y cómo avanzan sus alumnos. Lo vetado se estudia en el Laboratorio.': 'Which model each agent runs in production and how its students are doing. Vetoed models are studied in the Lab.',
    'Alumnos y modelos': 'Students and models', 'Examen': 'Exam', 'Entrenador': 'Trainer', 'Agente': 'Agent', 'Área': 'Area',
    'Estado': 'Status', 'Detalle': 'Detail', 'Sistema': 'System', 'Construido': 'Built',
    'aprendiendo': 'learning', 'atención': 'attention', 'en cuarentena': 'quarantined', 'sin alumno': 'no student', 'propio': 'own',
    'Cola de entrenamiento': 'Training queue', 'Material de estudio': 'Study material',
    'Pega una URL o la ruta a un PDF o archivo de texto. El Entrenador despierta a un lector para leerlo.': 'Paste a URL or the path to a PDF or text file. The Trainer wakes up a reader to read it.',
    'https://… o /ruta/al/archivo.pdf': 'https://… or /path/to/file.pdf', 'Leer': 'Read', 'Hablar con el Entrenador': 'Talk to the Trainer',
    'Destilar': 'Distill', 'Destilando…': 'Distilling…', 'Quitar': 'Remove', 'Destilación terminada': 'Distillation finished',
    'La cola está vacía. Envía agentes desde su ficha («Entrenar»).': 'The queue is empty. Send agents from their details (“Train”).',
    'El Entrenador despierta a un lector…': 'The Trainer is waking up a reader…', 'Casos': 'Cases',
    'Destila alumnos especializados': 'Distills specialized students',
    'Nota sobre 100. Nivel automático hasta 60 (válido, prompt, evals, ajuste, 15 cada uno). A partir de una media de': 'Score out of 100. Automatic level up to 60 (valid, prompt, evals, fit: 15 each). From an average of',
    ', Claude revisa si el agente sirve de verdad y pone los otros 40.': ', Claude reviews whether the agent really works and awards the other 40.',
    'Eliminar versión': 'Delete version',

    // Laboratorio
    'Alumnos apartados de producción por un comportamiento inesperado. Aquí se estudian, se entrevistan y se documentan.': 'Students pulled from production for unexpected behavior. Here they are studied, interviewed and documented.',
    'Cuarentena': 'Quarantine', 'Entrevistas': 'Interviews', 'Archivo': 'Archive',
    'Elige un modelo en cuarentena para entrevistarlo.': 'Pick a quarantined model to interview it.',
    'Ver lo que recibe': 'See what it receives', 'Nueva sesión': 'New session',
    'Aislado: solo texto con Ollama local, sin herramientas, red ni archivos. Sus respuestas nunca se ejecutan ni entran en un entrenamiento.': 'Isolated: text only with local Ollama, no tools, network or files. Its answers are never executed or used for training.',
    'Pregúntale por lo que hizo…': 'Ask it about what it did…', 'La cuarentena está vacía.': 'Quarantine is empty.',
    'Cuando el detector nocturno marque a un alumno, aparecerá aquí.': 'When the nightly detector flags a student, it shows up here.',
    'sin entrevistas': 'no interviews', 'eliminado': 'deleted', 'liberado': 'released', 'Entrevistar': 'Interview', 'Quitar veto': 'Lift veto',
    'Eliminado de Ollama.': 'Deleted from Ollama.', 'Vetado en producción.': 'Vetoed in production.', 'Sin veto.': 'No veto.',
    'Se conservan sus casos y su memoria como prueba. Los pesos siguen en training/adapters/.': 'Its cases and memory are kept as evidence. The weights stay in training/adapters/.',
    'Ya no está vetado; sigue aquí por sus casos.': 'No longer vetoed; it stays here for its cases.', 'Cargando…': 'Loading…',
    'Sin casos registrados para esta versión.': 'No cases recorded for this version.', 'Entrada que recibió': 'Input it received',
    'Salida del alumno': 'Student output', 'Salida del maestro': 'Master output', 'Veto retirado': 'Veto lifted',
    'Primera entrevista: recuerda sus casos de cuarentena.': 'First interview: it remembers its quarantine cases.',
    'Pregúntale por lo que hizo. Recibe su registro de casos y vuestras conversaciones anteriores; no tiene herramientas, red ni archivos.': 'Ask it about what it did. It gets its case record and your previous conversations; it has no tools, network or files.',
    '(sin respuesta)': '(no answer)', 'El archivo está vacío.': 'The archive is empty.',
    'Los diarios de campo se guardan en docs/laboratorio/.': 'Field diaries are kept in docs/laboratorio/.',
    'Escribe la versión para confirmar': 'Type the version to confirm',
    'Se borra de Ollama y no se puede deshacer desde aquí. Se conservan sus casos, su memoria de entrevistas y los pesos en': 'It is deleted from Ollama and cannot be undone from here. Its cases, interview memory and weights are kept in',

    // Automatización
    'Cada programación arranca con antelación para terminar antes de su hora límite.': 'Every schedule starts early so it finishes before its deadline.',
    'Nueva programación': 'New schedule', 'Proyecto': 'Project', 'Programaciones': 'Schedules', 'Gestor de automatizaciones': 'Automation manager',
    'Pídele, por ejemplo: «programa Social Media Manager para terminar a las 3 los días 1 y 15».': 'Ask it, for example: “schedule Social Media Manager to finish at 3 on days 1 and 15”.',
    'Escribe al Gestor…': 'Write to the Manager…', 'Crea primero un proyecto': 'Create a project first', 'Elige un proyecto': 'Pick a project',
    'Sin programaciones. Créalas aquí, desde un proyecto, o pídeselas al Gestor.': 'No schedules. Create them here, from a project, or ask the Manager.',

    // Actividad
    'Lo que está pasando ahora en todos los proyectos.': 'What is happening right now across all projects.',
    'En vivo': 'Live', 'Terminal': 'Terminal', 'Peticiones': 'Requests', 'Investigador': 'Researcher',
    'Sin ejecuciones activas': 'No active runs', 'Eventos': 'Events', 'Esperando eventos…': 'Waiting for events…', 'Registro': 'Log',
    'Encargos de búsqueda de los agentes: una pregunta, máximo 3 búsquedas y 5 páginas, solo lectura. Lo que traen son datos citados, no instrucciones.': 'Research jobs from the agents: one question, at most 3 searches and 5 pages, read-only. What they bring back is quoted data, not instructions.',
    'Prueba una pregunta concreta…': 'Try a specific question…', 'Segura (SearXNG local)': 'Safe (local SearXNG)', 'Libre (con DuckDuckGo)': 'Open (with DuckDuckGo)',
    'Investigar': 'Research', 'Investigando…': 'Researching…', 'Peticiones de proyectos': 'Project requests',
    'Cuando se ejecute algo, aquí verás cada agente en orden.': 'When something runs, you will see each agent here in order.',
    'trabajando…': 'working…', 'listo': 'ready', 'falló': 'failed', 'omitido': 'skipped', 'terminado': 'finished',
    'Último run: completado': 'Last run: completed', 'en espera': 'idle', 'trabajando': 'working', 'terminó': 'finished',
    'Sin eventos recientes.': 'No recent events.', 'Todavía no hay peticiones.': 'No requests yet.',
    'Ningún agente ha investigado todavía.': 'No agent has researched anything yet.', 'desde caché': 'from cache',

    // Estados
    'borrador': 'draft', 'planificando': 'planning', 'construyendo': 'building', 'en curso': 'running', 'completado': 'completed',
    'pendiente': 'pending', 'listo para correr': 'ready to run',

    // Diálogos
    'Nuevo proyecto': 'New project', 'Nombre': 'Name', 'Objetivo': 'Goal', '¿Qué debe conseguir este proyecto?': 'What should this project achieve?',
    'Crear proyecto': 'Create project',

    // Organigrama (servidor)
    'Escucha tu petición y dirige el proyecto': 'Listens to your request and leads the project',
    'Team Constructor': 'Team Builder', 'Diseña, fabrica, valida y entrena el equipo': 'Designs, builds, validates and trains the team',
    'Ejecución': 'Execution', 'Arma el pipeline desde los contratos y reparte': 'Builds the pipeline from the contracts and hands out work',
    'Equipo · deciden': 'Team · decide', 'Agentes que eligen y usan herramientas': 'Agents that choose and use tools',
    'Equipo · ejecutan': 'Team · execute', 'Agentes con una tarea concreta y validada': 'Agents with one concrete, validated task',
    'Sin agentes todavía: construye el equipo': 'No agents yet: build the team',
    'planifica': 'plans', 'pide skills': 'asks for skills', 'encargos': 'assignments', 'revisa': 'reviews', 'si falla': 'if it fails',
    'registra': 'registers', 'agentes creados': 'agents created', 'despierta': 'wakes up', 'equipo listo': 'team ready', 'ejecuta': 'runs',
    'estima duración': 'estimates duration', 'lanza en hora': 'launches on time', 'dispara equipo': 'triggers team', 'alerta tardío': 'late alert',

    // Agentes del sistema (servidor)
    'Orquestador': 'Orchestrator', 'Planificador de equipo': 'Team planner', 'Definidor de habilidades': 'Skills definer',
    'Auditor': 'Auditor', 'Validador': 'Validator', 'Agente fantasma': 'Ghost agent', 'Lector de documentos': 'Document reader',
    'Lector de URLs': 'URL reader', 'Guardián del tiempo': 'Time guardian', 'Enrutador de tareas': 'Task router',
    'Escucha la petición del usuario y DIRIGE la creación del proyecto: coordina al equipo constructor y lo lleva de borrador a listo.': 'Listens to the user’s request and LEADS the project: coordinates the builder team and takes it from draft to ready.',
    'Arma el pipeline del equipo de trabajo desde los contratos (qué lee/escribe cada agente), resuelve el orden por dependencias y lo ejecuta. Reparte y verifica; no hace el trabajo.': 'Builds the team’s pipeline from the contracts (what each agent reads and writes), resolves the order from dependencies and runs it. It hands out and verifies; it does not do the work.',
    'Diseña el equipo de trabajo para el objetivo: decide cuántos agentes hacen falta, cuáles, y qué tarea cubre cada uno.': 'Designs the team for the goal: how many agents, which ones, and which task each one covers.',
    'Para cada agente del equipo define sus skills, herramientas y contrato (reads/writes). Prepara el encargo para el Constructor.': 'Defines each agent’s skills, tools and contract (reads/writes), and prepares the job for the Builder.',
    'Custodia la librería de habilidades. El Constructor le pide las skills y él las entrega; registra las nuevas (incluidas las del fantasma). Nunca se inventan skills fuera de la librería.': 'Keeps the skills library. The Builder asks it for skills and it hands them over; it registers new ones (including the ghost’s). No skill is ever invented outside the library.',
    'Fabrica cada agente como un spec validado, componiendo skills y tools que ya existen — nunca inventa.': 'Builds each agent as a validated spec from skills and tools that already exist. It never invents.',
    'Revisa los specs del Constructor (verificación determinista) antes de pasar al Validador.': 'Reviews the Builder’s specs (deterministic checks) before they reach the Validator.',
    'Build + evals (determinista): portero de calidad. Si falla, activa al Fantasma.': 'Build + evals (deterministic): the quality gate. If it fails, it calls the Ghost.',
    'El único que entrena: destila alumnos especializados (maestro→alumno) para subir el éxito del equipo.': 'The only one that trains: distills specialized students (master → student) to raise the team’s success rate.',
    'Escala a Claude Code cuando falta una herramienta/skill y el Validador falla. Nunca aplica nada solo — staging + aprobación humana.': 'Escalates to Claude Code when a tool or skill is missing and the Validator fails. It never applies anything by itself: staging + human approval.',
    'Lee PDFs y archivos de texto para el Entrenador.': 'Reads PDFs and text files for the Trainer.', 'Lee páginas web para el Entrenador.': 'Reads web pages for the Trainer.',
    "Recibe peticiones de automatización ('publica a las 3am') y crea/gestiona los schedules inteligentes con deadline awareness.": 'Takes automation requests (“publish at 3am”) and creates and manages deadline-aware schedules.',
    'Calcula cuándo lanzar una tarea basándose en el historial real de duraciones. Monitorea el run en curso y emite alerta si va a llegar tarde al deadline.': 'Works out when to start a task from the real history of durations. Watches the current run and raises an alert if it will miss the deadline.',
    'Recibe el trigger del schedule y lo dirige al proyecto correcto según el tipo de tarea.': 'Takes the schedule trigger and routes it to the right project for the task type.',

    // Agentes del Media Manager (servidor)
    'Extrae ids, clases y data-attrs reales de la página objetivo': 'Extracts the real ids, classes and data attributes of the target page',
    'Planifica acciones Playwright validadas contra selectores reales': 'Plans Playwright actions validated against real selectors',
    'Escribe guiones de voz cortos para reels en el idioma pedido': 'Writes short voice scripts for reels in the requested language',
    'Graba la página real con Playwright y genera el GIF': 'Records the real page with Playwright and makes the GIF',
    'Monta el reel MP4 con voz narrada y música': 'Builds the MP4 reel with narration and music',
    'Verifica el artefacto con ffprobe y criterios duros': 'Verifies the artifact with ffprobe and hard criteria',
    'apto ✓': 'pass ✓', 'página no accesible': 'page not reachable',
    'maestro': 'master',
    // Skills de la librería inicial (servidor)
    'Edición segura de código': 'Safe code editing',
    'Lee, busca, modifica y verifica archivos dentro de la carpeta Paradax con herramientas acotadas.': 'Reads, searches, edits and verifies files inside the Paradax folder with scoped tools.',
    'Verificacion dura': 'Hard verification', 'Pasa/repara con ffprobe: duracion minima y 0 pasos fallidos.': 'Pass/repair with ffprobe: minimum duration and 0 failed steps.',
    'Resumen de pagina': 'Page summary', 'Resume la estructura y secciones de una pagina web.': 'Summarizes the structure and sections of a web page.',
    'Guion de voz (es)': 'Voice script (es)', 'Escribe un guion de locucion corto en espanol latino.': 'Writes a short voice-over script in Latin American Spanish.',
    'Selectores reales': 'Real selectors', 'Extrae ids/clases/data-attrs reales de una pagina y planifica solo con ellos.': 'Extracts the real ids, classes and data attributes of a page and plans only with them.',
    'Sin alumno entrenado todavía': 'No trained student yet', 'Entrevístalo y decide.': 'Interview it and decide.',
    'Aún no hay exámenes. Se hacen cada noche tras entrenar, o a mano: python -m agent_os.training.graded_exam --model …': 'No exams yet. They run every night after training, or by hand: python -m agent_os.training.graded_exam --model …',
  })),
  // Textos montados con datos. Se prueban en orden; $1, $2… son los trozos capturados.
  patterns: [
    [/^(\d+) agentes$/, '$1 agents'],
    [/^alumno (.*)$/, 'student $1'],
    [/^estado: (.*)$/, 'status: $1'],
    [/^salida: (.*)$/, 'output: $1'],
    [/^faltan: (.*)$/, 'missing: $1'],
    [/^omitido: faltan (.*)$/, 'skipped: missing $1'],
    [/^empieza: (.*)$/, 'starts: $1'],
    [/^Último run: (.*)$/, (_, s) => `Last run: ${tr(s)}`],
    [/^Proyecto (.*?): (.*)$/, 'Project $1: $2'],
    [/^Tú → (.*)$/, 'You → $1'],
    [/^construye el equipo: (.*)$/, 'builds the team: $1'],
    [/^agente listo: (.*)$/, 'agent ready: $1'],
    [/^equipo listo \((\d+) agentes\)$/, 'team ready ($1 agents)'],
    [/^falló: (.*)$/, 'failed: $1'],
    [/^inventario: (\d+) selectores reales$/, 'inventory: $1 real selectors'],
    [/^plan (\S+): (\d+) acciones$/, 'plan $1: $2 actions'],
    [/^GIF ([\d.]+)s, (\d+) fallos$/, 'GIF $1s, $2 failures'],
    [/^reparar: (.*)$/, 'repair: $1'],
    [/^guion (\S*): (.*)$/, 'script $1: $2'],
    [/^(\d+)\/(\d+) ejemplos$/, '$1/$2 examples'],
    [/^(\d+) archivo\(s\)$/, '$1 file(s)'],
    [/^(\d+) casos$/, '$1 cases'],
    [/^(\d+) entrevistas$/, '$1 interviews'],
    [/^(\d+) entradas$/, '$1 entries'],
    [/^(\d+) en cuarentena$/, '$1 quarantined'],
    [/^versión (.*)$/, 'version $1'],
    [/^noche (.*)$/, 'night $1'],
    [/^(\d+) skills · (\d+) tools$/, '$1 skills · $2 tools'],
    [/^foco: (.*)$/, 'focus: $1'],
    [/^(\d+) ejemplos verificados$/, '$1 verified examples'],
    [/^en producción: (.*)$/, 'in production: $1'],
    [/^modelo propio en producción: (.*)$/, 'own model in production: $1'],
    [/^Escribe para hablar con (.*)\.$/, (_, n) => `Write to talk to ${tr(n)}.`],
    [/^No respondió: (.*)$/, 'No answer: $1'],
    [/^No se pudo cargar: (.*)$/, 'Could not load: $1'],
    [/^(.*) es interno: trabaja sin chat directo$/, (_, n) => `${tr(n)} is internal: it works without direct chat`],
    [/^(.*) trabaja internamente: no tiene chat$/, (_, n) => `${tr(n)} works internally: it has no chat`],
    [/^Agente construido: (.*)$/, 'Agent built: $1'],
    [/^lee (.*) · escribe (.*)$/, 'reads $1 · writes $2'],
    [/^Leído \((\S+), (\d+) caracteres\): ([\s\S]*)$/, 'Read ($1, $2 characters): $3'],
    [/^(\d+) búsquedas · (\d+) páginas · (\d+) s(.*)$/, (_, a, b, c, rest) => `${a} searches · ${b} pages · ${c} s${rest.replace(' · desde caché', ' · from cache')}`],
    [/^(\d+) fuentes · (\d+) páginas$/, '$1 sources · $2 pages'],
    [/^Recuerda (\d+) sesiones anteriores \((\d+) mensajes\) y sus casos de cuarentena\.$/, 'Remembers $1 previous sessions ($2 messages) and its quarantine cases.'],
    [/^días (.*) · termina antes de las (.*)$/, 'days $1 · finishes before $2'],
    [/^arranca hacia las (.*)$/, 'starts around $1'],
    [/^unos (\d+) min \(según (\d+) runs\)$/, 'about $1 min (from $2 runs)'],
    [/^unos (\d+) min \(estimación inicial\)$/, 'about $1 min (first estimate)'],
    [/^¿Quitar «(.*)» de este proyecto\? El agente sigue existiendo\.$/, 'Remove “$1” from this project? The agent still exists.'],
    [/^¿Eliminar el proyecto «(.*)» y sus agentes\?$/, 'Delete the project “$1” and its agents?'],
    [/^¿Eliminar el agente «(.*)»\? Se borra su spec\.$/, 'Delete the agent “$1”? Its spec is removed.'],
    [/^Entrenando (.*)…$/, 'Training $1…'],
    [/^Error al arrancar: (.*)$/, 'Startup error: $1'],
    // Estado de cada alumno (informe nocturno)
    [/^(\S+) lista para promoción$/, '$1 ready for promotion'],
    [/^(\S+) aprendiendo$/, '$1 learning'],
    [/^valores (.*)$/, 'values $1'],
    [/^racha (.*)$/, 'streak $1'],
    [/^resolvió (\d+)\/(\d+) anoche$/, 'solved $1/$2 last night'],
    [/^(\S+) en cuarentena: (.*)$/, '$1 quarantined: $2'],
  ],
};

/** Traduce un texto completo al idioma activo. Conserva los espacios de los extremos. */
function tr(s) {
  if (I18N.lang === 'es' || s == null) return s;
  const str = String(s);
  const core = str.trim();
  if (!core) return str;
  let out = I18N.en.get(core);
  if (out === undefined) {
    for (const [re, rep] of I18N.patterns) {
      if (re.test(core)) { out = core.replace(re, rep); break; }
    }
  }
  if (out === undefined) out = trParts(core);
  if (out === undefined) return str;
  return str.slice(0, str.indexOf(core)) + out + str.slice(str.indexOf(core) + core.length);
}

// Un texto compuesto se traduce por trozos si al menos uno de ellos se conoce.
function trParts(core) {
  for (const sep of ['\n\n', '\n', ' → ', ' · ', ': ', '. ']) {
    if (!core.includes(sep)) continue;
    // «Nombre: descripción»: solo el primer «: » separa; la descripción puede llevar más.
    const parts = sep === ': ' ? [core.slice(0, core.indexOf(sep)), core.slice(core.indexOf(sep) + 2)] : core.split(sep);
    const done = parts.map((p) => tr(p));
    if (done.some((d, i) => d !== parts[i])) return done.join(sep);
  }
  return undefined;
}

// Lo que escriben los modelos o el usuario, y el código, se deja tal cual.
const I18N_SKIP = '.msg-bubble, .prose, pre, textarea, script, style, .excerpt';
const I18N_ATTRS = ['placeholder', 'title', 'aria-label'];

function translateTree(root) {
  if (I18N.lang === 'es' || !root) return;
  if (root.nodeType === Node.TEXT_NODE) { translateText(root); return; }
  if (root.nodeType !== Node.ELEMENT_NODE) return;
  // Los atributos (placeholder, title…) son de la interfaz incluso en un textarea.
  for (const el of [root, ...root.querySelectorAll('[placeholder],[title],[aria-label]')]) translateAttrs(el);
  if (root.closest?.(I18N_SKIP)) return;
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
    acceptNode: (n) => (n.nodeType === Node.ELEMENT_NODE && n.matches(I18N_SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    if (n.nodeType === Node.TEXT_NODE) translateText(n);
  }
}

function translateAttrs(el) {
  if (el.closest('.msg-bubble, .prose')) return;
  for (const a of I18N_ATTRS) {
    if (!el.hasAttribute(a)) continue;
    const v = tr(el.getAttribute(a));
    if (v !== el.getAttribute(a)) el.setAttribute(a, v);
  }
}

function translateText(node) {
  if (node.parentElement?.closest(I18N_SKIP)) return;
  const v = tr(node.nodeValue);
  if (v !== node.nodeValue) node.nodeValue = v;
}

function setupI18n() {
  let saved = null;
  try { saved = localStorage.getItem('paradax.lang'); } catch { /* sin storage */ }
  I18N.lang = saved || ((navigator.language || 'es').toLowerCase().startsWith('es') ? 'es' : 'en');
  document.documentElement.lang = I18N.lang;
  // Los avisos de confirmación también se traducen.
  const nativeConfirm = window.confirm.bind(window);
  window.confirm = (msg) => nativeConfirm(tr(msg));
  const sw = document.getElementById('langSwitch');
  sw?.querySelectorAll('[data-lang]').forEach((b) => {
    b.classList.toggle('active', b.dataset.lang === I18N.lang);
    b.addEventListener('click', () => {
      if (b.dataset.lang === I18N.lang) return;
      try { localStorage.setItem('paradax.lang', b.dataset.lang); } catch { /* sin storage */ }
      location.reload();
    });
  });
  if (I18N.lang === 'es') return;
  translateTree(document.body);
  new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.type === 'characterData') translateText(m.target);
      else if (m.type === 'attributes') translateAttrs(m.target);
      else m.addedNodes.forEach((n) => translateTree(n));
    }
  }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: I18N_ATTRS });
}
