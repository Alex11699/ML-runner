"""
Shared definitions for the IGZO bandgap validation workflow.

Both run_scf.py and run_bands.py import from here so that ENCUT, PREC, ALGO,
NPAR etc. stay identical across the two stages (only what has to differ —
IBRION/NSW being fixed at -1/0 for both, ISMEAR/SIGMA/KSPACING/ICHARG/LCHARG —
is set per-function below).

Assumptions / things to check before running at scale:
  - VASP_PP_PATH must be set in your environment (pointing at the directory
    containing potpaw_PBE/) before ASE can write POTCAR files. Put this in
    your job script or ~/.bashrc on Sulis/Isambard-AI.
  - ASE_VASP_COMMAND (or the older VASP_COMMAND) must point at how to launch
    vasp_std under srun/mpirun on the cluster you're on, e.g.:
        export ASE_VASP_COMMAND="srun vasp_std"
  - SIGMA_ELEC is set to 0.1 here, matching the strict-opts relaxation's
    SIGMA=0.1 uniformly (confirmed against your actual bandgaps/strict-opts/
    common.py).
  - USE_OPTB88_VDW below switches BOTH stages to the OptB88-vdW functional
    (GGA=BO), for comparing against ALIGNN's JARVIS-DFT training convention.
    This runs on top of the EXISTING PBE-relaxed ("strict PBE opts")
    geometries -- deliberately not re-relaxed under OptB88-vdW first.
  - VDW_KERNEL_PATH must point at your confirmed-good vdw_kernel.bindat when
    USE_OPTB88_VDW is True -- required by GGA=BO/LUSE_VDW. Your VASP build
    (6.3.2) does not auto-generate it (that's a 6.4.3+ feature), so a
    missing file means VASP silently spends hours computing it instead of
    erroring.
"""

import os
import shutil
from pathlib import Path
from ase.calculators.vasp import Vasp
from ase.io import write
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.symmetry.kpath import KPathSeek
from pymatgen.io.vasp.inputs import Kpoints

# ---- settings matched to the "strict PBE opts" relaxation these structures
# ---- came from (ENCUT=800, PREC=Accurate, EDIFF=1e-8, SIGMA=0.1) ----
ENCUT = 800.0
PREC = "Accurate"
ALGO = "Normal"
NELM = 120
NPAR = 8
SIGMA_ELEC = 0.1     # matches strict-opts relaxation SIGMA, for a clean comparison
KSPACING_SCF = 0.2   # denser than the 0.314 used for relaxation

# ---- OptB88-vdW ----
USE_OPTB88_VDW = True
GGA_BO_PARAM1 = 0.1833333333
GGA_BO_PARAM2 = 0.2200000000
VDW_KERNEL_PATH = os.environ.get("VDW_KERNEL_PATH")


def _functional_kwargs():
    """
    INCAR kwargs for the exchange-correlation functional -- ALWAYS explicit,
    for both branches, never relying on VASP's own default (GGA unset ->
    whatever LEXCH says in the POTCAR). That exact silent-default chain is
    what caused genuine LDA results to be produced and labeled PBE
    throughout the "strict PBE opts" dataset -- confirmed via `head -1
    POTCAR` showing "PAW Zn" (LDA, LEXCH=CA), not "PAW_PBE".

    Single function (not two separately-unpacked dicts) so there's no risk
    of passing `gga` twice to Vasp() in the same call -- these two branches
    are mutually exclusive by construction.
    """
    if not USE_OPTB88_VDW:
        return {"pp": "PBE", "gga": "PE"}
    return {
        "pp": "PBE",
        "gga": "BO",
        "param1": GGA_BO_PARAM1,
        "param2": GGA_BO_PARAM2,
        "aggac": 0.0,
        "luse_vdw": True,
    }


def stage_vdw_kernel(directory: str):
    """Copy vdw_kernel.bindat into a job's working directory. Required
    because VASP looks for it in the process's own cwd (= ASE calculator's
    `directory`), not some shared/central location -- so this has to run
    once per stage (scf/, bands/), not once per structure. No-ops if
    USE_OPTB88_VDW is False."""
    if not USE_OPTB88_VDW:
        return
    if not VDW_KERNEL_PATH:
        raise RuntimeError(
            "USE_OPTB88_VDW is True but VDW_KERNEL_PATH is not set. "
            "export VDW_KERNEL_PATH=$HOME/APPS/vasp.6.3.2/vdw_kernel.bindat"
        )
    src = Path(VDW_KERNEL_PATH)
    if not src.exists():
        raise RuntimeError(f"VDW_KERNEL_PATH={src} does not exist")
    dst = Path(directory) / "vdw_kernel.bindat"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)


def make_scf_calculator(directory: str) -> Vasp:
    """Static SCF calc that writes CHGCAR for the subsequent non-SCF step."""
    return Vasp(
        directory=directory,
        ibrion=-1,
        nsw=0,
        encut=ENCUT,
        prec=PREC,
        algo=ALGO,
        nelm=NELM,
        npar=NPAR,
        ismear=0,
        sigma=SIGMA_ELEC,
        kspacing=KSPACING_SCF,
        ediff=1e-8,
        lcharg=True,     # required: bands step reads this CHGCAR
        lwave=False,
        nwrite=1,
        **_functional_kwargs(),
    )


def make_bands_calculator(directory: str):
    """
    Non-SCF calc along the high-symmetry k-path, frozen density (ICHARG=11).

    Deliberately does NOT set `kpts` here — the KPOINTS file is written
    separately (with seekpath's explicit labeled path) by
    run_vasp_with_explicit_kpoints(), since ASE's own KPOINTS writer can't
    carry per-k-point labels that pymatgen's parser needs afterwards.
    """
    return Vasp(
        directory=directory,
        ibrion=-1,
        nsw=0,
        encut=ENCUT,
        prec=PREC,
        algo=ALGO,
        nelm=NELM,
        npar=NPAR,
        ismear=0,
        sigma=SIGMA_ELEC,
        icharg=11,
        lcharg=False,
        lwave=False,
        **_functional_kwargs(),
    )


def get_seekpath_primitive_and_kpoints(atoms, line_density=20, symprec=1e-3):
    """
    Per-structure high-symmetry k-path using the seekpath package (via
    pymatgen's KPathSeek wrapper), per supervisor guidance — this replaces
    ASE's cell.bandpath(), which infers the path from lattice shape alone
    rather than running full space-group determination (spglib) on the
    actual atoms + basis, and can pick the wrong path for lower-symmetry
    or non-symmorphic structures.

    IMPORTANT: seekpath returns a *standardized primitive cell*, which is
    not guaranteed to be identical to the input structure. Both the SCF and
    bands steps MUST run on this same primitive structure — if SCF runs on
    the original cell and bands runs on the seekpath primitive cell, the
    CHGCAR from SCF won't be valid for the bands step's ICHARG=11 read.

    Returns:
        primitive_atoms: ASE Atoms object (standardized primitive cell) —
            use this for BOTH the SCF and bands calculations, not the
            original input structure.
        kpoints_obj: pymatgen Kpoints object with the explicit, labeled
            k-point path, ready to write directly to a VASP KPOINTS file.
        spacegroup_info: (symbol, number) tuple, useful for logging/QA.
    """
    structure = AseAtomsAdaptor.get_structure(atoms)
    spacegroup_info = structure.get_space_group_info(symprec=symprec)

    kpath = KPathSeek(structure, symprec=symprec)
    primitive_structure = kpath.structure
    primitive_atoms = AseAtomsAdaptor.get_atoms(primitive_structure)

    frac_kpts, labels = kpath.get_kpoints(line_density=line_density, coords_are_cartesian=False)

    kpoints_obj = Kpoints(
        comment=f"seekpath explicit path, spacegroup {spacegroup_info}",
        style=Kpoints.supported_modes.Reciprocal,
        num_kpts=len(frac_kpts),
        kpts=frac_kpts,
        kpts_weights=[1] * len(frac_kpts),
        labels=labels,
    )

    return primitive_atoms, kpoints_obj, spacegroup_info


def run_vasp_with_explicit_kpoints(atoms, calc, kpoints_obj):
    """
    Write VASP inputs via ASE, then overwrite KPOINTS with the seekpath-
    generated explicit labeled path before running VASP, then run and
    parse results.
    """
    atoms.calc = calc
    calc.write_input(atoms)
    kpoints_obj.write_file(str(Path(calc.directory) / "KPOINTS"))

    command = calc.make_command(calc.command)
    with calc._txt_outstream() as out:
        errorcode, stderr = calc._run(command=command, out=out, directory=calc.directory)
    if errorcode:
        raise RuntimeError(f"VASP run failed with exit code {errorcode}: {stderr}")

    calc.update_atoms(atoms)
    calc.read_results()
    return atoms.get_potential_energy()


def extract_gap(vasprun_path: str, kpoints_path: str):
    """
    Parse a finished non-SCF bands run and return gap info.
    """
    try:
        from pymatgen.io.vasp import Vasprun
    except ImportError as e:
        return {"error": f"pymatgen not available: {e}"}

    try:
        vr = Vasprun(vasprun_path, parse_potcar_file=False)
        bs = vr.get_band_structure(kpoints_filename=kpoints_path, line_mode=True)
        gap_info = bs.get_band_gap()
        vbm = bs.get_vbm()
        cbm = bs.get_cbm()
        return {
            "energy": gap_info["energy"],
            "direct": gap_info["direct"],
            "transition": gap_info.get("transition"),
            "vbm_kpoint": getattr(vbm.get("kpoint"), "label", None) if vbm else None,
            "cbm_kpoint": getattr(cbm.get("kpoint"), "label", None) if cbm else None,
            "is_metal": bs.is_metal(),
        }
    except Exception as e:
        return {"error": str(e)}
