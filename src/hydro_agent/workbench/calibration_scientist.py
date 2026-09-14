"""Calibration-scientist workbench alias over the shared real XAJ evidence stack."""

from __future__ import annotations

from hydro_agent.workbench.real import RealWorkbenchKernel


class CalibrationScientistWorkbenchKernel(RealWorkbenchKernel):
    """Use the production evidence implementation with a different Agent provider.

    This class intentionally does not override ``_diagnose`` or any evidence
    service. The Yaogu deterministic smoke and the product API must exercise the
    same pre-development, full-calibration and Gate-feedback evidence path.
    """
