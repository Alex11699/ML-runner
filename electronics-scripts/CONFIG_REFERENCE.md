# Config reference

Two separate config files, one per calculation type — you never run
bandgaps and dielectrics from the same batch, so there's no shared file to
keep in sync between them.

This file is the plain-language companion to `config.py`, which is the
actual source of truth (`BANDGAP_CONFIG_FIELDS` / `DIELECTRIC_CONFIG_FIELDS`
dicts). If the two ever disagree, `config.py` is right — update this file
to match, not the other way round.

## How it works

1. Copy `config_bandgap.json` (or `config_dielectric.json`) to a new file,
   edit whatever you want to change, leave the rest.
2. Pass it with `--config your_file.json` to `driver.py` / `driver_local.py`
   / `driver_local_dielectric.py` / `launch_workers.py`.
3. On the **first** submission against a given `--run-root`, that config is
   resolved and written to `run_root/config_used.json` — a permanent,
   frozen record of exactly what that batch ran with, sitting right next to
   the results it produced.
4. On every submission after that (retries, resumed batches, extra
   `launch_workers.py` rounds), the driver checks your `--config` against
   `run_root/config_used.json` and **errors out if they don't match** —
   editing your config file after a batch has started doesn't silently
   change jobs already submitted for that run-root. Use a fresh `--run-root`
   for a new settings batch instead.
5. `run_scf.py` / `run_bands.py` / `run_dielectric.py` never read your
   `--config` file directly — only the frozen `config_used.json`, via the
   `BANDGAP_CONFIG_PATH` / `DIELECTRIC_CONFIG_PATH` environment variable the
   submit scripts export.

An unknown key in your JSON file (a typo) is a hard error, not a silently
ignored one.

## config_bandgap.json (SCF → bands)

| Key | Default | Meaning |
|---|---|---|
| `functional` | `"pbe"` | XC functional for **both** stages together. `"optb88-vdw"` runs GGA=BO on top of the existing PBE-relaxed geometry (not re-relaxed under it) — for the ALIGNN-JARVIS comparison runs specifically, not the default workflow. POTCAR family is PAW-PBE either way — VASP has no separate "optB88" pseudopotential set, the functional lives entirely in the INCAR tags. |
| `encut` | `800.0` | Plane-wave cutoff (eV). **Must match** the ENCUT the input geometries were relaxed at — currently 800, the "strict PBE opts" relaxation. A mismatch reintroduces basis-set inconsistency between the relaxed geometry and this run. |
| `prec` | `"Accurate"` | VASP `PREC` tag, both stages. |
| `algo` | `"Normal"` | VASP `ALGO` tag, both stages. |
| `nelm` | `120` | Max electronic SCF steps per ionic step. |
| `sigma_elec` | `0.1` | Smearing width (eV), `ISMEAR=0`. Matches the strict-opts relaxation's `SIGMA`, for a clean comparison. |
| `kspacing_scf` | `0.2` | `KSPACING` for the SCF stage only — bands uses the explicit seekpath k-path instead, not this. Denser than the 0.314 used for relaxation. |
| `ediff` | `1e-8` | Electronic convergence criterion (eV), both stages — confirmed 2026-09. |

Not configurable here (deliberately, see `common.py`'s docstring for why):
`NPAR` (parallelization, not a physics setting — HPC-specific like
`VASP_PP_PATH`), the seekpath k-path density, `ISMEAR`/`IBRION`/`ICHARG`
(fixed by what SCF vs. bands each need).

## config_dielectric.json (DFPT)

| Key | Default | Meaning |
|---|---|---|
| `encut` | `800.0` | Plane-wave cutoff (eV). **Must match** the ENCUT the input geometry was relaxed at — `IBRION=8` computes the ionic response at the current geometry without re-relaxing it, so a mismatch here is a real physical inconsistency, not just a convergence nicety. |
| `algo` | `"Normal"` | VASP `ALGO` tag. |
| `nelm` | `120` | Max electronic SCF steps. |
| `sigma_elec` | `0.05` | Smearing width (eV), `ISMEAR=0`. |
| `kspacing` | `0.2` | `KSPACING` for the DFPT run. Reuses the bandgap workflow's SCF mesh density as a starting point — worth convergence-testing separately, not assumed converged. |
| `ediff` | `1e-8` | Electronic convergence criterion (eV) — confirmed 2026-09. Kept as its own field rather than shared with the bandgap config, in case you ever want to tighten it independently (this is a second-derivative property, more sensitive to electronic convergence). |

No `functional` field — this workflow is always plain PBE (`pp="PBE"`,
`gga="PE"`, explicit, never left to VASP's default — see
`common_dielectric.py`'s docstring for the LDA incident this guards
against). Not configurable here: `NPAR`/`NCORE` (IBRION=8 doesn't support
band parallelization at all — nothing to set).

## Adding a new field

Add it to the relevant `*_FIELDS` dict in `config.py` (default + `doc`,
`choices` if it's an enum), regenerate the matching `config_*.json`
template with the new key at its default, update the table above, and wire
the new value into `common.py`/`common_dielectric.py`'s calculator
construction. Existing `config_used.json` files from past batches simply
won't have the new key — `load_config()` will fill it from the schema
default when reading them, so old frozen configs stay readable.
