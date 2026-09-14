"""Knowledge platform boundaries for Hydro-Agent.

Normative standards, governed advisory claims and audited calibration cases stay
separate so expert material cannot silently become execution authority.
"""

from hydro_agent.knowledge.basin_priors import derive_basin_hydro_profile
from hydro_agent.knowledge.cases import (
    CalibrationCase,
    CalibrationCaseMemory,
    lesson_from_gate,
)
from hydro_agent.knowledge.catalog import GovernedKnowledgeRepository
from hydro_agent.knowledge.expert import (
    BasinHydroProfile,
    ExpertAdvice,
    ExpertKnowledgeRepository,
)
from hydro_agent.knowledge.governance import (
    KnowledgeApplicability,
    KnowledgeAuthority,
    KnowledgeEntry,
    KnowledgeEvidenceBundle,
    KnowledgeFilterDecision,
    KnowledgeQueryContext,
    select_knowledge_entries,
)
from hydro_agent.knowledge.repository import KnowledgeRepository

__all__ = [
    "BasinHydroProfile",
    "CalibrationCase",
    "CalibrationCaseMemory",
    "ExpertAdvice",
    "ExpertKnowledgeRepository",
    "GovernedKnowledgeRepository",
    "KnowledgeApplicability",
    "KnowledgeAuthority",
    "KnowledgeEntry",
    "KnowledgeEvidenceBundle",
    "KnowledgeFilterDecision",
    "KnowledgeQueryContext",
    "KnowledgeRepository",
    "derive_basin_hydro_profile",
    "lesson_from_gate",
    "select_knowledge_entries",
]
