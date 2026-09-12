"""Lightweight knowledge platform for Hydro-Agent.

Normative standards, advisory expert priors and audited calibration cases are
kept as different knowledge classes. This prevents heuristics from being
silently promoted into Gate rules while still allowing the Agent to learn from
external expertise and local evidence.
"""

from hydro_agent.knowledge.basin_priors import derive_basin_hydro_profile
from hydro_agent.knowledge.cases import (
    CalibrationCase,
    CalibrationCaseMemory,
    lesson_from_gate,
)
from hydro_agent.knowledge.expert import (
    BasinHydroProfile,
    ExpertAdvice,
    ExpertKnowledgeRepository,
    ExpertRule,
)
from hydro_agent.knowledge.repository import KnowledgeRepository

__all__ = [
    "BasinHydroProfile",
    "CalibrationCase",
    "CalibrationCaseMemory",
    "ExpertAdvice",
    "ExpertKnowledgeRepository",
    "ExpertRule",
    "KnowledgeRepository",
    "derive_basin_hydro_profile",
    "lesson_from_gate",
]
