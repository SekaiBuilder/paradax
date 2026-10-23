"""La fábrica de agentes de Paradax.

Capa meta sobre el pipeline de agentes: los dos pilares —Constructor y
Entrenador— y sus órganos de apoyo (Skill Master, Auditor, Validador y el
agente fantasma). Esta carpeta arranca con la FUNDACIÓN:

- `skill.py`        — el modelo `Skill` (la unidad reutilizable que el
                      Constructor compone para fabricar agentes).
- `skill_wire.py`   — el códec compacto (extiende el wire protocol a skills):
                      menos peso en disco, parseo más rápido, round-trip lossless.
- `skill_master.py` — la memoria de skills, persistida en formato wire.

Ver `docs/AGENT_FACTORY.md` para la arquitectura completa.
"""

from .skill import Skill, SkillKind
from .skill_master import SkillMaster

__all__ = ["Skill", "SkillKind", "SkillMaster"]
