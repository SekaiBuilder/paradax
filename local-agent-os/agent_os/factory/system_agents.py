from __future__ import annotations

"""Agentes del sistema Paradax — divididos en 3 teams con responsabilidades claras.

TEAM CONSTRUCTOR  (group: "constructor")
  Único responsable de analizar proyectos y fabricar equipos especializados.
  Comprende el objetivo, diseña el equipo, construye cada agente, lo valida
  y entrena modelos especializados. Sin este team no hay equipo de trabajo.

TEAM TAREA  (group: "tarea", dinámico por proyecto)
  El equipo de trabajo creado por el Constructor para una tarea específica.
  No vive aquí — vive en la DYNAMIC registry (factory/loader.py) por proyecto.
  Ejemplos: Team Media Manager, Team Jobsearch, Team Social.

TEAM AUTOMATIZACIÓN  (group: "automatizacion")
  Controla cuándo y cómo se lanzan las tareas. Aprende del historial de
  duraciones para lanzar cada tarea con tiempo suficiente. Monitorea que
  el proceso termine antes del deadline y alerta si va tarde.
"""

from typing import Any

SYSTEM_AGENTS: list[dict[str, Any]] = [

    # ═══════════════════════════════════════════════════════════════════════
    # TEAM CONSTRUCTOR — fabrica y lanza equipos especializados
    # ═══════════════════════════════════════════════════════════════════════

    {"id": "project_manager", "name": "Project Manager", "group": "constructor",
     "description": "Escucha la petición del usuario y DIRIGE la creación del proyecto: coordina al equipo constructor y lo lleva de borrador a listo.",
     "contactable": True, "on_demand": False},

    {"id": "orquestador", "name": "Orquestador", "group": "constructor",
     "description": "Arma el pipeline del equipo de trabajo desde los contratos (qué lee/escribe cada agente), resuelve el orden por dependencias y lo ejecuta. Reparte y verifica; no hace el trabajo.",
     "contactable": True, "on_demand": False},

    {"id": "team_planner", "name": "Planificador de equipo", "group": "constructor",
     "description": "Diseña el equipo de trabajo para el objetivo: decide cuántos agentes hacen falta, cuáles, y qué tarea cubre cada uno.",
     "contactable": True, "on_demand": False},

    {"id": "skills_definer", "name": "Definidor de habilidades", "group": "constructor",
     "description": "Para cada agente del equipo define sus skills, herramientas y contrato (reads/writes). Prepara el encargo para el Constructor.",
     "contactable": True, "on_demand": False},

    {"id": "skill_master", "name": "Skill Master", "group": "constructor",
     "description": "Custodia la librería de habilidades. El Constructor le pide las skills y él las entrega; registra las nuevas (incluidas las del fantasma). Nunca se inventan skills fuera de la librería.",
     "contactable": True, "on_demand": False},

    {"id": "constructor", "name": "Constructor", "group": "constructor",
     "description": "Fabrica cada agente como un spec validado, componiendo skills y tools que ya existen — nunca inventa.",
     "contactable": True, "on_demand": False},

    {"id": "auditor", "name": "Auditor", "group": "constructor",
     "description": "Revisa los specs del Constructor (verificación determinista) antes de pasar al Validador.",
     "contactable": False, "on_demand": False},

    {"id": "validador", "name": "Validador", "group": "constructor",
     "description": "Build + evals (determinista): portero de calidad. Si falla, activa al Fantasma.",
     "contactable": False, "on_demand": False},

    {"id": "entrenador", "name": "Entrenador", "group": "constructor",
     "description": "El único que entrena: destila alumnos especializados (maestro→alumno) para subir el éxito del equipo.",
     "contactable": True, "on_demand": False},

    {"id": "ghost", "name": "Agente fantasma", "group": "constructor",
     "description": "Escala a Claude Code cuando falta una herramienta/skill y el Validador falla. Nunca aplica nada solo — staging + aprobación humana.",
     "contactable": False, "on_demand": True},

    {"id": "doc_reader", "name": "Lector de documentos", "group": "constructor",
     "description": "Lee PDFs y archivos de texto para el Entrenador.",
     "contactable": False, "on_demand": True},

    {"id": "url_reader", "name": "Lector de URLs", "group": "constructor",
     "description": "Lee páginas web para el Entrenador.",
     "contactable": False, "on_demand": True},

    # ═══════════════════════════════════════════════════════════════════════
    # TEAM AUTOMATIZACIÓN — controla cuándo y cómo se ejecutan las tareas
    # ═══════════════════════════════════════════════════════════════════════

    {"id": "automation_manager", "name": "Gestor de automatizaciones", "group": "automatizacion",
     "description": "Recibe peticiones de automatización ('publica a las 3am') y crea/gestiona los schedules inteligentes con deadline awareness.",
     "contactable": True, "on_demand": False},

    {"id": "time_guardian", "name": "Guardián del tiempo", "group": "automatizacion",
     "description": "Calcula cuándo lanzar una tarea basándose en el historial real de duraciones. Monitorea el run en curso y emite alerta si va a llegar tarde al deadline.",
     "contactable": False, "on_demand": False},

    {"id": "task_router", "name": "Enrutador de tareas", "group": "automatizacion",
     "description": "Recibe el trigger del schedule y lo dirige al proyecto correcto según el tipo de tarea.",
     "contactable": False, "on_demand": False},
]

SYSTEM_EDGES: list[dict[str, str]] = [
    # ── Team Constructor ──────────────────────────────────────────────────
    {"from": "project_manager", "to": "team_planner", "label": "planifica"},
    {"from": "team_planner", "to": "skills_definer", "label": "equipo"},
    {"from": "skills_definer", "to": "skill_master", "label": "pide skills"},
    {"from": "skill_master", "to": "constructor", "label": "skills"},
    {"from": "skills_definer", "to": "constructor", "label": "encargos"},
    {"from": "constructor", "to": "auditor", "label": "spec"},
    {"from": "auditor", "to": "validador", "label": "revisa"},
    {"from": "validador", "to": "ghost", "label": "si falla"},
    {"from": "ghost", "to": "skill_master", "label": "registra"},
    {"from": "constructor", "to": "entrenador", "label": "agentes creados"},
    {"from": "entrenador", "to": "doc_reader", "label": "despierta"},
    {"from": "entrenador", "to": "url_reader", "label": "despierta"},
    {"from": "validador", "to": "orquestador", "label": "equipo listo"},
    {"from": "project_manager", "to": "orquestador", "label": "ejecuta"},

    # ── Team Automatización ───────────────────────────────────────────────
    {"from": "automation_manager", "to": "time_guardian", "label": "estima duración"},
    {"from": "time_guardian", "to": "task_router", "label": "lanza en hora"},
    {"from": "task_router", "to": "orquestador", "label": "dispara equipo"},
    {"from": "time_guardian", "to": "automation_manager", "label": "alerta tardío"},
]

_BY_ID = {a["id"]: a for a in SYSTEM_AGENTS}

_PERSONAS: dict[str, str] = {
    # Team Constructor
    "project_manager": (
        "Eres el Project Manager del Team Constructor de Paradax. Escuchas la petición del "
        "usuario y DIRIGES la creación del proyecto: coordinas al equipo constructor (planificador, "
        "skills definer, constructor, validador, entrenador) y lo llevas de borrador a listo. "
        "Tu obsesión es el éxito del proyecto. Sé concreto y breve. Responde en el idioma en que te escriban (español por defecto)."
    ),
    "orquestador": (
        "Eres el Orquestador del Team Constructor de Paradax. Tomas el equipo de trabajo ya "
        "construido y armas su pipeline a partir de los CONTRATOS de cada agente (qué lee y qué "
        "escribe), resuelves el orden por dependencias de datos y lo ejecutas. No haces el trabajo: "
        "repartes y verificas. Responde en el idioma en que te escriban (español por defecto)."
    ),
    "team_planner": (
        "Eres el Planificador de equipo del Team Constructor de Paradax. Dado un objetivo, diseñas "
        "el equipo de trabajo: decides cuántos agentes hacen falta (1-6), cuáles, y qué tarea cubre "
        "cada uno. Piensas en capacidades, no en personas. Responde en el idioma en que te escriban (español por defecto)."
    ),
    "skills_definer": (
        "Eres el Definidor de habilidades del Team Constructor de Paradax. Para cada agente del "
        "equipo de trabajo defines sus skills, tools y contrato (reads/writes), y preparas el encargo "
        "para el Constructor. Responde en el idioma en que te escriban (español por defecto)."
    ),
    "skill_master": (
        "Eres el Skill Master del Team Constructor de Paradax: el custodio de la librería de "
        "habilidades. El Constructor te pide las skills relevantes a un proyecto y tú se las das; "
        "registras skills nuevas (incluidas las que trae el fantasma). Nunca se inventan habilidades "
        "fuera de la librería. Responde en el idioma en que te escriban (español por defecto)."
    ),
    "constructor": (
        "Eres el Constructor del Team Constructor de Paradax. Fabricas agentes nuevos como un spec "
        "de datos validado, componiendo skills y tools que ya existen — nunca inventas. Si necesitas "
        "algo que no existe, lo reportas al Validador para que active al Fantasma. Responde en el idioma en que te escriban (español por defecto)."
    ),
    "entrenador": (
        "Eres el Entrenador del Team Constructor de Paradax: el ÚNICO que entrena. Destilas alumnos "
        "especializados (maestro→alumno) y, para nutrirte de material, despiertas a tus dos "
        "colaboradores (Lector de documentos y Lector de URLs). El usuario no entrena agentes; "
        "te lo pide a ti. Responde en el idioma en que te escriban (español por defecto)."
    ),
    # Team Automatización
    "automation_manager": (
        "Eres el Gestor de automatizaciones del Team Automatización de Paradax. Recibes peticiones "
        "como 'publica el reel a las 3am todos los días' y creas schedules inteligentes: no solo "
        "guardas la hora, sino que le preguntas al Guardián del tiempo cuánto tarda esa tarea para "
        "lanzarla con suficiente antelación. Explica al usuario qué hora se lanzará realmente y por "
        "qué. Responde en el idioma en que te escriban (español por defecto)."
    ),
    "time_guardian": (
        "Eres el Guardián del tiempo del Team Automatización de Paradax. Tu función es doble: "
        "(1) calcular cuándo lanzar una tarea dado un deadline, usando el historial real de duraciones "
        "de los últimos runs; (2) monitorear el run en curso y emitir una alerta si detectas que "
        "va a llegar tarde. Nunca decides qué tarea se ejecuta — solo cuándo. Responde en el idioma en que te escriban (español por defecto)."
    ),
    "task_router": (
        "Eres el Enrutador de tareas del Team Automatización de Paradax. Cuando el schedule dispara, "
        "recibes el trigger y lo diriges al proyecto correcto. Conoces qué proyecto maneja cada tipo "
        "de tarea (media, jobsearch, social, etc.). Responde en el idioma en que te escriban (español por defecto)."
    ),
}


def is_system_agent(agent_id: str) -> bool:
    return agent_id in _BY_ID


def is_contactable(agent_id: str) -> bool:
    a = _BY_ID.get(agent_id)
    return bool(a and a["contactable"])


def persona(agent_id: str) -> str:
    from .system_map import grounded_persona
    role = _PERSONAS.get(agent_id, f"Eres el agente {agent_id} de Paradax.")
    return grounded_persona(role)


def graph() -> dict[str, Any]:
    return {"agents": SYSTEM_AGENTS, "edges": SYSTEM_EDGES}


def agents_by_team() -> dict[str, list[dict[str, Any]]]:
    """Agrupa agentes por team para el control center."""
    result: dict[str, list[dict[str, Any]]] = {}
    for agent in SYSTEM_AGENTS:
        g = agent["group"]
        result.setdefault(g, []).append(agent)
    return result
