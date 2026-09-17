#!/usr/bin/env python
"""
Run the full static dielectric tensor calculation (electronic + ionic, via
DFPT: IBRION=8/LEPSILON/LPEAD) for one structure.

Unlike the bandgap workflow, this is SINGLE-STAGE -- no SCF/bands split, no
seekpath primitivization, no explicit k-path. Runs directly on the input
structure using a standard k-mesh, so this file is much simpler than
run_scf.py/run_bands.py.

PREREQUISITE: the input structure must already be relaxed -- see
common_dielectric.py's module docstring for why.

Usage:
    python run_dielectric.py <structure_file> <run_root>
"""
import sys
import json
from pathlib import Path
from ase.io import read

from common_dielectric import make_dielectric_calculator, extract_dielectric
from claiming import ensure_dirs, release_claim, write_status


def main():
    if len(sys.argv) != 3:
        print("Usage: python run_dielectric.py <structure_file> <run_root>")
        sys.exit(1)

    struct_path = Path(sys.argv[1])
    run_root = Path(sys.argv[2])
    name = struct_path.stem

    workdir = run_root / name / "dielectric"
    workdir.mkdir(parents=True, exist_ok=True)

    atoms = read(struct_path)
    calc = make_dielectric_calculator(str(workdir))
    atoms.calc = calc

    result = {"structure": name, "stage": "dielectric"}
    try:
        atoms.get_potential_energy()  # triggers the DFPT run
        diel = extract_dielectric(str(workdir / "OUTCAR"))
        if "error" in diel:
            result["status"] = "extraction_failed"
            result["error"] = diel["error"]
        else:
            result["status"] = "ok"
            result.update(diel)
    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)

    write_status(workdir / "dielectric_result.json", result)

    # This is the only (and therefore always terminal) stage for a structure
    # in this workflow, so release the claim here regardless of outcome.
    # The structure file itself never moved; result["status"] in this
    # dielectric_result.json is the actual record of success/failure.
    release_claim(name, ensure_dirs(run_root))

    if result["status"] != "ok":
        print(f"[{name}] dielectric stage problem: {result.get('error')}")
        sys.exit(1)

    print(f"[{name}] dielectric OK: electronic_mean={result['electronic_mean']:.3f}, "
          f"ionic_mean={result['ionic_mean']:.3f}, total_mean={result['total_mean']:.3f}")


if __name__ == "__main__":
    main()
