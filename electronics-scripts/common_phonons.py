"""
Calculator + supercell-sizing helpers for finite-displacement phonons
(phonopy + plain VASP forces) -- NOT DFPT-on-supercell.

WHY FINITE DIFFERENCES, NOT DFPT-ON-SUPERCELL:
VASP's own wiki is explicit that its DFPT routines "only support
displacements commensurate with the supercell, i.e. so-called q=0
phonons" -- run on the primitive/original cell (as common_dielectric.py's
existing workflow does), IBRION=8 gives Gamma-point only, nothing about
dispersion elsewhere in the BZ. You COULD in principle run IBRION=8 on a
supercell instead to get dispersion via Fourier interpolation, but this
group decided against that route, for two independent reasons found when
checking primary sources:
  1. A VASP forum maintainer: "DFPT is currently just worse in many
     aspects, so finite differences should be the go-to method."
  2. IBRION=8 cannot use NPAR/NCORE band parallelization AT ALL (see
     common_dielectric.py's own docstring) -- a real, previously-hit
     problem that only gets worse scaling up to the larger supercells
     dispersion requires.
So: this module computes forces via plain SCF (IBRION=-1, NSW=0) on each
of phonopy's displaced supercells; run_phonons.py assembles them into
force constants and the dispersion curve.

THIS IS A SEPARATE, ADDITIONAL PIPELINE -- common_dielectric.py/
run_dielectric.py are UNCHANGED and still required: they supply the Born
effective charges + dielectric tensor for the non-analytical (LO-TO
splitting) term correction, on the primitive/original cell, Gamma-point
only, no supercell involved there. Phonopy's own docs confirm this is
exactly the right division of labour: "Non-analytical term correction
requires the Born effective charges and dielectric constant supplied
through a BORN file... obtained from a separate VASP calculation with
LEPSILON=.TRUE." -- i.e. precisely what that existing workflow already
produces. run_phonons.py picks up a finished dielectric_result.json's
sibling vasprun.xml automatically if present (see build_born_file()
there); dispersion is still computed without it, just missing the LO-TO
correction near Gamma.

Each displaced-supercell force evaluation is a PLAIN SCF, not DFPT, so
(unlike common_dielectric.py) NPAR parallelization IS supported and used
here. Same FUNCTIONAL discipline as common_dielectric.py: pp="PBE",
gga="PE" set explicitly, never left to VASP's default -- see that
module's docstring for the LDA incident this guards against.

Physics/convergence settings are loaded from a JSON config via config.py
(PHONON_CONFIG_FIELDS) -- see that module's docstring, config_phonons.json
for the editable starting template, and CONFIG_REFERENCE.md for a
plain-language field reference. Reads the PHONON_CONFIG_PATH environment
variable at import time, same pattern as common.py/common_dielectric.py.

CONFIDENCE NOTE (be aware before trusting this at scale): the VASP-forces
half of this module (make_force_calculator, resolve_supercell_matrix) is
built on the same well-trodden ASE/VASP patterns as the rest of this repo
and is on solid ground. The phonopy orchestration in run_phonons.py --
specifically the automatic seekpath-derived band path
(get_band_qpoints_by_seekpath) and the phonopy-vasp-born BORN-file step --
were written from phonopy's documented API/CLI but NOT tested against a
live installation before handing this over. Check both against your
installed phonopy version (`python -c "from phonopy.phonon.band_structure
import get_band_qpoints_by_seekpath; help(get_band_qpoints_by_seekpath)"`,
`phonopy-vasp-born --help`) before trusting output from them, same as
you'd test any new script here against live data first.
"""

import os

import numpy as np
from ase.calculators.vasp import Vasp

import config as _config

CFG = _config.load_config(_config.PHONON_CONFIG_FIELDS, os.environ.get("PHONON_CONFIG_PATH"))

ENCUT = CFG["encut"]
ALGO = CFG["algo"]
NELM = CFG["nelm"]
SIGMA_ELEC = CFG["sigma_elec"]
KSPACING = CFG["kspacing"]
EDIFF = CFG["ediff"]
NPAR = 8  # parallelization, not physics -- plain SCF force eval, so
          # (unlike common_dielectric.py's IBRION=8) this DOES support it.
SUPERCELL = CFG["supercell"]
MIN_IMAGE_DISTANCE = CFG["min_image_distance"]
DISPLACEMENT_DISTANCE = CFG["displacement_distance"]
BAND_NPOINTS = CFG["band_npoints"]


def make_force_calculator(directory: str) -> Vasp:
    """Plain single-point force evaluation for one displaced supercell."""
    return Vasp(
        directory=directory,
        ibrion=-1,
        nsw=0,
        encut=ENCUT,
        prec="Accurate",
        algo=ALGO,
        nelm=NELM,
        npar=NPAR,
        ismear=0,
        sigma=SIGMA_ELEC,
        kspacing=KSPACING,
        ediff=EDIFF,
        pp="PBE",           # explicit -- see module docstring
        gga="PE",
        lcharg=False,
        lwave=False,
        nwrite=1,
    )


def resolve_supercell_matrix(atoms):
    """
    Return [nx, ny, nz] to hand phonopy, per the `supercell` config field:
      - explicit [nx, ny, nz] (3 ints >= 1): used as-is.
      - "auto" (default): smallest diagonal repeat such that every
        supercell lattice vector is >= min_image_distance (config field,
        default 15.0 Angstrom -- a starting-point rule of thumb, NOT a
        converged value for your IGZO systems specifically; see
        config.py's doc for that field). Capped at 6x in any direction as
        a sanity backstop -- raises rather than silently going further,
        since that's a sign min_image_distance is unreasonable for this
        cell rather than something to push through automatically.
    """
    if SUPERCELL == "auto":
        lengths = atoms.cell.lengths()
        matrix = []
        for length in lengths:
            n = max(1, int(np.ceil(MIN_IMAGE_DISTANCE / length)))
            if n > 6:
                raise ValueError(
                    f"auto supercell sizing needs {n}x along a lattice "
                    f"vector of length {length:.2f} A to reach "
                    f"min_image_distance={MIN_IMAGE_DISTANCE} A -- capped "
                    f"at 6x as a sanity backstop. Set 'supercell' "
                    f"explicitly (e.g. [2, 2, 2]) if you're sure this is "
                    f"right, or lower min_image_distance."
                )
            matrix.append(n)
        return matrix
    return list(SUPERCELL)
