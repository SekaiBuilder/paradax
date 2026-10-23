from __future__ import annotations

"""Harvest: convierte la EXPERIENCIA real de los agentes en datasets propios.

Este módulo cierra el circuito "agente de prompt → modelo especialista":
cada run de proyecto COMPLETADO deja eventos `agent_completed` con el input
(reads resueltos) y el output valid