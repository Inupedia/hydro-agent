"""Versioned technical standards and project Gate policies.

This package owns normative configuration. Agent Skills may explain when a
standard is relevant, but cannot edit or override these thresholds at runtime.
"""

from hydro_agent.standards.repository import DEFAULT_GRADE_DC_BING, StandardRepository

__all__ = ["DEFAULT_GRADE_DC_BING", "StandardRepository"]
