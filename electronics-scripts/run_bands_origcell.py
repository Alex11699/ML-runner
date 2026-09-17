#!/usr/bin/env python
"""
ONE-OFF TEST VARIANT of run_bands.py, pairs with run_scf_origcell.py --
reads cell.vasp/seekpath_orig_cell_KPOINTS instead of
primitive.vasp/seekpath_KPOINTS. Everything else (calculator settings,
gap extraction) unchanged, reused from common.py as-is.

Usage:
    python run_bands_origcell.py <structure_file> <run_root>

Expects <run_root>/<structure_stem>/scf/CHGCAR to already exist (written by
run_scf_origcell.py). Writes results to
<run_root>/<structure_stem>/bands/gap_result.json
"""
import sys
import json
import shutil
from pathlib import Path
from ase.io import read

from common import make_bands_calculator, extract_gap, run_vasp_with_explicit_kpoints, stage_vdw_kernel
from claiming import ensure_dirs, release_claim, write_status
from pymatgen.io.vasp.inputs import Kpoints


def main():
    if len(sys.argv) != 3:
        print("Usage: python run_bands_origcell.py <structure_file> <run_root>")
        sys.exit(1)

    struct_path = Path(sys.argv[1])  # kept for CLI symmetry with run_scf_origcell.py; not read directly
    run_root = Path(sys.argv[2])
    name = struct_path.stem

    struct_dir = run_root / name
    scf_dir = struct_dir / "scf"
    bands_dir = struct_dir / "bands"
    bands_dir.mkdir(parents=True, exist_ok=True)

    cell_path = struct_dir / "cell.vasp"
    seekpath_kpoints_path = struct_dir / "seekpath_orig_cell_KPOINTS"
    chgcar_src = scf_dir / "CHGCAR"

    missing = [p for p in (cell_path, seekpath_kpoints_path, chgcar_src)
               if not p.exists() or p.stat().st_size == 0]
    if missing:
        result = {"structure": name, "stage": "bands", "status": "failed",
                  "error": f"missing/empty required file(s) from SCF stage: {[str(p) for p in missing]}"}
        write_status(bands_dir / "gap_result.json", result)
        print(f"[{name}] prerequisite files missing, aborting: {missing}")
        release_claim(name, ensure_dirs(run_root))
        sys.exit(1)

    shutil.copy(chgcar_src, bands_dir / "CHGCAR")

    # Use the EXACT same cell the SCF step ran on — do not re-derive it from
    # struct_path.
    atoms = read(cell_path, format="vasp")
    kpoints_obj = Kpoints.from_file(str(seekpath_kpoints_path))

    calc = make_bands_calculator(str(bands_dir))
    stage_vdw_kernel(str(bands_dir))  # no-op unless config's functional is optb88-vdw

    result = {"structure": name, "stage": "bands", "kpath_mode": "orig_cell"}
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

    write_status(bands_dir / "gap_result.json", result)

    release_claim(name, ensure_dirs(run_root))

    if result["status"] != "ok":
        print(f"[{name}] bands stage problem: {result.get('error')}")
        sys.exit(1)

    print(f"[{name}] gap={result['energy']:.3f} eV direct={result['direct']} (orig-cell k-path)")


if __name__ == "__main__":
    main()
