#!/usr/bin/env python3
"""
Standalone uniqueness checker for a directory of .res files.

Uses matador's PDF (pair distribution function / RDF) fingerprint to
identify duplicate/near-duplicate structures, without doing any hull
plotting.

Usage:
    python check_uniqueness.py <path_or_dir> [<path_or_dir> ...] [--sim-tol 0.1] [--sim-hist]
"""

import argparse
import glob
import os
import re
from collections import Counter, defaultdict

from matador.scrapers import res2dict
from matador.fingerprints import get_uniq_cursor
import matador.utils.cursor_utils as cu


def apply_provenance_patch():
    """
    Patch get_guess_doc_provenance to recognise FUSE (pso/rand/tpe filename
    patterns) and MatterGen (_mat_ filename pattern) sources, and merge OQMD
    into MP. Mirrors the provenance-patching half of patched_utils.apply_patch(),
    without the plotting-related monkey-patches (not needed for this script).
    """
    original_provenance = cu.get_guess_doc_provenance

    def patched_provenance(sources, icsd=None):
        if isinstance(sources, str):
            sources = [sources]
        fname = ''.join(s.split('/')[-1] for s in sources).lower()
        if any(s in fname for s in ['pso', 'rand', 'tpe']):
            return 'FUSE'
        if '_mat_' in fname:
            return 'MatterGen'
        result = original_provenance(sources, icsd=icsd)
        if result == 'OQMD':
            return 'MP'
        return result

    cu.get_guess_doc_provenance = patched_provenance


def plot_similarity_histogram(sim_matrix, out_path, sim_tol):
    """
    Print summary stats and save a histogram of pairwise PDF similarity
    distances. Handles a few possible return shapes for sim_matrix since
    matador's docs are vague on the exact type: scipy sparse matrix, dense
    2D ndarray, or a 1D condensed-distance-style array.
    """
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")  # headless-safe (HPC login nodes etc.)
    import matplotlib.pyplot as plt

    print(f"[debug] sim_matrix type: {type(sim_matrix)}")

    try:
        from scipy import sparse
        is_sparse = sparse.issparse(sim_matrix)
    except ImportError:
        is_sparse = False

    vals = None

    if is_sparse:
        coo = sim_matrix.tocoo()
        mask = coo.row < coo.col  # upper triangle, no diagonal
        vals = coo.data[mask]
    else:
        arr = np.asarray(sim_matrix)
        print(f"[debug] sim_matrix ndim: {arr.ndim}, shape: {arr.shape}")

        if arr.ndim == 2:
            iu = np.triu_indices_from(arr, k=1)
            vals = arr[iu]
            # NOTE: this drops explicit zero-distance duplicate pairs along
            # with unset/never-compared entries, since a dense matrix likely
            # uses 0 for both. Sparse input avoids this ambiguity.
            vals = vals[vals != 0]
        elif arr.ndim == 1:
            # Likely already a condensed (upper-triangle-only) form, e.g.
            # scipy.spatial.distance style output -- use directly.
            vals = arr[arr != 0]
        else:
            print(f"Could not interpret sim_matrix (ndim={arr.ndim}); "
                  "skipping histogram. Run with --debug and inspect the "
                  "get_uniq_cursor return value directly if you need this.\n")
            return

    if vals is None or len(vals) == 0:
        print("No pairwise similarity values found to plot "
              "(likely no same-stoichiometry pairs were compared).\n")
        return

    print("-" * 60)
    print("PAIRWISE SIMILARITY DISTRIBUTION (compared pairs only)")
    print("-" * 60)
    print(f"  n compared pairs: {len(vals)}")
    print(f"  min:    {vals.min():.4f}")
    print(f"  max:    {vals.max():.4f}")
    print(f"  mean:   {vals.mean():.4f}")
    print(f"  median: {np.median(vals):.4f}")
    for p in (5, 25, 50, 75, 95):
        print(f"  p{p}:    {np.percentile(vals, p):.4f}")
    print()

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(vals, bins=50, color="#2196F3", edgecolor="k", alpha=0.7)
    ax.axvline(sim_tol, color="red", linestyle="--", label=f"sim_tol = {sim_tol}")
    ax.set_xlabel("Pairwise PDF similarity distance")
    ax.set_ylabel("Count")
    ax.set_title("Pairwise structural similarity distribution")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"Saved histogram to {out_path}")
    print("(Move sim_tol left/right along this plot to judge whether a "
          "different cutoff would meaningfully change the unique count.)\n")


def n_distinct_elements(doc):
    """
    Return the number of distinct elements in a doc, trying stoichiometry
    first and falling back to atom_types (both standard matador doc fields).
    """
    stoich = doc.get("stoichiometry")
    if stoich:
        return len(stoich)
    atom_types = doc.get("atom_types")
    if atom_types:
        return len(set(atom_types))
    return None


def first_source_basename(doc):
    src = doc.get("source", doc.source)
    src = src[0] if isinstance(src, list) else src
    return os.path.basename(str(src))


def get_mattergen_run(doc):
    """
    Extract the MatterGen run number from a filename like:
        In3GaZnO3_Mat_R13_g483.res  ->  13
    Returns None if the pattern isn't found (e.g. not a MatterGen structure).
    """
    fname = first_source_basename(doc)
    match = re.search(r"_[Rr](\d+)_", fname)
    if match:
        return int(match.group(1))
    return None


def analyse_mattergen_runs(cursor, unique_inds, dupe_dict):
    """
    Report uniqueness broken down by MatterGen run number, and how many
    genuinely NEW (never seen in an earlier run) unique structures each
    run contributes -- i.e. whether later runs are still finding new
    structures or just rediscovering earlier ones.
    """
    runs = {i: get_mattergen_run(doc) for i, doc in enumerate(cursor)}
    n_no_run = sum(1 for r in runs.values() if r is None)

    if n_no_run == len(cursor):
        print("--mattergen-runs: no filenames matched the '_R<N>_' pattern "
              "(e.g. '..._Mat_R13_g483.res') -- skipping run analysis.\n")
        return

    if n_no_run:
        print(f"--mattergen-runs: {n_no_run}/{len(cursor)} structures had no "
              "parseable run number and are excluded from this analysis.\n")

    # Build clusters: each representative index + its duplicates.
    # (dupe_dict is keyed by every representative in unique_inds, values are
    # lists of duplicate indices, possibly empty for singletons.)
    clusters = []
    seen = set()
    for key, dupes in dupe_dict.items():
        members = [key] + list(dupes)
        clusters.append(members)
        seen.update(members)
    # Catch any unique indices not present as dupe_dict keys, just in case.
    for i in unique_inds:
        if i not in seen:
            clusters.append([i])

    # Raw per-run totals
    per_run_total = Counter()
    for i, r in runs.items():
        if r is not None:
            per_run_total[r] += 1

    # Discovery run per cluster = earliest run number among its members
    # (structures with no parseable run are ignored when picking discovery run)
    discovery_run_counts = Counter()
    for members in clusters:
        member_runs = [runs[i] for i in members if runs[i] is not None]
        if not member_runs:
            continue
        discovery_run_counts[min(member_runs)] += 1

    sorted_runs = sorted(per_run_total)

    print("=" * 60)
    print("MATTERGEN RUN BREAKDOWN")
    print("=" * 60)
    print(f"{'Run':>5}  {'Total':>7}  {'New unique':>11}  {'Yield %':>8}  {'Cumulative unique':>18}")
    cumulative = 0
    for r in sorted_runs:
        new_unique = discovery_run_counts.get(r, 0)
        cumulative += new_unique
        total = per_run_total[r]
        yield_pct = 100 * new_unique / total if total else 0
        print(f"{r:>5}  {total:>7}  {new_unique:>11}  {yield_pct:>7.1f}%  {cumulative:>18}")
    print()
    print(f"Total structures across {len(sorted_runs)} runs: {sum(per_run_total.values())}")
    print(f"Total unique structures (all runs combined):     {cumulative}")
    print("(\"New unique\" = structures whose earliest-seen duplicate-cluster "
          "member is from that run -- i.e. genuinely new finds, not just "
          "the count of files in that run that happen to be representatives.")
    print(" \"Yield %\" = New unique / Total for that run -- use this, not the "
          "raw New unique count, to compare runs with different batch sizes.)\n")


def main():
    apply_provenance_patch()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inpf", nargs="+",
                         help="One or more directories of .res files and/or glob patterns. "
                              "Files are combined and de-duplicated across all inputs.")
    parser.add_argument("--sim-tol", type=float, default=0.1,
                         help="PDF similarity tolerance (default: 0.1)")
    parser.add_argument("--energy-tol", type=float, default=0.01,
                         help="Energy tolerance (default: 0.01)")
    parser.add_argument("--diff-stoich", action="store_true",
                         help="Allow comparisons across different stoichiometries "
                              "(default: enforce same stoichiometry)")
    parser.add_argument("--debug", action="store_true",
                         help="Print timings and similarity values from get_uniq_cursor")
    parser.add_argument("--sim-hist", action="store_true",
                         help="Print summary stats and save a histogram of pairwise "
                              "similarity distances (requires scipy + matplotlib)")
    parser.add_argument("--sim-hist-out", default="sim_hist.png",
                         help="Output path for the similarity histogram PNG "
                              "(default: sim_hist.png)")
    parser.add_argument("--quaternary-only", action="store_true",
                         help="Only include structures with exactly 4 distinct "
                              "elements (e.g. In-Ga-Zn-O) before running the "
                              "uniqueness check")
    parser.add_argument("--mattergen-runs", action="store_true",
                         help="Break down uniqueness by MatterGen run number, "
                              "parsed from filenames like '..._Mat_R13_g483.res', "
                              "and show how many new unique structures each run "
                              "contributes")
    parser.add_argument("--show-duplicate-groups", action="store_true",
                         help="Print the full list of duplicate groups (kept off "
                              "by default -- can be a lot of text for large batches)")
    args = parser.parse_args()

    # Resolve inputs: each entry can be a directory (-> *.res) or a glob pattern.
    # Combine and de-duplicate across all of them.
    res_files = set()
    for inpf in args.inpf:
        pattern = os.path.join(inpf, "*.res") if os.path.isdir(inpf) else inpf
        matches = glob.glob(pattern)
        if not matches:
            print(f"WARNING: no .res files matched: {pattern}")
        res_files.update(matches)
    res_files = sorted(res_files)

    if not res_files:
        raise SystemExit("No .res files found across any of the given paths.")

    print(f"Found {len(res_files)} .res files across {len(args.inpf)} input path(s)\n")

    cursor, failures = res2dict(res_files, as_model=True)
    if failures:
        print(f"WARNING: {len(failures)} files failed to parse:")
        for f in failures:
            print(f"  - {f}")
        print()

    print(f"Loaded {len(cursor)} structures successfully.\n")

    if args.quaternary_only:
        n_before = len(cursor)
        filtered_cursor = []
        n_unknown = 0
        for doc in cursor:
            n_elem = n_distinct_elements(doc)
            if n_elem is None:
                n_unknown += 1
                continue
            if n_elem == 4:
                filtered_cursor.append(doc)
        cursor = filtered_cursor
        print(f"--quaternary-only: kept {len(cursor)}/{n_before} structures "
              f"with exactly 4 distinct elements")
        if n_unknown:
            print(f"  ({n_unknown} structures skipped: could not determine "
                  "element count from stoichiometry/atom_types)")
        print()
        if not cursor:
            raise SystemExit("No quaternary structures remain after filtering.")

    unique_inds, dupe_dict, fingerprints, sim_matrix = get_uniq_cursor(
        cursor,
        sim_tol=args.sim_tol,
        energy_tol=args.energy_tol,
        enforce_same_stoich=not args.diff_stoich,
        debug=args.debug,
    )

    n_total = len(cursor)
    n_unique = len(unique_inds)
    n_dupes = n_total - n_unique

    print("=" * 60)
    print("UNIQUENESS SUMMARY  (report only -- no files are moved, copied, or deleted)")
    print("=" * 60)
    print(f"Total structures loaded:        {n_total}")
    print(f"Would be classed as unique:     {n_unique}")
    print(f"Would be flagged as duplicates: {n_dupes}  ({100 * n_dupes / n_total:.1f}%)")
    print(f"sim_tol:                        {args.sim_tol}")
    print(f"energy_tol:                     {args.energy_tol}")
    print(f"enforce_same_stoich:            {not args.diff_stoich}")
    print()

    # Provenance breakdown: before and after filtering
    def provenance_of(doc):
        try:
            return cu.get_guess_doc_provenance(doc.get("source", doc.source))
        except Exception:
            return "UNKNOWN"

    all_provenance = Counter(provenance_of(doc) for doc in cursor)
    unique_docs = [cursor[i] for i in unique_inds]
    unique_provenance = Counter(provenance_of(doc) for doc in unique_docs)

    print("-" * 60)
    print("BY PROVENANCE (source -> total / would-keep-as-unique / % unique)")
    print("-" * 60)
    for source in sorted(all_provenance):
        total = all_provenance[source]
        kept = unique_provenance.get(source, 0)
        pct = 100 * kept / total if total else 0
        print(f"  {source:12s} total={total:5d}  unique={kept:5d}  unique%={pct:5.1f}%")
    print()

    if args.sim_hist:
        plot_similarity_histogram(sim_matrix, args.sim_hist_out, args.sim_tol)

    if args.mattergen_runs:
        analyse_mattergen_runs(cursor, unique_inds, dupe_dict)

    if args.show_duplicate_groups:
        print("-" * 60)
        print("DUPLICATE GROUPS (first 20 shown; representative structure is the one")
        print("get_uniq_cursor's hierarchy would pick if filtering were applied)")
        print("-" * 60)
        shown = 0
        for key, dupes in dupe_dict.items():
            if not dupes:
                continue
            kept_src = first_source_basename(cursor[key])
            dupe_srcs = [first_source_basename(cursor[d]) for d in dupes]
            print(f"  Representative: {kept_src}")
            for ds in dupe_srcs:
                print(f"    -> duplicate:  {ds}")
            shown += 1
            if shown >= 20:
                remaining = sum(1 for v in dupe_dict.values() if v) - shown
                if remaining > 0:
                    print(f"  ... and {remaining} more duplicate groups not shown")
                break
        if shown == 0:
            print("  (no duplicate groups found)")


if __name__ == "__main__":
    main()
