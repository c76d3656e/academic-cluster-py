"""
Agent 模块 - 定义 LangGraph 中的 Agent

Agent 是具有自主决策能力的 LLM 节点，可以决定调用哪些工具、何时停止。
与普通节点不同，Agent 节点使用 LLM 进行推理和决策。
"""

from .evidence_generation import create_evidence_agent
from .kg_extraction import create_kg_extraction_agent
from .query_planning import create_query_planning_agent
from .writing import create_writing_agent

__all__ = [
    "create_evidence_agent",
    "create_kg_extraction_agent",
    "create_query_planning_agent",
    "create_writing_agent",
]
