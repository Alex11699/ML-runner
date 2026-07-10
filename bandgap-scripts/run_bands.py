#!/usr/bin/env python
"""
Run the non-SCF band structure step for one structure, then extract the gap.

Usage:
    python run_bands.py <structure_file> <run_root>

Expects <run_root>/<structure_stem>/scf/CHGCAR to already exist (written by
run_scf.py). Writes results to <run_root>/<structure_stem>/bands/gap_result.json
"""
import sys
import json
import shutil
from pathlib import Path
from ase.io import read

from common import make_bands_calculator, extract_gap, run_vasp_with_explicit_kpoints
from claiming import finalize_structure
from pymatgen.io.vasp.inputs import Kpoints


def main():
    if len(sys.argv) != 3:
        print("Usage: python run_bands.py <structure_file> <run_root>")
        sys.exit(1)

    struct_path = Path(sys.argv[1])  # kept for CLI symmetry with run_scf.py; not read directly
    run_root = Path(sys.argv[2])
    name = struct_path.stem

    struct_dir = run_root / name
    scf_dir = struct_dir / "scf"
    bands_dir = struct_dir / "bands"
    bands_dir.mkdir(parents=True, exist_ok=True)

    primitive_path = struct_dir / "primitive.vasp"
    seekpath_kpoints_path = struct_dir / "seekpath_KPOINTS"
    chgcar_src = scf_dir / "CHGCAR"

    missing = [p for p in (primitive_path, seekpath_kpoints_path, chgcar_src)
               if not p.exists() or p.stat().st_size == 0]
    if missing:
        result = {"structure": name, "stage": "bands", "status": "failed",
                  "error": f"missing/empty required file(s) from SCF stage: {[str(p) for p in missing]}"}
        with open(bands_dir / "gap_result.json", "w") as f:
            json.dump(result, f, indent=2)
        print(f"[{name}] prerequisite files missing, aborting: {missing}")
        finalize_structure(struct_path, run_root, success=False)
        sys.exit(1)

    shutil.copy(chgcar_src, bands_dir / "CHGCAR")

    # Use the EXACT same primitive structure the SCF step ran on — do not
    # re-derive it from struct_path, and do not use the original structure.
    atoms = read(primitive_path, format="vasp")
    kpoints_obj = Kpoints.from_file(str(seekpath_kpoints_path))

    calc = make_bands_calculator(str(bands_dir))

    result = {"structure": name, "stage": "bands"}
    try:
        run_vasp_with_explicit_kpoints(atoms, calc, kpoints_obj)
        gap_info = extract_gap(
            str(bands_dir / "vasprun.xml"),
            str(bands_dir / "KPOINTS"),
        )
        if "error" in gap_info:
            result["status"] = "gap_extraction_failed"
            result["error"] = gap_info["error"]
        else:
            result["status"] = "ok"
            result.update(gap_info)
    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)

    with open(bands_dir / "gap_result.json", "w") as f:
        json.dump(result, f, indent=2)

    # This is always the terminal stage for a structure (nothing runs after
    # bands), so finalize here regardless of outcome.
    finalize_structure(struct_path, run_root, success=(result["status"] == "ok"))

    if result["status"] != "ok":
        print(f"[{name}] bands stage problem: {result.get('error')}")
        sys.exit(1)

    print(f"[{name}] gap={result['energy']:.3f} eV direct={result['direct']}")


if __name__ == "__main__":
    main()
