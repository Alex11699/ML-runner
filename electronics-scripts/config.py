"""
Shared config schema + loader/freezer for the bandgap and dielectric
workflows. This is deliberately its own module (not inside common.py /
common_dielectric.py) so it's the one place both workflows' field lists
live, side by side, for reference -- "what's tunable and what does it mean"
shouldn't require reading through calculator-construction code to answer.

Two separate schemas, not one shared one: the bandgap and dielectric
workflows are run as separate batches against separate run-roots (you never
launch both from the same config), so there's no shared ENCUT/EDIFF/etc.
to accidentally desync -- each field lives in exactly one schema, named
plainly (no _dielectric suffix needed).

Usage pattern:
  - common.py / common_dielectric.py call load_config() at import time,
    reading the path from an env var (BANDGAP_CONFIG_PATH /
    DIELECTRIC_CONFIG_PATH) that the driver scripts set before invoking
    run_scf.py / run_bands.py / run_dielectric.py as a subprocess.
  - driver.py / driver_local.py / driver_local_dielectric.py /
    launch_workers.py call resolve_and_freeze() ONCE per run-root, at
    submission time: it resolves --config against the schema defaults,
    writes (or verifies against) run_root/config_used.json, and that
    frozen copy -- not your possibly-still-being-edited --config file --
    is what every job for that run-root actually reads. This is what
    keeps a run-root internally consistent even if you tweak your working
    config file mid-batch, and it's what makes "what did runs/ actually
    get computed with" answerable after the fact without digging through
    job logs.

Config files are plain JSON: {"encut": 700.0, "functional": "optb88-vdw"}.
Unknown keys are rejected (typo protection) rather than silently ignored.
"""
import json
from pathlib import Path

# Each field: default value, one-line doc (also surfaced in CONFIG_REFERENCE.md
# -- keep the two in sync if you add/change a field), and optional `choices`
# for validation. This dict IS the source of truth for both the JSON template
# files' starting values and for what's actually read by the calculators --
# there's no third copy of these numbers anywhere.
BANDGAP_CONFIG_FIELDS = {
    "functional": {
        "default": "pbe",
        "choices": ["pbe", "optb88-vdw"],
        "doc": "XC functional for BOTH the scf and bands stages. 'optb88-vdw' "
               "runs GGA=BO on top of the existing PBE-relaxed geometry "
               "(not re-relaxed under it first) -- for the ALIGNN-JARVIS "
               "comparison runs specifically, not the default workflow. "
               "POTCAR family is PAW-PBE either way -- VASP has no separate "
               "'optB88' pseudopotential set.",
    },
    "encut": {
        "default": 800.0,
        "doc": "Plane-wave cutoff (eV). Must match the ENCUT the input "
               "geometries were relaxed at (currently 800, the 'strict PBE "
               "opts' relaxation) -- a mismatch here reintroduces basis-set "
               "inconsistency between the relaxed geometry and this run.",
    },
    "prec": {
        "default": "Accurate",
        "doc": "VASP PREC tag for both stages.",
    },
    "algo": {
        "default": "Normal",
        "doc": "VASP ALGO tag for both stages.",
    },
    "nelm": {
        "default": 120,
        "doc": "Max electronic SCF steps per ionic step.",
    },
    "sigma_elec": {
        "default": 0.1,
        "doc": "Smearing width (eV), ISMEAR=0. Matches the strict-opts "
               "relaxation's SIGMA, for a clean comparison.",
    },
    "kspacing_scf": {
        "default": 0.2,
        "doc": "KSPACING (SCF stage only -- bands uses the explicit "
               "seekpath k-path instead). Denser than the 0.314 used for "
               "relaxation.",
    },
    "ediff": {
        "default": 1e-8,
        "doc": "Electronic convergence criterion (eV), both stages.",
    },
}

DIELECTRIC_CONFIG_FIELDS = {
    "encut": {
        "default": 800.0,
        "doc": "Plane-wave cutoff (eV). Must match the ENCUT the input "
               "geometry was relaxed at -- IBRION=8 computes the ionic "
               "response at the current geometry without re-relaxing it, so "
               "an ENCUT mismatch against the relaxation is a real physical "
               "inconsistency, not just a convergence nicety.",
    },
    "algo": {
        "default": "Normal",
        "doc": "VASP ALGO tag.",
    },
    "nelm": {
        "default": 120,
        "doc": "Max electronic SCF steps.",
    },
    "sigma_elec": {
        "default": 0.05,
        "doc": "Smearing width (eV), ISMEAR=0.",
    },
    "kspacing": {
        "default": 0.2,
        "doc": "KSPACING for the DFPT run. Reuses the bandgap workflow's "
               "SCF mesh density as a starting point -- dielectric "
               "properties can be sensitive to k-point sampling, treat as "
               "worth convergence-testing separately rather than assumed "
               "converged.",
    },
    "ediff": {
        "default": 1e-8,
        "doc": "Electronic convergence criterion (eV). Matches the bandgap "
               "workflow's value; kept as its own field (not shared) since "
               "this is a second-derivative property and more sensitive to "
               "electronic convergence, in case you ever want to tighten it "
               "independently.",
    },
}

# Finite-displacement phonons (phonopy + plain VASP forces), NOT DFPT-on-
# supercell. See common_phonons.py's module docstring for the reasoning
# (VASP-docs + forum-maintainer guidance that finite differences is the
# better route than DFPT here, plus IBRION=8's NPAR/NCORE restriction
# getting worse on the larger cells dispersion needs) -- this was a
# deliberate decision, not a default. The DIELECTRIC_CONFIG_FIELDS
# workflow above is UNCHANGED and still required alongside this one: it
# supplies the Born charges/dielectric tensor for the LO-TO
# non-analytical correction, on the primitive/original cell, no
# supercell involved there.
PHONON_CONFIG_FIELDS = {
    "encut": {
        "default": 800.0,
        "doc": "Plane-wave cutoff (eV). Must match the ENCUT the input "
               "geometry was relaxed at, same reasoning as the bandgap/"
               "dielectric workflows.",
    },
    "algo": {
        "default": "Normal",
        "doc": "VASP ALGO tag for each displaced-supercell force "
               "evaluation.",
    },
    "nelm": {
        "default": 120,
        "doc": "Max electronic SCF steps per force evaluation.",
    },
    "sigma_elec": {
        "default": 0.05,
        "doc": "Smearing width (eV), ISMEAR=0. Matches the dielectric "
               "workflow's value.",
    },
    "kspacing": {
        "default": 0.2,
        "doc": "KSPACING for each displaced-supercell force run. Note "
               "this is evaluated on the SUPERCELL, not the unit cell -- "
               "the same KSPACING value yields proportionally fewer "
               "k-points there than it would on the primitive cell, which "
               "is the physically correct behaviour, not something to "
               "compensate for.",
    },
    "ediff": {
        "default": 1e-8,
        "doc": "Electronic convergence criterion (eV) for each force "
               "evaluation. Phonon force constants are sensitive to force "
               "noise, so this is deliberately tight, not loosened for "
               "the extra supercell cost.",
    },
    "supercell": {
        "default": "auto",
        "doc": "Either the string 'auto', or an explicit diagonal repeat "
               "[nx, ny, nz]. 'auto' (default) picks the smallest diagonal "
               "repeat such that every supercell lattice vector is >= "
               "min_image_distance (see that field) -- a standard "
               "minimum-image-convention rule of thumb for finite-"
               "displacement phonons, capped at 6x per direction as a "
               "sanity backstop. Set explicitly (e.g. [2, 2, 2]) once "
               "you've decided on a size (e.g. after convergence-testing "
               "the dispersion against supercell size for one structure).",
    },
    "min_image_distance": {
        "default": 15.0,
        "doc": "Angstrom. Only used when supercell == 'auto' (see above) "
               "-- target minimum supercell lattice-vector length. This is "
               "a starting-point rule of thumb, not a converged value for "
               "your IGZO systems specifically; worth checking dispersion "
               "curves for at least one structure at two different sizes "
               "before trusting it across the batch.",
    },
    "displacement_distance": {
        "default": 0.01,
        "doc": "Angstrom. Finite-displacement magnitude phonopy uses when "
               "generating the displaced supercells (its own default, per "
               "phonopy's documentation).",
    },
    "band_npoints": {
        "default": 51,
        "doc": "Number of q-points per segment along the automatic "
               "(seekpath-derived) dispersion path phonopy generates for "
               "band.yaml.",
    },
}


def load_config(fields: dict, path) -> dict:
    """
    Resolve a config dict: schema defaults, overridden by whatever's in the
    JSON file at `path` (if given). Raises on unknown keys (typo
    protection) and on values outside a field's `choices`, rather than
    silently accepting them.

    path=None returns pure defaults -- no file needed for quick/manual use
    (e.g. importing common.py directly without going through a driver).
    """
    resolved = {name: spec["default"] for name, spec in fields.items()}
    if path is not None:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        overrides = json.loads(path.read_text())
        unknown = sorted(set(overrides) - set(fields))
        if unknown:
            raise ValueError(
                f"Unknown config key(s) in {path}: {unknown}. "
                f"Valid keys: {sorted(fields)}"
            )
        resolved.update(overrides)
    for name, value in resolved.items():
        choices = fields[name].get("choices")
        if choices and value not in choices:
            raise ValueError(
                f"Config key '{name}'={value!r} not in allowed choices {choices}"
            )
    if "supercell" in resolved:
        sc = resolved["supercell"]
        is_explicit = (isinstance(sc, list) and len(sc) == 3
                       and all(isinstance(n, int) and n >= 1 for n in sc))
        is_auto = sc == "auto"
        if not (is_explicit or is_auto):
            raise ValueError(
                f"Config key 'supercell'={sc!r} must be 'auto' or a list "
                f"of 3 positive integers, e.g. [2, 2, 2]"
            )
    return resolved


def resolve_and_freeze(fields: dict, config_path, run_root) -> tuple[dict, Path]:
    """
    Called ONCE per run-root, by whichever driver script is submitting jobs
    against it (driver.py / driver_local.py / driver_local_dielectric.py /
    launch_workers.py) -- never by run_scf.py/run_bands.py/run_dielectric.py
    themselves, which just read the frozen file via load_config().

    Resolves config_path against `fields`, then writes it to
    run_root/config_used.json if that doesn't exist yet, or verifies it
    matches if it does. A mismatch raises rather than silently overwriting
    -- this run-root was already started under different settings, and
    sbatch's submission/execution decoupling means jobs from that earlier
    submission could still be queued or running. Returns (resolved_config,
    frozen_path) either way.
    """
    resolved = load_config(fields, config_path)
    run_root = Path(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    frozen_path = run_root / "config_used.json"

    if frozen_path.exists():
        existing = json.loads(frozen_path.read_text())
        if existing != resolved:
            diff_keys = sorted(
                k for k in set(existing) | set(resolved)
                if existing.get(k) != resolved.get(k)
            )
            raise RuntimeError(
                f"{frozen_path} already records different settings than the "
                f"config you just passed (differing key(s): {diff_keys}). "
                f"This run-root was already started under a different "
                f"config -- use a fresh --run-root for a new settings batch, "
                f"or delete {frozen_path} only if you're SURE no jobs from "
                f"the earlier settings are still queued or running."
            )
        return existing, frozen_path

    with open(frozen_path, "w") as f:
        json.dump(resolved, f, indent=2, sort_keys=True)
    return resolved, frozen_path
