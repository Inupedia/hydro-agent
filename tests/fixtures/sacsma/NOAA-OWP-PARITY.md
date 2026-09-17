# NOAA-OWP SAC-SMA parity fixture

`noaa_owp_synthetic_400d.csv` contains a 400-day run of the NOAA-OWP `sac-sma`
Fortran executable. It uses deterministic dry periods and rainfall events with
all process fractions set to nonzero reference values, so the fixture exercises
`PCTIM`, `ADIMP`, `RIVA`, `PFREE`, `SIDE`, `RSERV`, and surface runoff. Forcing
rates were supplied to the executable in mm/s and recorded here as mm/day;
states and fluxes came directly from the upstream executable.

Depths retain full floating-point precision because SAC1 derives an integer
substep count from available water; rounding a value across a 5 mm boundary
changes `NINC` and therefore the state trajectory.

- Repository: <https://github.com/NOAA-OWP/sac-sma>
- Revision: `975902e3d44785f3b3503f29adfb5755120f5bf5`
- Forcing: deterministic sequence documented by the committed CSV
- Parameters: `models/sacsma/parity.py::REFERENCE_PARAMS`
- Upstream outputs: `test_cases/ex1/output/output.sacbmi.HHWM8IL.txt`
- Upstream states: `test_cases/ex1/state/sac_states.HHWM8IL.txt`
- License: Apache-2.0; see the upstream repository license.
