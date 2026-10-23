from .action_planner import ActionPlannerAgent
from .browser_recorder import BrowserRecorderAgent
from .page_inspector import PageInspectorAgent
from .script_writer import ScriptWriterAgent
from .verifier import VerifierAgent
from .video_builder import VideoBuilderAgent

# Instancias únicas: los agentes no guardan estado de run (la memoria vive en
# el contexto del pipeline), así que compartirlos es seguro.
REGISTRY = {
    agent.contract.id: agent
    for agent in (
        PageInspectorAgent(),
        ActionPlannerAgent(),
        ScriptWriterAgent(),
        BrowserRecorderAgent(),
        VideoBuilderAgent(),
        VerifierAgent(),
    )
}

__all__ = [
    "REGISTRY",
    "PageInspectorAgent",
    "ActionPlannerAgent",
    "ScriptWriterAgent",
    "BrowserRecorderAgent",
    "VideoBuilderAgent",
    "VerifierAgent",
]
