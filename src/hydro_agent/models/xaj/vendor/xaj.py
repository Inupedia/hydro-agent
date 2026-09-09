#!/usr/bin/env python3
"""Single-file XAJ model with bounded deep ET and complete Python checkpoints.

Run in a case directory, or use --case-dir. Requires numpy and netCDF4 only.
All model arithmetic uses float32, like the original default Fortran REAL.
See README_python.md for compatibility limits and MODEL_REVIEW.md for known
scientific/driver issues deliberately retained for reproducibility.
"""

import argparse
import hashlib
import json
import os
from collections import deque
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import warnings
import uuid

import numpy as np

F = np.float32
ZERO, ONE, HALF = F(0), F(1), F(0.5)
DAY, HOUR = F(86400), F(3600)
MAXDP = 50
PARAMETERS = "rivid area dp kc b c imp wm wum wlm sm ex kg ki cg ci cs lag ke xe".split()
STATES = "wu wl wd s fr qs qi qg qs_cs qi_cs qg_cs".split()
ROUTING = "qxs qxi qxg".split()
TOTALS = "sum_qg sum_qig sum_qsig".split()
ROUTING_LAYOUT = "zone_reach_v2"
RESTART_VERSION = 1


def netcdf_path(path):
    """Prefer a path relative to cwd for Windows HDF5/non-ASCII compatibility."""
    path = Path(path)
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def read_namelist(path):
    """Read the scalar subset used by xaj_namelist, including quoted paths.

    This intentionally isn't a general Fortran namelist parser. Unknown keys,
    arrays and malformed assignments are rejected instead of silently ignored.
    """
    token = re.compile(r"\s+|![^\n]*|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[&,=/]|[^\s&,=/!]+")
    tokens = [t for t in token.findall(Path(path).read_text())
              if not t.isspace() and not t.startswith("!")]
    if [t.lower() for t in tokens[:2]] != ["&", "xaj_namelist"]:
        raise ValueError("Expected &xaj_namelist")
    result = dict(fnm_parameters="parameters.csv", fnm_restart_in="", fnm_output="", fnm_restart_out="")
    strings = set(result)
    result.update(start_minute=0, start_second=0)
    integers = set("nzone nstep start_year start_month start_day start_hour start_minute start_second".split())
    i = 2
    while i < len(tokens) and tokens[i] != "/":
        if tokens[i] == ",":
            i += 1
            continue
        if i + 2 >= len(tokens) or tokens[i + 1] != "=":
            raise ValueError("Malformed namelist assignment")
        key, value = tokens[i].lower(), tokens[i + 2]
        if key in strings:
            if value[0] not in "'\"" or value[-1] != value[0]:
                raise ValueError(f"{key} must be quoted")
            result[key] = value[1:-1].replace(value[0] * 2, value[0])
        elif key in integers:
            result[key] = int(value)
        elif key == "dt":
            result[key] = F(value.lower().replace("d", "e"))
        else:
            raise ValueError(f"Unsupported namelist key: {key}")
        i += 3
    if i != len(tokens) - 1 or tokens[i:] != ["/"]:
        raise ValueError("Expected final namelist terminator /")
    missing = (integers | {"dt"}) - result.keys()
    if missing:
        raise ValueError(f"Missing namelist values: {sorted(missing)}")
    if result["nzone"] < 1 or result["nstep"] < 1:
        raise ValueError("nzone and nstep must be positive")
    if not np.isfinite(result["dt"]) or result["dt"] < HALF:
        raise ValueError("dt must be finite and at least 0.5 seconds")
    return SimpleNamespace(**result)


def make_parameter(values, dt, zone_index=0):
    """Validate one raw parameter mapping and apply the driver's dt conversion.

    This is the in-memory counterpart of ``read_parameters`` for callers such
    as calibration and academy tools. Values use the original 20-column names
    and remain subject to the same float32 coercion, validation and warnings.
    ``zone_index`` is zero based and is used only in diagnostics.
    """
    missing = set(PARAMETERS) - set(values)
    unknown = set(values) - set(PARAMETERS)
    if missing or unknown:
        raise ValueError(
            f"Zone {zone_index + 1}: parameter keys mismatch; "
            f"missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    data = {
        name: (int(value) if name in ("rivid", "dp") else F(value))
        for name, value in values.items()
    }
    p = SimpleNamespace(**data)
    if not all(np.isfinite(v) for v in data.values()):
        raise ValueError(f"Zone {zone_index + 1}: nonfinite parameter")
    p.lag = int(p.lag)  # Fortran INT truncates the single precision value.
    p.wdm = p.wm - p.wum - p.wlm
    if not (p.area > ZERO and p.wm > ZERO and p.wum >= ZERO and
            p.wlm > ZERO and p.wdm >= ZERO and p.sm > ZERO and
            ZERO <= p.imp < ONE and p.b >= ZERO and p.ex >= ZERO and
            p.kc >= ZERO and ZERO <= p.c <= ONE and
            p.kg >= ZERO and p.ki >= ZERO and ZERO < p.kg + p.ki <= ONE and
            all(ZERO <= v <= ONE for v in (p.cg, p.ci, p.cs)) and
            0 <= p.dp < MAXDP and p.lag >= 0):
        raise ValueError(f"Zone {zone_index + 1}: invalid parameter range")
    dt = F(dt)
    if dt != DAY:
        if p.kg == ZERO:
            raise ValueError("KG=0 has undefined subdaily conversion in Fortran")
        bb1, bb2 = p.ki + p.kg, p.ki / p.kg
        p.kg = (ONE - (ONE - bb1) ** (dt / DAY)) / (ONE + bb2)
        p.ki = p.kg * bb2
        p.ci = p.ci ** (dt / DAY)
        p.cg = p.cg ** (dt / DAY)
    denominator = p.ke - p.ke * p.xe + HALF * (dt / HOUR)
    if denominator == ZERO:
        raise ValueError("Zero Muskingum denominator")
    if p.dp and not (p.ke > ZERO and ZERO <= p.xe <= HALF and
                     F(2) * p.ke * p.xe <= dt / HOUR <=
                     F(2) * p.ke * (ONE - p.xe)):
        warnings.warn(f"Zone {zone_index + 1}: Muskingum coefficients may produce negative flow")
    return p


def read_parameters(path, nzone, dt):
    params = []
    with Path(path).open() as stream:
        next(stream)  # Original driver skips the header and reads positionally.
        for index in range(nzone):
            values = re.split(r"[\s,]+", next(stream, "").strip())
            if len(values) != len(PARAMETERS):
                raise ValueError(f"{path}: zone {index + 1}: expected 20 columns")
            data = {name: (int(value) if name in ("rivid", "dp") else
                           F(value.lower().replace("d", "e")))
                    for name, value in zip(PARAMETERS, values)}
            params.append(make_parameter(data, dt, zone_index=index))
    return params


def cold_state(p):
    z = SimpleNamespace(wu=F(0.8) * p.wum, wl=F(0.8) * p.wlm,
                        wd=F(0.8) * p.wdm, s=F(10), fr=F(0.05))
    for name in STATES[5:]:
        setattr(z, name, F(2))
    for name in ROUTING:
        setattr(z, name, np.zeros(MAXDP, dtype=F))
    z.w = z.wu + z.wl + z.wd
    return z


def runoff_yield(p, z, dt, prec, ep):
    """Three-layer ET and tension-water runoff; prec/ep are in mm/s."""
    w, wu, wl, wd = z.w, z.wu, z.wl, z.wd
    wmm = (ONE + p.b) * p.wm / (ONE - p.imp)
    ek = ep * p.kc * dt
    pe = prec * dt - ek
    if abs(pe) < F(1.e-3):
        pe = ZERO
    nd = int(pe / F(5)) + 1 if pe > F(5) else 1
    if nd > 100:
        raise ValueError("Net precipitation requires >100 subdivisions (Fortran buffer limit)")
    ped = np.full(nd, pe / F(nd), dtype=F)
    rd = np.zeros(nd, dtype=F)  # Fortran leaves this undefined on dry steps; never needed there.
    r = ZERO
    if pe > ZERO:
        a = (wmm if abs(w - p.wm) < F(1.e-3) else
             wmm * (ONE - (ONE - w / p.wm) ** (ONE / (ONE + p.b))))
        peds = ZERO
        for i in range(nd):
            a = a + ped[i]
            peds = peds + ped[i]
            previous = r
            r = peds - (p.wm - w)
            if a < wmm:
                r = r + p.wm * (ONE - a / wmm) ** (ONE + p.b)
            rd[i] = r - previous
        eu, el, ed = ek, ZERO, ZERO
        if wu + pe - r > p.wum:
            if wu + pe - r - p.wum + wl > p.wlm:
                wu, wl = p.wum, p.wlm
                wd = w + peds - r - wu - wl
            else:
                wl = wl + wu + pe - r - p.wum
                wu = p.wum
        else:
            wu = wu + pe - r
    elif wu + pe >= ZERO:
        eu, el, ed = ek, ZERO, ZERO
        wu = wu + pe
    else:
        eu = wu + ek + pe
        wu = ZERO
        if wl > p.c * p.wlm:
            el = (ek - eu) * wl / p.wlm
            ed = ZERO
            wl = wl - el
        elif wl > p.c * (ek - eu):
            el = p.c * (ek - eu)
            ed = ZERO
            wl = wl - el
        else:
            el = wl
            ed = p.c * (ek - eu) - el
            ed = min(ed, max(ZERO, wd))
            wl = ZERO
            wd = max(ZERO, wd - ed)
    z.wu, z.wl, z.wd = wu, wl, wd
    z.w = wu + wl + wd
    return SimpleNamespace(et=eu + el + ed, eu=eu, el=el, ed=ed,
                           r_yield=r, ped=ped, rd=rd)


def divi3(p, z, ped, rd):
    """Legacy three-source separation, including old-S drainage ordering."""
    pe = ZERO
    for value in ped:
        pe = pe + value
    s, fr = z.s, z.fr
    rs, ri, rg = ZERO, ZERO, ZERO
    if pe <= ZERO:
        rg = s * p.kg * fr
        ri = s * p.ki * fr
        s = s * (ONE - p.kg - p.ki)
    else:
        kid = (ONE - (ONE - (p.kg + p.ki)) ** (ONE / F(len(ped)))) / (p.kg + p.ki)
        kgd = kid * p.kg
        kid = kid * p.ki
        smm = (ONE + p.ex) * p.sm
        rb = p.imp * pe
        for rain, runoff in zip(ped, rd):
            td = runoff - p.imp * rain
            old_fr = fr
            fr = max(F(1.e-5), td / rain)
            s = old_fr * s / fr
            rs_adjust = ZERO
            if s > p.sm:
                rs_adjust = (s - p.sm) * fr
                s = p.sm
            au = (smm if abs(s - p.sm) < F(1.e-3) else
                  smm * (ONE - (ONE - s / p.sm) ** (ONE / (ONE + p.ex))))
            if au + rain < smm:
                rsd = (rain - p.sm + s + p.sm *
                       (ONE - (rain + au) / smm) ** (ONE + p.ex)) * fr
            else:
                rsd = (rain + s - p.sm) * fr
            rsd = max(ZERO, rsd)
            rs = rs + rsd + rs_adjust
            rid = s * kid * fr
            ri = ri + rid
            rgd = s * kgd * fr
            rg = rg + rgd
            s = s + rain - (rsd + rid + rgd) / fr
        rs = rs + rb
    z.s, z.fr = s, fr
    return rs, ri, rg


def musk(p, dt, flow, qx):
    t = dt / HOUR
    denominator = p.ke - p.ke * p.xe + HALF * t
    c0 = (HALF * t - p.ke * p.xe) / denominator
    c1 = (p.ke * p.xe + HALF * t) / denominator
    c2 = (p.ke - p.ke * p.xe - HALF * t) / denominator
    for j in range(1, p.dp + 1):
        i1, o1 = qx[j - 1], qx[j]
        qx[j - 1] = flow
        flow = c0 * flow + c1 * i1 + c2 * o1
    qx[p.dp] = flow
    return flow


class Model:
    """Stateful timestep API. Inputs are per-step depths in mm, zone order."""

    def __init__(self, params, dt, states=None, start_time=None):
        self.params, self.dt = params, F(dt)
        self.time = start_time  # State boundary: start of the NEXT forcing step.
        self.states = states if states is not None else [cold_state(p) for p in params]
        self.lags = [deque([(ZERO, ZERO, ZERO)] * p.lag) for p in params]
        self.cp = [F(1000) * p.area / self.dt for p in params]

    def step(self, rain, evaporation):
        if len(rain) != len(self.params) or len(evaporation) != len(self.params):
            raise ValueError("Forcing zone count mismatch")
        volumes, fluxes, precipitation = [], [], []
        qsz, qiz, qgz = ZERO, ZERO, ZERO
        for i, (p, z) in enumerate(zip(self.params, self.states)):
            prec, ep = F(rain[i]) / self.dt, F(evaporation[i]) / self.dt
            if not (np.isfinite(prec) and np.isfinite(ep) and prec >= ZERO and ep >= ZERO):
                raise ValueError(f"Zone {i + 1}: forcing must be finite and nonnegative")
            flux = runoff_yield(p, z, self.dt, prec, ep)
            rs, ri, rg = divi3(p, z, flux.ped, flux.rd)
            flux.rs, flux.ri, flux.rg = rs, ri, rg
            z.qs = rs * self.cp[i]
            z.qi = z.qi * p.ci + ri * (ONE - p.ci) * self.cp[i]
            z.qg = z.qg * p.cg + rg * (ONE - p.cg) * self.cp[i]
            z.qs_cs = z.qs_cs * p.cs + z.qs * (ONE - p.cs)
            z.qi_cs = z.qi_cs * p.cs + z.qi * (ONE - p.cs)
            z.qg_cs = z.qg_cs * p.cs + z.qg * (ONE - p.cs)
            self.lags[i].append((z.qs_cs, z.qi_cs, z.qg_cs))
            qss, qii, qgg = self.lags[i].popleft()
            volumes.append((qss + qii + qgg) * self.dt)  # BEFORE Muskingum, as in driver.
            qss = musk(p, self.dt, qss, z.qxs)
            qii = musk(p, self.dt, qii, z.qxi)
            qgg = musk(p, self.dt, qgg, z.qxg)
            qsz, qiz, qgz = qsz + qss, qiz + qii, qgz + qgg
            precipitation.append(prec * self.dt)
            fluxes.append(flux)
        if self.time is not None:
            self.time = advance_date(self.time, timedelta(seconds=int(float(self.dt) + 0.5)))
        return SimpleNamespace(m3_riv=volumes, prec=precipitation, fluxes=fluxes,
                               sum_qg=qgz, sum_qig=qgz + qiz, sum_qsig=qgz + qiz + qsz)


def parameter_signature(params):
    """Identify the effective (already dt-converted) parameter set and zone order."""
    rows = [[int(getattr(p, key)) if key in ("rivid", "dp", "lag") else
             float(getattr(p, key)) for key in PARAMETERS] for p in params]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def time_string(date):
    return f"{date.year:04d}{date:%m%d%H%M%S}"


def write_restart(path, model):
    """Atomically replace a complete, single-boundary checkpoint after a good run.

    Queues are ordered by arrival: slot 0 is released by the next Model.step.
    Diagnostic output files are deliberately not treated as checkpoints.
    """
    from netCDF4 import Dataset

    if model.time is None:
        raise ValueError("Checkpoint requires Model(start_time=...) to define its state time")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    try:
        with Dataset(netcdf_path(temporary), "w", format="NETCDF4") as nc:
            nc.xaj_restart_version = RESTART_VERSION
            nc.xaj_routing_layout = ROUTING_LAYOUT
            nc.time_semantics = "start_of_next_step"
            nc.dt_seconds = model.dt
            nc.parameter_signature = parameter_signature(model.params)
            for name, size in (("time", None), ("nzone", len(model.params)),
                               ("maxdp", MAXDP), ("char_len", 14),
                               ("lag_slot", max(1, max(p.lag for p in model.params)))):
                nc.createDimension(name, size)
            nc.createVariable("time", "S1", ("time", "char_len"))[0] = np.frombuffer(
                time_string(model.time).encode("ascii"), dtype="S1")
            nc.createVariable("rivid", "i8", ("nzone",))[:] = [p.rivid for p in model.params]
            nc.createVariable("lag_steps", "i4", ("nzone",))[:] = [p.lag for p in model.params]
            for name in ["w"] + STATES + ROUTING:
                dims = ("time", "nzone", "maxdp") if name in ROUTING else ("time", "nzone")
                data = np.asarray([getattr(z, name) for z in model.states], dtype=F)
                if not np.isfinite(data).all():
                    raise ValueError(f"Cannot checkpoint nonfinite state: {name}")
                nc.createVariable(name, "f4", dims)[0] = data
            if any(z.w != z.wu + z.wl + z.wd for z in model.states):
                raise ValueError("Cannot checkpoint inconsistent total soil water")
            for component, name in enumerate(("qs_lag", "qi_lag", "qg_lag")):
                values = np.zeros((len(model.params), len(nc.dimensions["lag_slot"])), dtype=F)
                for i, (p, queue) in enumerate(zip(model.params, model.lags)):
                    if len(queue) != p.lag:
                        raise ValueError("Checkpoint lag queue length mismatch")
                    values[i, :p.lag] = [q[component] for q in queue]
                if not np.isfinite(values).all():
                    raise ValueError(f"Cannot checkpoint nonfinite lag queue: {name}")
                nc.createVariable(name, "f4", ("time", "nzone", "lag_slot"))[0] = values
        os.replace(temporary, str(path))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_restart(path, params, dt, start_time):
    """Restore a complete checkpoint, requiring the exact requested state time.

    Explicit restart requests fail on missing/incomplete/incompatible files;
    only an empty fnm_restart_in selects a cold start. Historical output files
    lack the pending lag queues and cannot guarantee a continuous restart.
    """
    from netCDF4 import Dataset

    with Dataset(netcdf_path(path)) as nc:
        if getattr(nc, "xaj_restart_version", None) != RESTART_VERSION:
            raise ValueError("Not a complete Python XAJ checkpoint; legacy output lacks restart metadata/lag queues")
        if getattr(nc, "xaj_routing_layout", None) != ROUTING_LAYOUT:
            raise ValueError("Unsupported checkpoint routing layout")
        if getattr(nc, "time_semantics", None) != "start_of_next_step":
            raise ValueError("Unsupported checkpoint time semantics")
        if getattr(nc, "dt_seconds", None) != F(dt):
            raise ValueError("Checkpoint dt mismatch")
        sizes = dict(time=1, nzone=len(params), maxdp=MAXDP, char_len=14,
                     lag_slot=max(1, max(p.lag for p in params)))
        for name, size in sizes.items():
            if name not in nc.dimensions or len(nc.dimensions[name]) != size:
                raise ValueError(f"Checkpoint dimension mismatch: {name}")

        def values(name, dims, dtype="f4"):
            if name not in nc.variables:
                raise ValueError(f"Checkpoint missing variable: {name}")
            variable = nc[name]
            if variable.dimensions != dims or variable.dtype != np.dtype(dtype):
                raise ValueError(f"Checkpoint variable layout/type mismatch: {name}")
            data = variable[:]
            if np.ma.getmaskarray(data).any() or (dtype != "S1" and not np.isfinite(data).all()):
                raise ValueError(f"Checkpoint contains missing/nonfinite values: {name}")
            return np.asarray(data)

        timestamp = values("time", ("time", "char_len"), "S1")[0].tobytes().decode("ascii")
        if timestamp != time_string(start_time):
            raise ValueError(f"Checkpoint time mismatch: stored {timestamp}, requested {time_string(start_time)}")
        if not np.array_equal(values("rivid", ("nzone",), "i8"), [p.rivid for p in params]):
            raise ValueError("Checkpoint river IDs/order mismatch")
        if not np.array_equal(values("lag_steps", ("nzone",), "i4"), [p.lag for p in params]):
            raise ValueError("Checkpoint LAG mismatch")
        if getattr(nc, "parameter_signature", None) != parameter_signature(params):
            raise ValueError("Checkpoint parameters mismatch")
        model = Model(params, dt, start_time=start_time)
        for name in ["w"] + STATES + ROUTING:
            dims = ("time", "nzone", "maxdp") if name in ROUTING else ("time", "nzone")
            data = values(name, dims)[0]
            for i, z in enumerate(model.states):
                setattr(z, name, data[i].copy() if name in ROUTING else F(data[i]))
        for z in model.states:
            if z.w != z.wu + z.wl + z.wd:
                raise ValueError("Checkpoint total soil water does not match its layers")
        queues = [values(name, ("time", "nzone", "lag_slot"))[0]
                  for name in ("qs_lag", "qi_lag", "qg_lag")]
        model.lags = [deque(zip(*(q[i, :p.lag] for q in queues))) for i, p in enumerate(params)]
        return model


def forcing_row(stream, nzone, step):
    values = re.split(r"[\s,]+", stream.readline().strip())
    if len(values) != nzone + 1:
        raise ValueError(f"{stream.name}: step {step}: expected time and {nzone} values")
    # The first numeric column is discarded by Fortran; dates come from namelist.
    numbers = [F(v.lower().replace("d", "e")) for v in values]
    return numbers[1:]


def advance_date(date, delta):
    """Match geth_newdate/nfeb, including its non-Gregorian 3600-year rule."""
    result = date + delta
    for year in range(max(3600, ((date.year - 1) // 3600 + 1) * 3600), result.year + 1, 3600):
        if date < datetime(year, 2, 29) <= result:
            result += timedelta(days=1)
    return result


def run(case_dir=".", namelist="xaj.namelist", restart_out=None):
    """Stream original case files to the same two NetCDF output schemas."""
    from netCDF4 import Dataset

    root = Path(case_dir).resolve()
    config = read_namelist(root / namelist)
    params = read_parameters(root / config.fnm_parameters, config.nzone, config.dt)
    date = datetime(config.start_year, config.start_month, config.start_day, config.start_hour,
                    config.start_minute, config.start_second)
    if date.year % 3600 == 0 and date.month == 2 and date.day == 29:
        raise ValueError("February 29 is invalid under the Fortran 3600-year calendar rule")
    restart = root / config.fnm_restart_in if config.fnm_restart_in else None
    output = root / config.fnm_output if config.fnm_output else None
    checkpoint_name = config.fnm_restart_out if restart_out is None else restart_out
    checkpoint = root / checkpoint_name if checkpoint_name else None
    m3_path = root / "m3_riv.nc"
    inputs = [root / namelist, root / config.fnm_parameters,
              root / "forcings/prec.txt", root / "forcings/ep.txt"]
    targets = [m3_path] + ([output] if output else [])
    if (len({p.resolve() for p in targets}) != len(targets) or
            any(p.resolve() in {q.resolve() for q in inputs + ([restart] if restart else [])}
                for p in targets)):
        raise ValueError("Output paths must differ from each other and from input/restart paths")
    if checkpoint and checkpoint.resolve() in {p.resolve() for p in inputs + targets}:
        raise ValueError("Checkpoint output must differ from forcing/configuration and diagnostic outputs")
    model = (read_restart(restart, params, config.dt, date) if restart else
             Model(params, config.dt, start_time=date))
    # Keep the final restart contract, and separately archive every daily 08:00
    # boundary. A fresh generation prevents stale dates surviving a shorter rerun.
    daily_index = None
    if config.dt == DAY and (date.hour, date.minute, date.second) == (8, 0, 0):
        daily_root = root / "results/daily_restarts"
        generation = uuid.uuid4().hex
        (daily_root / generation).mkdir(parents=True, exist_ok=False)
        daily_index = dict(status="running", time_semantics="start_of_next_step",
                           dt_seconds=86400, generation=generation, checkpoints=[],
                           source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                           inputs={str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in inputs + ([restart] if restart else [])})
        (daily_root / "index.json").write_text(json.dumps(daily_index, indent=2), encoding="utf-8")
    with ExitStack() as stack:
        rain = stack.enter_context((root / "forcings/prec.txt").open())
        ep = stack.enter_context((root / "forcings/ep.txt").open())
        next(rain)
        next(ep)
        for path in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
        m3 = stack.enter_context(Dataset(netcdf_path(m3_path), "w", format="NETCDF3_CLASSIC"))
        m3.createDimension("time", None)
        m3.createDimension("COMID", config.nzone)
        m3.createVariable("m3_riv", "f4", ("time", "COMID"))
        out = None
        if output:
            out = stack.enter_context(Dataset(netcdf_path(output), "w", format="NETCDF4"))
            out.xaj_routing_layout = ROUTING_LAYOUT
            for name, size in (("time", None), ("nzone", config.nzone), ("maxdp", MAXDP), ("char_len", 14)):
                out.createDimension(name, size)
            out.createVariable("time", "S1", ("time", "char_len"))
            for name in ["prec"] + STATES:
                out.createVariable(name, "f4", ("time", "nzone"))
            for name in ROUTING:
                out.createVariable(name, "f4", ("time", "nzone", "maxdp"))
            for name in TOTALS:
                out.createVariable(name, "f4", ("time",))
        for it in range(config.nstep):
            result = model.step(forcing_row(rain, config.nzone, it + 1),
                                forcing_row(ep, config.nzone, it + 1))
            m3["m3_riv"][it] = result.m3_riv
            if out is not None:
                out["time"][it] = np.frombuffer(time_string(date).encode("ascii"), dtype="S1")
                out["prec"][it] = result.prec
                for name in STATES + ROUTING:
                    values = np.asarray([getattr(z, name) for z in model.states], dtype=F)
                    out[name][it] = values
                for name in TOTALS:
                    out[name][it] = getattr(result, name)
            if it == 0 or (it + 1) % 1000 == 0 or it + 1 == config.nstep:
                print(f"step,time {it + 1} {date:%Y%m%d%H%M%S}")
            date = model.time
            if daily_index is not None:
                saved = daily_root / generation / (time_string(model.time) + ".nc")
                write_restart(saved, model)
                daily_index["checkpoints"].append(dict(
                    time=model.time.isoformat(), path=saved.relative_to(daily_root).as_posix(),
                    sha256=hashlib.sha256(saved.read_bytes()).hexdigest()))
    if checkpoint:
        write_restart(checkpoint, model)
    if daily_index is not None:
        daily_index["status"] = "completed"
        pending = daily_root / (generation + ".json.tmp")
        pending.write_text(json.dumps(daily_index, indent=2), encoding="utf-8")
        os.replace(pending, daily_root / "index.json")
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", default=".", help="Case directory (default: current directory)")
    parser.add_argument("--namelist", default="xaj.namelist", help="Namelist path relative to case directory")
    parser.add_argument("--restart-out", help="Complete checkpoint path relative to case directory")
    args = parser.parse_args()
    try:
        run(args.case_dir, args.namelist, args.restart_out)
    except (OSError, ValueError, KeyError, StopIteration, FloatingPointError) as exc:
        parser.exit(1, f"XAJ error: {exc}\n")


if __name__ == "__main__":
    main()
