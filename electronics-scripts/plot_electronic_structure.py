#!/usr/bin/env python
"""
Sanity-check the electronic structure of an already-completed bandgap
calculation by plotting the actual band structure (and optionally DOS)
directly from the saved VASP outputs -- no rerun needed.

Reads:
    runs/<structure_name>/bands/vasprun.xml + KPOINTS  -> band structure
    runs/<structure_name>/scf/vasprun.xml               -> DOS (optional)

These files already exist for every completed structure -- run_bands.py's
extract_gap() parses the same vasprun.xml to get the numbers already sitting
in gap_result.json; this script builds the same BandStructureSymmLine object
but renders it visually instead of reducing it to a single gap number, which
is the actual value-add for spotting things a scalar gap can't show: weird
band crossings, an implausible VBM/CBM location, a gap that's technically
"direct" by a hair but visually looks like it should be indirect, etc.

Usage:
    python plot_electronic_structure.py Zn2InGaO5 --run-root runs/
    python plot_electronic_structure.py Zn2InGaO5 --run-root runs/ --dos
    python plot_electronic_structure.py Zn2InGaO5 --run-root runs/ --ylim -3 5
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless -- no display on a login node/compute node

from pymatgen.io.vasp import Vasprun
from pymatgen.electronic_structure.plotter import BSPlotter, DosPlotter


def plot_bands(struct_dir: Path, out_path: Path, ylim=None):
    bands_dir = struct_dir / "bands"
    vasprun_path = bands_dir / "vasprun.xml"
    kpoints_path = bands_dir / "KPOINTS"

    if not vasprun_path.exists():
        print(f"No {vasprun_path} found -- has the bands stage completed for this structure?")
        return False

    vr = Vasprun(str(vasprun_path), parse_potcar_file=False)
    bs = vr.get_band_structure(kpoints_filename=str(kpoints_path), line_mode=True)

    gap = bs.get_band_gap()
    vbm = bs.get_vbm()
    cbm = bs.get_cbm()
    print(f"gap = {gap['energy']:.3f} eV, direct = {gap['direct']}, "
          f"transition = {gap.get('transition')}")
    print(f"is_metal = {bs.is_metal()}")
    if vbm:
        print(f"VBM at: {getattr(vbm.get('kpoint'), 'label', None)}")
    if cbm:
        print(f"CBM at: {getattr(cbm.get('kpoint'), 'label', None)}")

    plotter = BSPlotter(bs)
    # save_plot() doesn't expose vbm_cbm_marker at all -- only the lower-level
    # get_plot() does (confirmed against pymatgen's actual signatures), which
    # is why this saves the returned Axes' figure directly instead of using
    # the save_plot() convenience wrapper. vbm_cbm_marker=True overlays the
    # automatically-determined VBM/CBM directly on the plot, so the visual
    # and automatic determination sit on the same figure -- the actual point
    # of this script (per supervisor feedback: compare them side by side to
    # spot artifacts) rather than requiring you to cross-reference the
    # printed text above against the image separately.
    ax = plotter.get_plot(zero_to_efermi=True, ylim=ylim if ylim else None,
                           vbm_cbm_marker=True)
    ax.figure.savefig(str(out_path), bbox_inches="tight")
    ax.figure.clf()
    print(f"Band structure plot written to {out_path} (VBM/CBM marked)")
    return True


def plot_dos(struct_dir: Path, out_path: Path, ylim=None):
    scf_vasprun = struct_dir / "scf" / "vasprun.xml"
    if not scf_vasprun.exists():
        print(f"No {scf_vasprun} found -- has the SCF stage completed for this structure?")
        return False

    vr = Vasprun(str(scf_vasprun), parse_potcar_file=False)
    dos = vr.complete_dos

    plotter = DosPlotter(sigma=0.05)
    plotter.add_dos("Total DOS", dos)
    plotter.save_plot(str(out_path), xlim=None, ylim=ylim)
    print(f"DOS plot written to {out_path}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("structure_name")
    ap.add_argument("--run-root", required=True, type=Path)
    ap.add_argument("--out-dir", type=Path, default=None,
                     help="defaults to runs/<structure_name>/bands/")
    ap.add_argument("--dos", action="store_true", help="also plot DOS from the SCF stage")
    ap.add_argument("--ylim", type=float, nargs=2, default=None,
                     help="e.g. --ylim -3 5, energy window around VBM/CBM in eV")
    args = ap.parse_args()

    struct_dir = args.run_root / args.structure_name
    if not struct_dir.exists():
        print(f"No such structure directory: {struct_dir}")
        return

    out_dir = args.out_dir or (struct_dir / "bands")
    out_dir.mkdir(parents=True, exist_ok=True)

    plot_bands(struct_dir, out_dir / f"{args.structure_name}_bands.png", ylim=args.ylim)

    if args.dos:
        plot_dos(struct_dir, out_dir / f"{args.structure_name}_dos.png", ylim=None)


if __name__ == "__main__":
    main()
