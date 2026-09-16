"""
Shared definitions for the IGZO bandgap validation workflow.

Both run_scf.py and run_bands.py import from here so that ENCUT, PREC, ALGO,
NPAR etc. stay identical across the two stages (only what has to differ —
IBRION/NSW being fixed at -1/0 for both, ISMEAR/SIGMA/KSPACING/ICHARG/LCHARG —
is set per-function below).

Physics/convergence settings (ENCUT, PREC, ALGO, NELM, SIGMA, KSPACING,
EDIFF, functional) are NOT hardcoded here -- they're loaded from a JSON
config via config.py (see that module's docstring). This module reads the
BANDGAP_CONFIG_PATH environment variable at import time; that path is set
by whichever driver script (driver.py / driver_local.py /
launch_workers.py) submitted the batch, pointing at the FROZEN
run_root/config_used.json for that run-root -- not necessarily your
current --config file, if you've edited it since submitting. See
config_bandgap.json for the editable starting template and
CONFIG_REFERENCE.md for a plain-language field reference.
NPAR (parallelization, not physics) stays a plain constant below rather
than a config field, same as VASP_PP_PATH/ASE_VASP_COMMAND are cluster
environment, not calculation settings.

Assumptions / things to check before running at scale:
  - VASP_PP_PATH must be set in your environment (pointing at the directory
    containing potpaw_PBE/) before ASE can write POTCAR files. Put this in
    your job script or ~/.bashrc on Sulis/Isambard-AI.
  - ASE_VASP_COMMAND (or the older VASP_COMMAND) must point at how to launch
    vasp_std under srun/mpirun on the cluster you're on, e.g.:
        export ASE_VASP_COMMAND="srun vasp_std"
  - config["sigma_elec"] defaults to 0.1, matching the strict-opts
    relaxation's SIGMA=0.1 uniformly (confirmed against your actual
    bandgaps/strict-opts/common.py).
  - config["functional"] ("pbe" or "optb88-vdw") switches BOTH stages
    together. optb88-vdw (GGA=BO) is for comparing against ALIGNN's
    JARVIS-DFT training convention, and runs on top of the EXISTING
    PBE-relaxed ("strict PBE opts") geometries -- deliberately not
    re-relaxed under OptB88-vdW first. Defaults to "pbe". (Previously this
    was a hardcoded module constant always True, so every bandgap run --
    including ones meant to be plain PBE -- silently used OptB88-vdW.)
  - The POTCAR family is standard PAW-PBE for BOTH branches -- VASP does not
    distribute a separate "optB88" pseudopotential set. The functional is
    entirely defined by the GGA=BO/PARAM1/PARAM2/LUSE_VDW INCAR tags; pp
    stays "PBE" either way (confirmed against VASP community guidance).
  - VDW_KERNEL_PATH must point at your confirmed-good vdw_kernel.bindat when
    functional is optb88-vdw -- required by GGA=BO/LUSE_VDW. Your VASP build
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

import config as _config

CFG = _config.load_config(_config.BANDGAP_CONFIG_FIELDS, os.environ.get("BANDGAP_CONFIG_PATH"))

ENCUT = CFG["encut"]
PREC = CFG["prec"]
ALGO = CFG["algo"]
NELM = CFG["nelm"]
NPAR = 8  # parallelization, not a physics setting -- see module docstring
SIGMA_ELEC = CFG["sigma_elec"]
KSPACING_SCF = CFG["kspacing_scf"]
EDIFF = CFG["ediff"]

# ---- OptB88-vdW ----
USE_OPTB88_VDW = CFG["functional"] == "optb88-vdw"
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
        ediff=EDIFF,
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
        ediff=EDIFF,     # was previously unset here, silently falling back to
        # VASP's own default (1e-4 eV) -- much looser than the SCF stage's
        # 1e-8, and inconsistent with the confirmed EDIFF=1e-8 for this
        # workflow. Caught while wiring this up to the config system.
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
