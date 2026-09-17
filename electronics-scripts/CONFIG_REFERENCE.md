# Config reference

Three separate config files, one per calculation type — you never run
bandgaps, dielectrics, and phonons from the same batch, so there's no
shared file to keep in sync between them.

This file is the plain-language companion to `config.py`, which is the
actual source of truth (`BANDGAP_CONFIG_FIELDS` / `DIELECTRIC_CONFIG_FIELDS`
/ `PHONON_CONFIG_FIELDS` dicts). If the two ever disagree, `config.py` is
right — update this file to match, not the other way round.

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

## config_phonons.json (finite-displacement phonons, via phonopy)

Separate, additional workflow — NOT a replacement for `config_dielectric.json`
above, which is still required for the Born charges/dielectric tensor (LO-TO
correction). See `common_phonons.py`'s module docstring for why this is
finite differences rather than DFPT-on-supercell.

| Key | Default | Meaning |
|---|---|---|
| `encut` | `800.0` | Plane-wave cutoff (eV), each displaced-supercell force evaluation. Must match the relaxation ENCUT, same reasoning as the other two workflows. |
| `algo` | `"Normal"` | VASP `ALGO` tag. |
| `nelm` | `120` | Max electronic SCF steps per force evaluation. |
| `sigma_elec` | `0.05` | Smearing width (eV), `ISMEAR=0`. Matches the dielectric workflow. |
| `kspacing` | `0.2` | `KSPACING` for each force run — evaluated on the SUPERCELL, so this yields proportionally fewer k-points there than on the unit cell (physically correct, not something to compensate for). |
| `ediff` | `1e-8` | Electronic convergence (eV) per force evaluation — kept tight since phonon force constants are sensitive to force noise. |
| `supercell` | `"auto"` | `"auto"` (default) picks the smallest diagonal repeat so every supercell lattice vector is >= `min_image_distance`, capped at 6x per direction. Or an explicit `[nx, ny, nz]` once you've settled on a size. |
| `min_image_distance` | `15.0` | Angstrom. Only used when `supercell == "auto"`. A starting rule of thumb, **not** a converged value for IGZO specifically — check dispersion at at least two sizes for one structure before trusting it across a batch. |
| `displacement_distance` | `0.01` | Angstrom. Finite-displacement magnitude (phonopy's own default). |
| `band_npoints` | `51` | q-points per segment along the automatic (seekpath-derived) dispersion path written to `band.yaml`. |

Requires `phonopy` in the environment (`pip install phonopy`) in addition to
everything the other two workflows need. Also shells out to phonopy's own
`phonopy-vasp-born` CLI tool (ships with the `phonopy` package) to build a
BORN file from an existing, completed dielectric run for the same
structure, when one exists — see `run_phonons.py`'s docstring. This piece,
and the automatic seekpath band-path generation, were written against
phonopy's documented API but not exercised against a live install before
being handed over — verify both against your installed phonopy version
before trusting a full batch (see `common_phonons.py`'s CONFIDENCE NOTE).

## Adding a new field

Add it to the relevant `*_FIELDS` dict in `config.py` (default + `doc`,
`choices` if it's an enum), regenerate the matching `config_*.json`
template with the new key at its default, update the table above, and wire
the new value into `common.py`/`common_dielectric.py`/`common_phonons.py`'s
calculator construction. Existing `config_used.json` files from past
batches simply won't have the new key — `load_config()` will fill it from
the schema default when reading them, so old frozen configs stay readable.
