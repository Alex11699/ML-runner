"""
Calculator and result-extraction for the full static dielectric tensor
(electronic + ionic) via DFPT: IBRION=8, LEPSILON=.TRUE., LPEAD=.TRUE.

This is deliberately SEPARATE from common.py (the bandgap SCF/bands module):
this workflow is single-stage (no SCF->bands split, no seekpath k-path, no
frozen-density ICHARG=11 trick) -- just one VASP run per structure on a
standard k-mesh.

IMPORTANT PREREQUISITE: the input structure must already be well-relaxed.
IBRION=8 computes the ionic (phonon-related) contribution to the dielectric
tensor at the CURRENT geometry -- it does not perform ionic relaxation
itself. Feeding it an unrelaxed structure gives a physically wrong ionic
contribution (small residual forces are assumed, not enforced).

PARALLELIZATION NOTE: IBRION=8 does NOT support NCORE/NPAR band
parallelization at all (confirmed against VASP community/wiki guidance) --
this is deliberately different from common.py's SCF/bands calculators,
which set NPAR=8. KPAR (k-point parallelization) IS supported for IBRION=8,
but is known to scale memory poorly for larger cells (community guidance
suggests keeping KPAR <= ~12 even when memory allows more) -- left unset
(VASP default, no k-point parallelization) here for correctness; only add
it after checking it's safe for your cell sizes and node memory.

IMPORTANT — FUNCTIONAL: pp="PBE" and gga="PE" are set explicitly below, not
left to VASP's default. VASP's default (GGA unset in INCAR) is "whatever
LEXCH says in the POTCAR" (confirmed against VASP's own wiki), and ASE's
own default POTCAR-family guess (pp unset) is 'lda', which looks for a
folder literally named 'potpaw' rather than 'potpaw_PBE'. This exact silent
chain is what caused the bandgap workflow's "strict PBE opts" dataset to
actually be computed with genuine LDA throughout (confirmed via `head -1
POTCAR` showing "PAW Zn", LEXCH=CA, not "PAW_PBE") -- fixed there, and
fixed here from the start rather than carrying the same latent risk.
"""

import numpy as np
from ase.calculators.vasp import Vasp

ENCUT = 600.0
ALGO = "Normal"
NELM = 120
SIGMA_ELEC = 0.05
KSPACING = 0.2  # reuses the same mesh density as common.py's SCF stage; dielectric
# properties can be sensitive to k-point sampling, so treat this as a starting
# point worth convergence-testing separately rather than assuming it's converged.


def make_dielectric_calculator(directory: str) -> Vasp:
    return Vasp(
        directory=directory,
        ibrion=8,
        lepsilon=True,
        lpead=True,
        nsw=1,
        lreal=False,        # DFPT needs reciprocal-space projection, not real-space
        prec="Accurate",     # DFPT is more sensitive to real-space grid accuracy
        # than a plain SCF -- deliberately NOT "Normal" here, unlike common.py.
        encut=ENCUT,
        algo=ALGO,
        nelm=NELM,
        ismear=0,
        sigma=SIGMA_ELEC,
        ediff=1e-8,          # tighter than the bandgap workflow's 1e-6 -- this is
        # a second-derivative property, more sensitive to electronic convergence.
        kspacing=KSPACING,
        pp="PBE",            # see module docstring — explicit, not left to default
        gga="PE",
        lcharg=False,
        lwave=False,
        nwrite=1,
        # Deliberately NOT setting npar/ncore here -- IBRION=8 does not support them.
    )


def extract_dielectric(outcar_path: str):
    """
    Parse a finished LEPSILON run and return the electronic, ionic, and
    total static dielectric tensors, plus their isotropic (trace/3) means.

    Uses pymatgen's Outcar parser, which exposes:
        outcar.dielectric_tensor        -> electronic (clamped-ion) tensor
        outcar.dielectric_ionic_tensor  -> ionic contribution

    Note: IGZO structures are generally not cubic, so the isotropic mean is
    a simplification for convenient comparison/reporting -- the full 3x3
    tensor (included here too) is the physically complete answer and is
    what you'd want for anything anisotropy-sensitive.
    """
    try:
        from pymatgen.io.vasp import Outcar
    except ImportError as e:
        return {"error": f"pymatgen not available: {e}"}

    try:
        outcar = Outcar(outcar_path)
        electronic = np.array(outcar.dielectric_tensor)
        ionic = np.array(outcar.dielectric_ionic_tensor)
        total = electronic + ionic
        return {
            "electronic_tensor": electronic.tolist(),
            "ionic_tensor": ionic.tolist(),
            "total_tensor": total.tolist(),
            "electronic_mean": float(np.trace(electronic) / 3),
            "ionic_mean": float(np.trace(ionic) / 3),
            "total_mean": float(np.trace(total) / 3),
        }
    except Exception as e:
        return {"error": str(e)}
