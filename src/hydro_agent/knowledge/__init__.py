"""Lightweight knowledge platform for Hydro-Agent.

The knowledge package keeps standards and project policies outside executable
Gate code. Runtime components consume structured, versioned knowledge through
``KnowledgeRepository`` while the existing Agent loop and action contracts stay
unchanged.
"""

from hydro_agent.knowledge.repository import KnowledgeRepository

__all__ = ["KnowledgeRepository"]
