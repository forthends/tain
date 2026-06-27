"""Standard Plugin factory mapping for AgentKernel initialization."""

from tain_agent.plugins.identity import IdentityPlugin
from tain_agent.plugins.memory import MemoryPlugin
from tain_agent.plugins.tool import ToolPlugin
from tain_agent.plugins.skill import SkillPlugin
from tain_agent.plugins.knowledge import KnowledgePlugin
from tain_agent.plugins.workflow import WorkflowPlugin
from tain_agent.plugins.collaboration import CollaborationPlugin

STANDARD_FACTORIES = {
    "identity": IdentityPlugin,
    "memory": MemoryPlugin,
    "tool": ToolPlugin,
    "skill": SkillPlugin,
    "knowledge": KnowledgePlugin,
    "workflow": WorkflowPlugin,
    "collaboration": CollaborationPlugin,
}
