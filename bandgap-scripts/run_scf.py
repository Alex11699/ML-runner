#!/usr/bin/env python
"""
Run the static SCF step for one structure.

Usage:
    python run_scf.py <structure_file> <run_root>

Writes output to <run_root>/<structure_stem>/scf/ including CHGCAR,
which run_bands.py will read next.
"""
import sys
import json
from pathlib import Path
from ase.io import read, write

from common import make_scf_calculator, get_seekpath_primitive_and_kpoints
from claiming import finalize_structure


def main():
    if len(sys.argv) != 3:
        print("Usage: python run_scf.py <structure_file> <run_root>")
        sys.exit(1)

    struct_path = Path(sys.argv[1])
    run_root = Path(sys.argv[2])
    name = struct_path.stem

    struct_dir = run_root / name
    workdir = struct_dir / "scf"
    workdir.mkdir(parents=True, exist_ok=True)

    orig_atoms = read(struct_path)

    # Derive the seekpath-standardized primitive structure ONCE here, save
    # it to disk (primitive.vasp) so run_bands.py reads the exact same
    # cell rather than re-deriving it — the SCF density (CHGCAR) is only
    # valid for the exact cell it was computed on.
    primitive_atoms, kpoints_obj, spacegroup_info = get_seekpath_primitive_and_kpoints(orig_atoms)
    write(struct_dir / "primitive.vasp", primitive_atoms, format="vasp")
    kpoints_obj.write_file(str(struct_dir / "seekpath_KPOINTS"))
    with open(struct_dir / "spacegroup_info.json", "w") as f:
        json.dump({"symbol": spacegroup_info[0], "number": spacegroup_info[1],
                   "n_atoms_original": len(orig_atoms), "n_atoms_primitive": len(primitive_atoms)}, f, indent=2)

    atoms = primitive_atoms
    calc = make_scf_calculator(str(workdir))
    atoms.calc = calc

    status = {"structure": name, "stage": "scf",
              "spacegroup": spacegroup_info[0], "spacegroup_number": spacegroup_info[1]}
    try:
        energy = atoms.get_potential_energy()
        status["status"] = "ok"
        status["energy"] = energy
        chgcar = workdir / "CHGCAR"
        status["chgcar_written"] = chgcar.exists() and chgcar.stat().st_size > 0
    except Exception as e:
        status["status"] = "failed"
        status["error"] = str(e)

    with open(workdir / "scf_status.json", "w") as f:
        json.dump(status, f, indent=2)

    # non-zero exit on failure so the Slurm dependency (afterok) blocks the bands job
    if status["status"] != "ok" or not status.get("chgcar_written"):
        print(f"[{name}] SCF failed or CHGCAR missing: {status.get('error', 'no CHGCAR')}")
        # Under sbatch, the bands job's afterok dependency means it will never
        # run if SCF failed — so nothing else will ever finalize this
        # structure. Move it to failed now rather than leaving it stuck in
        # _structures_inprogress forever. (Under driver_local.py this is a
        # no-op duplicate of what would happen anyway, which is fine.)
        finalize_structure(struct_path, run_root, success=False)
        sys.exit(1)

    print(f"[{name}] SCF ok, energy={energy:.6f} eV")


if __name__ == "__main__":
    main()
