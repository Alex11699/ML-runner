#!/usr/bin/env python
"""
Aggregate per-structure dielectric_result.json files into one CSV, optionally
joined against ALIGNN 'jv_dfpt_piezo_max_dielectric_alignn' predictions.

That model predicts JARVIS-DFT's 'dfpt_piezo_max_dielectric' property: the
TOTAL (electronic + ionic) dielectric response, reduced to a single scalar
as the MAXIMUM EIGENVALUE of the diagonalized tensor -- not the isotropic
mean. Since your structures are generally anisotropic, this is a genuinely
different number from total_mean (trace/3), so it's computed separately
here (total_max_eigenvalue) from the tensor already stored in each result.

Usage:
    python collect_results_dielectric.py --run-root runs_dielectric/ \
        --alignn-preds alignn_dielectric_predictions.csv \
        --out dielectric_results.csv

alignn_dielectric_predictions.csv expected columns:
    structure, alignn_max_dielectric
matched by structure name (== structure_file.stem, same convention used
throughout the rest of the pipeline).
"""
import argparse
import json
import csv
from pathlib import Path

import numpy as np


def max_eigenvalue(tensor_list):
    """Max eigenvalue of a stored 3x3 tensor (as nested lists from JSON).
    Symmetrizes first as a guard against tiny numerical asymmetry from the
    OUTCAR parse -- the physical dielectric tensor is symmetric, so any
    asymmetry here should only be floating-point noise, not signal."""
    if tensor_list is None:
        return None
    t = np.array(tensor_list, dtype=float)
    t_sym = 0.5 * (t + t.T)
    return float(np.max(np.linalg.eigvalsh(t_sym)))


def load_alignn_preds(path: Path):
    preds = {}
    if not path or not path.exists():
        return preds
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            preds[row["structure"]] = row
    return preds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-root", required=True, type=Path)
    ap.add_argument("--alignn-preds", type=Path, default=None,
                     help="CSV with structure,alignn_max_dielectric "
                          "(jv_dfpt_piezo_max_dielectric_alignn predictions)")
    ap.add_argument("--out", type=Path, default=Path("dielectric_results.csv"))
    args = ap.parse_args()

    alignn_preds = load_alignn_preds(args.alignn_preds)

    rows = []
    for struct_dir in sorted(args.run_root.iterdir()):
        if not struct_dir.is_dir():
            continue
        if struct_dir.name in ("_claims", "_worker_logs"):
            continue  # reserved bookkeeping dirs used by driver_local_dielectric.py's claim/move logic
        name = struct_dir.name
        result_file = struct_dir / "dielectric" / "dielectric_result.json"

        row = {"structure": name, "status": "missing", "error": None,
               "electronic_mean": None, "ionic_mean": None, "total_mean": None,
               "total_max_eigenvalue": None,
               "alignn_max_dielectric": None, "dft_minus_alignn": None,
               "electronic_tensor": None, "ionic_tensor": None, "total_tensor": None}

        if result_file.exists():
            data = json.loads(result_file.read_text())
            row["status"] = data.get("status")
            row["error"] = data.get("error")
            if data.get("status") == "ok":
                row["electronic_mean"] = data.get("electronic_mean")
                row["ionic_mean"] = data.get("ionic_mean")
                row["total_mean"] = data.get("total_mean")
                row["total_max_eigenvalue"] = max_eigenvalue(data.get("total_tensor"))
                row["electronic_tensor"] = json.dumps(data.get("electronic_tensor"))
                row["ionic_tensor"] = json.dumps(data.get("ionic_tensor"))
                row["total_tensor"] = json.dumps(data.get("total_tensor"))

        pred = alignn_preds.get(name)
        if pred:
            row["alignn_max_dielectric"] = pred.get("alignn_max_dielectric")
            if row["total_max_eigenvalue"] is not None and pred.get("alignn_max_dielectric"):
                try:
                    row["dft_minus_alignn"] = row["total_max_eigenvalue"] - float(pred["alignn_max_dielectric"])
                except ValueError:
                    pass

        rows.append(row)

    fieldnames = ["structure", "status", "total_max_eigenvalue", "alignn_max_dielectric",
                  "dft_minus_alignn", "electronic_mean", "ionic_mean", "total_mean",
                  "electronic_tensor", "ionic_tensor", "total_tensor", "error"]
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    n_ok = sum(1 for r in rows if r["status"] == "ok")
    print(f"{n_ok}/{len(rows)} structures completed successfully.")
    print(f"Written to {args.out}")

    print(f"\n{'structure':<30} {'dft (total_max_eig)':>20} {'alignn':>10}")
    print("-" * 62)
    for r in rows:
        dft_val = f"{r['total_max_eigenvalue']:.3f}" if r["total_max_eigenvalue"] is not None else "-"
        alignn_val = r["alignn_max_dielectric"] if r["alignn_max_dielectric"] is not None else "-"
        print(f"{r['structure']:<30} {dft_val:>20} {str(alignn_val):>10}")


if __name__ == "__main__":
    main()
