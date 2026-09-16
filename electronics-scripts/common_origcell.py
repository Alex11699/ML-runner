"""
ONE-OFF TEST VARIANT -- not part of the regular bandgap workflow, doesn't
touch it, and isn't wired into config.py/driver.py/launch_workers.py.

Tests whether skipping seekpath's cell primitivization/standardization step
and working directly on the ORIGINAL input cell changes the calculated
bandgap, versus the regular workflow's approach (common.py's
get_seekpath_primitive_and_kpoints(), which standardizes to seekpath's
primitive cell first).

Everything except the k-path generation step is reused UNCHANGED from
common.py (make_scf_calculator, make_bands_calculator, stage_vdw_kernel,
run_vasp_with_explicit_kpoints, extract_gap) -- same ENCUT/EDIFF/functional/
config machinery, same VASP settings, same VDW kernel staging. Only the
k-path step differs. Import common's CFG/ENCUT/etc. are unaffected by this
module -- it's a pure addition.

WHY THIS NEEDS TO BYPASS pymatgen's KPathSeek:
pymatgen.symmetry.kpath.KPathSeek (what common.py uses) always calls
spglib.standardize_cell(...) and then seekpath.getpaths.get_path() on the
standardized result -- there's no parameter to skip that. The underlying
`seekpath` package itself, however, has a separate pair of functions
specifically for this: get_path_orig_cell() / get_explicit_k_path_orig_cell(),
which compute the k-path for the cell AS GIVEN, with no standardization or
symmetrization of the input structure. This module calls the explicit-path
variant directly, bypassing pymatgen's wrapper entirely, and builds a
pymatgen Kpoints object from its output by hand.

CAVEATS (read before trusting a comparison against the regular workflow):
  - Point density is controlled differently: the regular workflow uses
    pymatgen's line_density (points per unit RECIPROCAL LENGTH, sampled by
    pymatgen's own segment-walking code in KPathBase.get_kpoints()); this
    module uses seekpath's own reference_distance (target spacing between
    neighboring k-points, in 1/Angstrom, via seekpath's own explicit-path
    generator). These are conceptually similar but not numerically
    identical knobs -- don't assume line_density=20 and
    reference_distance=0.025 (seekpath's own default) produce the same
    point density. If point density matters to your comparison, check the
    actual kpoint counts (printed by run_scf_origcell.py) between the two
    runs and adjust REFERENCE_DISTANCE below if they're wildly different.
  - If the original cell is a non-primitive setting of a smaller cell (the
    IGZO CSP structures may or may not be, depending on the generator),
    seekpath's docs note the k-point labels lose their high-symmetry
    meaning and a SupercellWarning is raised -- watch stderr/logs for that
    per structure.
  - Labels come through as seekpath's own strings (e.g. "GAMMA", not "Γ"),
    same convention the regular workflow already uses via KPathSeek, so
    this isn't a NEW inconsistency -- just noting it's unchanged.
"""
from pathlib import Path

import seekpath
from pymatgen.io.vasp.inputs import Kpoints

REFERENCE_DISTANCE = 0.025  # 1/Angstrom -- seekpath's own default; see caveat above


def get_kpoints_orig_cell(atoms, reference_distance=REFERENCE_DISTANCE, symprec=1e-3):
    """
    Original-cell equivalent of common.py's get_seekpath_primitive_and_kpoints()
    -- same return shape, so it's a drop-in swap in the run_scf/run_bands
    scripts, but:
      - does NOT primitivize/standardize the input structure at all -- the
        atoms you pass in are returned unchanged, not a seekpath-primitive
        copy
      - uses seekpath's get_explicit_k_path_orig_cell() directly, not
        pymatgen's KPathSeek

    Returns:
        atoms: the SAME atoms object passed in, unmodified (for interface
            parity with get_seekpath_primitive_and_kpoints's primitive_atoms
            return slot -- here there's no primitivization to do).
        kpoints_obj: pymatgen Kpoints object with the explicit, labeled
            k-point path in the ORIGINAL cell's reciprocal lattice, ready
            to write directly to a VASP KPOINTS file.
        spacegroup_info: (symbol, number) tuple from seekpath's own
            symmetry detection, for logging/QA -- same shape as the regular
            workflow's spacegroup_info, sourced differently (seekpath's
            spglib call internally, vs. pymatgen's SpacegroupAnalyzer).
    """
    cell = atoms.cell[:]
    positions = atoms.get_scaled_positions().tolist()
    numbers = atoms.get_atomic_numbers().tolist()
    structure = (cell, positions, numbers)

    result = seekpath.get_explicit_k_path_orig_cell(
        structure,
        with_time_reversal=True,
        reference_distance=reference_distance,
        symprec=symprec,
    )

    kpoints_obj = Kpoints(
        comment=f"seekpath ORIGINAL-CELL explicit path (no primitivization), "
                f"spacegroup {result['spacegroup_international']} "
                f"({result['spacegroup_number']})",
        style=Kpoints.supported_modes.Reciprocal,
        num_kpts=len(result["explicit_kpoints_rel"]),
        kpts=result["explicit_kpoints_rel"].tolist(),
        kpts_weights=[1] * len(result["explicit_kpoints_rel"]),
        labels=list(result["explicit_kpoints_labels"]),
    )

    spacegroup_info = (result["spacegroup_international"], result["spacegroup_number"])

    if result.get("is_supercell"):
        print(f"WARNING: seekpath flagged this as a supercell of a smaller "
              f"primitive cell -- k-point labels below may not correspond "
              f"to actual high-symmetry points of THIS cell's Brillouin "
              f"zone. See this module's docstring.")

    return atoms, kpoints_obj, spacegroup_info
