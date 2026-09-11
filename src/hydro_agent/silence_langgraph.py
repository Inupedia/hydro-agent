"""Silence LangGraph's import-time serializer warning until we bump langgraph.

langchain_core prepends a 'default' filter for LangChainPendingDeprecationWarning,
so PYTHONWARNINGS cannot hide it. Import this module before any langgraph import.
"""

from __future__ import annotations

import warnings

from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

warnings.filterwarnings(
    "ignore",
    message="The default value of `allowed_objects` will change in a future version.",
    category=LangChainPendingDeprecationWarning,
)
