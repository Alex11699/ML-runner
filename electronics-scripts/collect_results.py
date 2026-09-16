#!/usr/bin/env python
"""
Aggregate per-structure gap_result.json files into one CSV, joined against
ALIGNN predictions (and Materials Project references where you have them).

Usage:
    python collect_results.py --run-root runs/ \
        --alignn-preds alignn_predictions.csv \
        --out gap_validation_results.csv

alignn_predictions.csv is expected to have at least columns:
    structure, alignn_gap_ev
and optionally:
    mp_reference_gap_ev
matched by the structure name (== structure_file.stem used throughout the
pipeline, e.g. the name in your fuse/mattergen registry CSV).
"""
import argparse
import json
import csv
from pathlib import Path


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
                     help="CSV with structure,alignn_gap_ev[,mp_reference_gap_ev]")
    ap.add_argument("--out", type=Path, default=Path("gap_validation_results.csv"))
    args = ap.parse_args()

    alignn_preds = load_alignn_preds(args.alignn_preds)

    rows = []
    for struct_dir in sorted(args.run_root.iterdir()):
        if not struct_dir.is_dir():
            continue
        if struct_dir.name in ("_claims", "_worker_logs"):
            continue  # reserved bookkeeping dirs used by driver_local.py's claim/move logic
        name = struct_dir.name
        gap_file = struct_dir / "bands" / "gap_result.json"

        row = {"structure": name, "dft_gap_ev": None, "direct": None,
               "status": "missing", "error": None,
               "alignn_gap_ev": None, "mp_reference_gap_ev": None,
               "dft_minus_alignn": None}

        if gap_file.exists():
            data = json.loads(gap_file.read_text())
            row["status"] = data.get("status")
            row["error"] = data.get("error")
            if data.get("status") == "ok":
                row["dft_gap_ev"] = data.get("energy")
                row["direct"] = data.get("direct")

        pred = alignn_preds.get(name)
        if pred:
            row["alignn_gap_ev"] = pred.get("alignn_gap_ev")
            row["mp_reference_gap_ev"] = pred.get("mp_reference_gap_ev")
            if row["dft_gap_ev"] is not None and pred.get("alignn_gap_ev"):
                try:
                    row["dft_minus_alignn"] = float(row["dft_gap_ev"]) - float(pred["alignn_gap_ev"])
                except ValueError:
                    pass

        rows.append(row)

    fieldnames = ["structure", "status", "dft_gap_ev", "direct", "alignn_gap_ev",
                  "mp_reference_gap_ev", "dft_minus_alignn", "error"]
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    n_ok = sum(1 for r in rows if r["status"] == "ok")
    print(f"{n_ok}/{len(rows)} structures completed successfully.")
    print(f"Written to {args.out}")


if __name__ == "__main__":
    main()
