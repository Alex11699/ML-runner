#!/usr/bin/env python
"""
Finite-displacement phonon dispersion for one structure: phonopy builds a
supercell + symmetry-inequivalent displacements, VASP computes forces at
each displaced supercell (plain SCF, NOT DFPT -- see common_phonons.py's
module docstring for why this route was chosen over DFPT-on-supercell),
phonopy assembles force constants and generates the dispersion (band.yaml)
along an automatic q-path (phonopy's own path generation uses seekpath
internally -- the same tool the bandgap workflow's electronic k-path
already uses, a nice consistency).

PREREQUISITE: the input structure must already be well-relaxed -- finite
displacements assume near-zero residual forces at the undisplaced
geometry (same caveat as common_dielectric.py's IBRION=8 prerequisite).

BORN / LO-TO CORRECTION: if a completed dielectric_result.json (and its
sibling vasprun.xml) exists for this structure under
run_root/<name>/dielectric/ -- from the EXISTING, separate LEPSILON
workflow, see run_dielectric.py -- this script shells out to phonopy's own
`phonopy-vasp-born` tool against it to build a BORN file automatically,
picked up as the non-analytical correction near Gamma. Not required --
dispersion away from Gamma is unaffected by its absence, and this script
proceeds (recording born_applied=False) if it's missing or the tool isn't
on PATH.

CONFIDENCE NOTE: see common_phonons.py's docstring -- the band-path and
BORN-file steps below were written from phonopy's documented API/CLI but
not exercised against a live phonopy install. Test against one structure
first and check stderr/the result JSON's "warnings" list before trusting
a full batch.

Usage:
    python run_phonons.py <structure_file> <run_root>
"""
import subprocess
import sys
import json
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.io import read

from common_phonons import (
    make_force_calculator, resolve_supercell_matrix,
    DISPLACEMENT_DISTANCE, BAND_NPOINTS,
)
from claiming import ensure_dirs, release_claim, write_status

try:
    from phonopy import Phonopy
    from phonopy.structure.atoms import PhonopyAtoms
    from phonopy.file_IO import parse_BORN
except ImportError:
    Phonopy = None


def ase_to_phonopy(atoms: Atoms) -> "PhonopyAtoms":
    return PhonopyAtoms(
        symbols=atoms.get_chemical_symbols(),
        cell=atoms.get_cell()[:],
        scaled_positions=atoms.get_scaled_positions(),
    )


def phonopy_to_ase(patoms: "PhonopyAtoms") -> Atoms:
    return Atoms(
        symbols=patoms.symbols,
        cell=patoms.cell,
        scaled_positions=patoms.scaled_positions,
        pbc=True,
    )


def run_one_force_calc(supercell_atoms: Atoms, workdir: Path) -> np.ndarray:
    """Run a single-point VASP force evaluation on one displaced
    supercell, return the (n_atoms, 3) forces array."""
    workdir.mkdir(parents=True, exist_ok=True)
    calc = make_force_calculator(str(workdir))
    supercell_atoms.calc = calc
    supercell_atoms.get_potential_energy()  # triggers the VASP run
    return supercell_atoms.get_forces()


def try_build_born(run_root: Path, name: str, phonon: "Phonopy", workdir: Path):
    """
    Attempt to build a BORN file from the existing (separate) dielectric
    workflow's output for this structure, and set it as phonon.nac_params.
    Returns (born_applied: bool, note: str) -- never raises; any failure
    just means no LO-TO correction, not a fatal error for this script.
    """
    dielectric_vasprun = run_root / name / "dielectric" / "vasprun.xml"
    if not dielectric_vasprun.exists():
        return False, "no dielectric_result vasprun.xml found -- run the " \
                       "dielectric (LEPSILON) workflow for this structure " \
                       "first if you want the LO-TO correction."
    born_path = workdir / "BORN"
    try:
        result = subprocess.run(
            ["phonopy-vasp-born", str(dielectric_vasprun)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True,
        )
        born_path.write_text(result.stdout)
        nac_params = parse_BORN(phonon.primitive, filename=str(born_path))
        phonon.nac_params = nac_params
        return True, "BORN file built from existing dielectric run and applied."
    except FileNotFoundError:
        return False, "phonopy-vasp-born not found on PATH -- is phonopy installed in this env?"
    except subprocess.CalledProcessError as e:
        return False, f"phonopy-vasp-born failed: {e.stderr.strip()[:500]}"
    except Exception as e:
        return False, f"BORN parsing/application failed: {e}"


def try_auto_dispersion(phonon: "Phonopy", workdir: Path):
    """
    Generate the dispersion curve along phonopy's automatic (seekpath-
    derived) q-path and write band.yaml. Returns (ok: bool, note: str).
    See this file's CONFIDENCE NOTE / common_phonons.py's docstring --
    this specific step is the least-tested part of the pipeline.
    """
    try:
        from phonopy.phonon.band_structure import get_band_qpoints_by_seekpath
        qpoints, labels, connections = get_band_qpoints_by_seekpath(phonon.primitive, BAND_NPOINTS)
        phonon.run_band_structure(qpoints, path_connections=connections, labels=labels)
        phonon.write_yaml_band_structure(filename=str(workdir / "band.yaml"))
        return True, "band.yaml written via automatic seekpath q-path."
    except Exception as e:
        return False, f"automatic dispersion generation failed: {e}"


def main():
    if len(sys.argv) != 3:
        print("Usage: python run_phonons.py <structure_file> <run_root>")
        sys.exit(1)

    if Phonopy is None:
        print("phonopy is not importable -- `pip install phonopy` in this environment.")
        sys.exit(1)

    struct_path = Path(sys.argv[1])
    run_root = Path(sys.argv[2])
    name = struct_path.stem

    workdir = run_root / name / "phonons"
    workdir.mkdir(parents=True, exist_ok=True)

    atoms = read(struct_path)
    supercell_matrix = resolve_supercell_matrix(atoms)

    result = {
        "structure": name,
        "stage": "phonons",
        "supercell": supercell_matrix,
        "n_atoms_unitcell": len(atoms),
        "warnings": [],
    }

    try:
        unitcell = ase_to_phonopy(atoms)
        phonon = Phonopy(unitcell, supercell_matrix=np.diag(supercell_matrix),
                          primitive_matrix="auto")
        phonon.generate_displacements(distance=DISPLACEMENT_DISTANCE)

        displaced_supercells = phonon.supercells_with_displacements
        result["n_displacements"] = len(displaced_supercells)
        n_atoms_supercell = len(displaced_supercells[0].symbols) if displaced_supercells else 0
        print(f"[{name}] {len(displaced_supercells)} displaced supercell(s) "
              f"({n_atoms_supercell} atoms each, matrix {supercell_matrix}) to run.")

        force_sets = []
        for i, disp_supercell in enumerate(displaced_supercells):
            disp_workdir = workdir / f"disp-{i:03d}"
            disp_atoms = phonopy_to_ase(disp_supercell)
            print(f"[{name}] running force calc {i + 1}/{len(displaced_supercells)}...")
            forces = run_one_force_calc(disp_atoms, disp_workdir)
            force_sets.append(forces)

        phonon.forces = force_sets
        phonon.produce_force_constants()
        phonon.save(filename=str(workdir / "phonopy_params.yaml"),
                     settings={"force_constants": True})

        born_applied, born_note = try_build_born(run_root, name, phonon, workdir)
        result["born_applied"] = born_applied
        result["warnings"].append(born_note)

        dispersion_ok, dispersion_note = try_auto_dispersion(phonon, workdir)
        result["dispersion_written"] = dispersion_ok
        result["warnings"].append(dispersion_note)

        result["status"] = "ok"

    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)

    write_status(workdir / "phonons_result.json", result)

    # Only stage for a structure in this workflow -> release unconditionally,
    # same convention as run_dielectric.py.
    release_claim(name, ensure_dirs(run_root))

    if result["status"] != "ok":
        print(f"[{name}] phonons stage problem: {result.get('error')}")
        sys.exit(1)

    print(f"[{name}] phonons OK: {result['n_displacements']} displacement(s), "
          f"born_applied={result['born_applied']}, "
          f"dispersion_written={result['dispersion_written']}")


if __name__ == "__main__":
    main()
