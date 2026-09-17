#!/usr/bin/env python
"""
ONE-OFF TEST VARIANT of run_scf.py -- uses common_origcell.get_kpoints_orig_cell()
instead of common.get_seekpath_primitive_and_kpoints(), so the ORIGINAL input
cell is used directly with no seekpath primitivization/standardization step.
Everything else (calculator settings, config, VDW kernel staging, claiming)
is unchanged, reused from common.py as-is.

Point this at its OWN --run-root, separate from the regular workflow's, e.g.
runs_origcell/ -- config_used.json and claim locks are per-run-root, but
there's no reason to interleave this test's structures with the regular
pipeline's.

Usage:
    python run_scf_origcell.py <structure_file> <run_root>

Writes output to <run_root>/<structure_stem>/scf/ including CHGCAR,
which run_bands_origcell.py will read next.
"""
import sys
import json
from pathlib import Path
from ase.io import read, write

from common import make_scf_calculator, stage_vdw_kernel
from common_origcell import get_kpoints_orig_cell
from claiming import ensure_dirs, release_claim, write_status


def main():
    if len(sys.argv) != 3:
        print("Usage: python run_scf_origcell.py <structure_file> <run_root>")
        sys.exit(1)

    struct_path = Path(sys.argv[1])
    run_root = Path(sys.argv[2])
    name = struct_path.stem

    struct_dir = run_root / name
    workdir = struct_dir / "scf"
    workdir.mkdir(parents=True, exist_ok=True)

    orig_atoms = read(struct_path)

    # NO primitivization here (that's the whole point of this variant) --
    # atoms comes back unchanged. Still saved to disk under the SAME
    # filename convention (cell.vasp) run_bands_origcell.py expects, so the
    # two stages agree on exactly which cell/k-path was used, same
    # CHGCAR-validity reasoning as the regular workflow's primitive.vasp.
    atoms, kpoints_obj, spacegroup_info = get_kpoints_orig_cell(orig_atoms)
    write(struct_dir / "cell.vasp", atoms, format="vasp")
    kpoints_obj.write_file(str(struct_dir / "seekpath_orig_cell_KPOINTS"))
    with open(struct_dir / "spacegroup_info.json", "w") as f:
        json.dump({"symbol": spacegroup_info[0], "number": spacegroup_info[1],
                   "n_atoms": len(atoms), "kpath_mode": "orig_cell",
                   "n_kpoints": kpoints_obj.num_kpts}, f, indent=2)

    calc = make_scf_calculator(str(workdir))
    stage_vdw_kernel(str(workdir))  # no-op unless config's functional is optb88-vdw
    atoms.calc = calc

    status = {"structure": name, "stage": "scf", "kpath_mode": "orig_cell",
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

    status = write_status(workdir / "scf_status.json", status)

    if status["status"] != "ok" or not status.get("chgcar_written"):
        print(f"[{name}] SCF failed or CHGCAR missing: {status.get('error', 'no CHGCAR')}")
        release_claim(name, ensure_dirs(run_root))
        sys.exit(1)

    print(f"[{name}] SCF ok (orig-cell k-path, {kpoints_obj.num_kpts} kpts), energy={energy:.6f} eV")


if __name__ == "__main__":
    main()
