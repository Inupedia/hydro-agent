"""Teacher v6 kernel adapter. All timesteps evolve one native Model instance."""
import hashlib
import json
from pathlib import Path

from .vendor import xaj as native

MODEL_VERSION = "teacher-xaj-v6-20260908"
MODEL_SHA256 = "9175b0edd8c80605a47463ceafe6fcaac568cdac49f98a4c00f5470e802bb8ff"


def simulate(scheme, basin, inputs):
    """Return post-warmup discharge in m3/s; preserve native cold-start units."""
    import numpy as np

    if hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest() != MODEL_SHA256:
        raise ValueError("teacher XAJ source checksum mismatch")
    p = scheme.parameters
    raw = dict(rivid=1, area=basin.area_km2, dp=scheme.routing.dp,
               kc=p["K"], b=p["B"], c=p["C"], imp=p["IM"],
               wm=p["UM"] + p["LM"] + p["DM"], wum=p["UM"], wlm=p["LM"],
               sm=p["SM"], ex=p["EX"], kg=p["KG"], ki=p["KI"],
               cg=p["CG"], ci=p["CI"], cs=p["CS"], lag=p["L"],
               ke=scheme.routing.ke, xe=scheme.routing.xe)
    model = native.Model([native.make_parameter(raw, 86400)], 86400)
    values = []
    for row in inputs:
        result = model.step([float(row[0, 0])], [float(row[0, 1])])
        values.append(float(result.sum_qsig))
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("invalid teacher XAJ numerical result")
    return values[scheme.warmup_days:]


def _bounds_payload():
    return json.loads((Path(__file__).parent / "vendor/parameter_bounds.yaml").read_text(
        encoding="utf-8"))["parameters"]


def load_param_ranges():
    bounds = _bounds_payload()
    mapping = {"K": "KC", "IM": "IMP", "UM": "WUM", "LM": "WLM", "L": "LAG"}
    from .contracts import XajScheme
    ranges = {}
    for name in XajScheme.PARAMETER_ORDER:
        if name == "DM":
            # Compatibility coordinate: WM = UM + LM + DM. Joint WM bound is
            # enforced by the calibration caller, not by independent sampling.
            ranges[name] = (0.001, bounds["WM"]["max"] - bounds["WUM"]["min"]
                            - bounds["WLM"]["min"])
        else:
            item = bounds[mapping.get(name, name)]
            ranges[name] = (float(item["min"]), float(item["max"]))
    return ranges


def load_calibratable_params() -> tuple[str, ...]:
    """Map teacher calibration flags onto this adapter's scheme coordinates.

    The teacher source calibrates WM rather than WUM/WLM independently. This adapter
    represents WM as UM + LM + DM, so DM is the single residual coordinate used to
    change total tension-water capacity while UM/LM remain fixed.
    """
    bounds = _bounds_payload()
    native_to_scheme = {
        "KC": "K",
        "B": "B",
        "WM": "DM",
        "SM": "SM",
        "KG": "KG",
        "KI": "KI",
        "CI": "CI",
        "CS": "CS",
    }
    selected = {
        native_to_scheme[name]
        for name, item in bounds.items()
        if bool(item.get("calibrate")) and name in native_to_scheme
    }
    from .contracts import XajScheme
    return tuple(name for name in XajScheme.PARAMETER_ORDER if name in selected)
