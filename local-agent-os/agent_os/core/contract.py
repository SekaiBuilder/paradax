from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel


@dataclass(frozen=True)
class AgentContract:
    """Contrato público de un agente: qué hace, qué puede tocar y qué devuelve.

    - `reads`: únicas claves del contexto que el agente recibe (memoria limitada).
    - `writes`: clave bajo la que el pipeline guarda su salida.
    - `allowed_tools`: nombres de herramientas que puede invocar; vacío = solo LLM.
    - `output_model`: schema pydantic obligatorio de la salida.
    """

    id: str
    name: str
    description: str
    reads: tuple[str, ...]
    writes: str
    output_model: type[BaseModel]
    allowed_tools: tuple[str, ...] = field(default=())
    uses_llm: bool = False
    max_retries: int = 1
    # Visibilidad: `contactable` = el usuario puede chatear con él. `on_demand` =
    # agente durmiente que solo se activa cuando se le necesita (se ve en el
    # grafo pero, si además no es contactable, no se puede hablar con él).
    contactable: bool = True
    on_demand: bool = False
    # Sandbox: si True (por defecto), el agente no puede llamar tools directamente;
    # todas las tool calls se enrutan a través del SandboxBus → Sentinel-Watch.
    # Solo Ghost y los Sentinelas usan sandbox=False (tienen acceso irrestricto).
    sandbox: bool = True

    def summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "reads": list(self.reads),
            "writes": self.writes,
            "allowed_tools": list(self.allowed_tools),
            "uses_llm": self.uses_llm,
            "output_schema": self.output_model.__name__,
        }
