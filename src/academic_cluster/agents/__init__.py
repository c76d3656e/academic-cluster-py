"""Production multi-agent workflow public API.

The LangGraph supervisor coordinates a bounded research agent, deterministic
analysis phase, outline/writing phase, and peer-review agent.
"""

from .agent_graph import (
    AgentState,
    compile_agent_graph,
    run_agent_graph,
)
from .orchestrator import (
    OrchestratorAgent,
    create_orchestrator,
)
from .peer_review_team import run_peer_review
from .research_team import create_research_agent, run_research
from .writing_team import run_writing

__all__ = [
    "AgentState",
    "OrchestratorAgent",
    "compile_agent_graph",
    "create_orchestrator",
    "create_research_agent",
    "run_agent_graph",
    "run_peer_review",
    "run_research",
    "run_writing",
]
