"""Lightweight knowledge platform for Hydro-Agent.

Standards/project policies remain versioned structured knowledge, while
calibration cases preserve experience as auditable evidence rather than model
weights. This keeps V1 retrieval-friendly without requiring fine-tuning/RL.
"""

from hydro_agent.knowledge.cases import (
    CalibrationCase,
    CalibrationCaseMemory,
    lesson_from_gate,
)
from hydro_agent.knowledge.repository import KnowledgeRepository

__all__ = [
    "CalibrationCase",
    "CalibrationCaseMemory",
    "KnowledgeRepository",
    "lesson_from_gate",
]
