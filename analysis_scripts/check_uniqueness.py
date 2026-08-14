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
import pickle
import re
import shutil
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


def first_source_path(doc):
    """Full path (not just basename) -- needed to actually locate/copy the file."""
    src = doc.get("source", doc.source)
    src = src[0] if isinstance(src, list) else src
    return str(src)


def export_structures(paths, args, label="unique"):
    """
    Write a text file of structure paths (--unique-list-out) and/or copy the
    actual .res files into a directory (--copy-unique-to), for later use
    (e.g. pulling representative structures into VESTA).
    """
    if not (args.unique_list_out or args.copy_unique_to):
        return
    if not paths:
        print(f"No {label} structures to export.\n")
        return

    if args.unique_list_out:
        with open(args.unique_list_out, "w") as fh:
            fh.write("\n".join(paths) + "\n")
        print(f"Wrote {len(paths)} {label} structure paths to {args.unique_list_out}")

    if args.copy_unique_to:
        os.makedirs(args.copy_unique_to, exist_ok=True)
        n_copied = 0
        n_failed = 0
        for p in paths:
            try:
                shutil.copy2(p, os.path.join(args.copy_unique_to, os.path.basename(p)))
                n_copied += 1
            except Exception as e:
                n_failed += 1
                print(f"  WARNING: failed to copy {p}: {e}")
        print(f"Copied {n_copied}/{len(paths)} {label} structures to {args.copy_unique_to}"
              + (f" ({n_failed} failed)" if n_failed else ""))
    print()


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


def stoich_key(doc):
    """Canonical, hashable stoichiometry key for grouping same-composition structures."""
    stoich = doc.get("stoichiometry")
    if not stoich:
        return None
    try:
        return tuple(sorted((el, round(float(ratio), 6)) for el, ratio in stoich))
    except Exception:
        return None


def load_checkpoint(path):
    if path and os.path.exists(path):
        with open(path, "rb") as fh:
            return pickle.load(fh)
    return {
        "version": 1,
        "processed_sources": set(),           # absolute paths already handled
        "representatives": {},                # stoich_key -> [{"source","run","pdf"}, ...]
        "run_stats": {},                      # run_number -> {"total": int, "new_unique": int}
    }


def save_checkpoint(path, state):
    with open(path, "wb") as fh:
        pickle.dump(state, fh)


def print_checkpoint_summary(state, args):
    total_unique = sum(len(v) for v in state["representatives"].values())
    total_processed = len(state["processed_sources"])
    print("=" * 60)
    print("CUMULATIVE (all checkpointed sessions combined)")
    print("=" * 60)
    print(f"Total structures processed so far: {total_processed}")
    print(f"Total unique structures so far:    {total_unique}")
    print()

    if args.mattergen_runs and state["run_stats"]:
        print("=" * 60)
        print("MATTERGEN RUN BREAKDOWN (cumulative across all checkpointed sessions)")
        print("=" * 60)
        print(f"{'Run':>5}  {'Total':>7}  {'New unique':>11}  {'Yield %':>8}  {'Cumulative unique':>18}")
        cumulative = 0
        for r in sorted(state["run_stats"]):
            stats = state["run_stats"][r]
            cumulative += stats["new_unique"]
            yield_pct = 100 * stats["new_unique"] / stats["total"] if stats["total"] else 0
            print(f"{r:>5}  {stats['total']:>7}  {stats['new_unique']:>11}  "
                  f"{yield_pct:>7.1f}%  {cumulative:>18}")
        print()


def export_checkpoint_representatives(state, res_files, args):
    """
    Resolve checkpointed representatives (stored by basename) back to real
    paths using this invocation's res_files, then export via export_structures.
    Representatives from earlier sessions whose files aren't among THIS
    invocation's input paths can't be resolved and are reported as missing --
    re-run pointing at their directory (in addition to any new ones) to
    include them.
    """
    if not (args.unique_list_out or args.copy_unique_to):
        return
    path_by_basename = {os.path.basename(p): p for p in res_files}
    paths = []
    n_missing = 0
    for reps in state["representatives"].values():
        for rep in reps:
            p = path_by_basename.get(rep["source"])
            if p:
                paths.append(p)
            else:
                n_missing += 1
    if n_missing:
        print(f"NOTE: {n_missing} checkpointed representative(s) aren't among this "
              "invocation's input paths (checkpointed in an earlier session with a "
              "different directory) -- point --inpf at their directory too to "
              "include them in the export.\n")
    export_structures(paths, args, label="unique (checkpointed)")


def run_checkpointed_analysis(res_files, args):
    """
    Incrementally check uniqueness against a persisted checkpoint of
    previously-seen representative structures (PDF fingerprints), so
    re-running after adding new MatterGen runs only fingerprints and
    compares the NEW structures, rather than redoing the full pairwise
    RDF comparison from scratch every time.

    Cost: O(n_new * n_existing_reps_of_same_stoich) instead of O(n_total^2).

    CAVEAT: for the per-run "New unique" bookkeeping to stay meaningful,
    process runs in increasing run-number order. A run added out of order
    (e.g. re-processing run 8 after runs up to 13 are already checkpointed)
    can only be compared against what's checkpointed so far, so it may be
    credited as "new" for structures that a later-numbered-but-earlier-
    processed run already claimed.

    NOT YET SUPPORTED in checkpoint mode: --sim-hist, --show-duplicate-groups,
    --diff-stoich (representatives are always bucketed by exact stoichiometry).

    Matches matador's own get_uniq_cursor logic: a pair is only treated as a
    candidate duplicate if it passes BOTH the energy gate
    (|enthalpy_per_atom_i - enthalpy_per_atom_j| < energy_tol) AND the PDF
    similarity gate (sim_tol). Confirmed against matador's actual source
    (matador/fingerprints/similarity.py) rather than assumed from docs.
    """
    from matador.fingerprints.pdf import PDFFactory

    if args.reset_checkpoint and args.checkpoint and os.path.exists(args.checkpoint):
        os.remove(args.checkpoint)
        print(f"--reset-checkpoint: removed existing checkpoint at {args.checkpoint}\n")

    state = load_checkpoint(args.checkpoint)
    already_processed = state["processed_sources"]

    # Tracked by basename, not absolute path, so moving files between
    # directories (without renaming) doesn't defeat the skip-optimization.
    # Relies on MatterGen filenames already being content-meaningful
    # (formula + run + generation index) and therefore collision-unlikely.
    new_paths = [p for p in res_files if os.path.basename(p) not in already_processed]
    n_skipped = len(res_files) - len(new_paths)

    print(f"Checkpoint: {args.checkpoint}")
    print(f"  {len(already_processed)} structures previously processed")
    print(f"  {n_skipped} of {len(res_files)} input files already checkpointed, skipping")
    print(f"  {len(new_paths)} new files to process this run\n")

    if not new_paths:
        print("Nothing new to process.\n")
        print_checkpoint_summary(state, args)
        export_checkpoint_representatives(state, res_files, args)
        return

    cursor, failures = res2dict(new_paths, as_model=True)
    if failures:
        print(f"WARNING: {len(failures)} new files failed to parse:")
        for f in failures:
            print(f"  - {f}")
        print()
    # Mark every attempted new path as processed (including parse failures)
    # so we don't keep retrying broken files on every future run.
    for p in new_paths:
        state["processed_sources"].add(os.path.basename(p))

    if args.quaternary_only:
        n_before = len(cursor)
        cursor = [doc for doc in cursor if n_distinct_elements(doc) == 4]
        print(f"--quaternary-only: kept {len(cursor)}/{n_before} new structures\n")

    if not cursor:
        print("No new structures remain after filtering.\n")
        save_checkpoint(args.checkpoint, state)
        print_checkpoint_summary(state, args)
        export_checkpoint_representatives(state, res_files, args)
        return

    # Sort by run number (unparseable runs last) so a batch spanning several
    # runs is still processed in a sensible discovery order.
    cursor.sort(key=lambda d: (get_mattergen_run(d) is None, get_mattergen_run(d) or 0))

    print(f"Computing PDF fingerprints for {len(cursor)} new structures...")
    PDFFactory(cursor, debug=args.debug)
    print("Done.\n")

    n_new_unique = 0
    n_new_duplicate = 0

    for doc in cursor:
        source = first_source_basename(doc)
        run = get_mattergen_run(doc)
        key = stoich_key(doc)
        new_pdf = doc.get("pdf")

        is_duplicate = False
        if key is not None and new_pdf is not None:
            new_energy = doc.get("enthalpy_per_atom", 0)
            for rep in state["representatives"].get(key, []):
                # Mirror matador's own get_uniq_cursor: a pair is only a
                # candidate duplicate if it ALSO passes the energy gate,
                # not on PDF similarity alone.
                if abs(rep.get("enthalpy_per_atom", 0) - new_energy) >= args.energy_tol:
                    continue
                try:
                    dist = rep["pdf"].get_sim_distance(new_pdf)
                except Exception:
                    continue
                if dist <= args.sim_tol:
                    is_duplicate = True
                    break

        if is_duplicate:
            n_new_duplicate += 1
        else:
            n_new_unique += 1
            if key is not None:
                state["representatives"].setdefault(key, []).append(
                    {
                        "source": source,
                        "run": run,
                        "pdf": new_pdf,
                        "enthalpy_per_atom": doc.get("enthalpy_per_atom", 0),
                    }
                )

        if run is not None:
            rstats = state["run_stats"].setdefault(run, {"total": 0, "new_unique": 0})
            rstats["total"] += 1
            if not is_duplicate:
                rstats["new_unique"] += 1

    try:
        save_checkpoint(args.checkpoint, state)
        print(f"Checkpoint saved to {args.checkpoint}\n")
    except Exception as e:
        print(f"WARNING: failed to save checkpoint ({e}). PDF fingerprint objects "
              "may contain something unpicklable -- results below are still valid "
              "for this session, but won't persist for next time.\n")

    print("=" * 60)
    print("THIS SESSION")
    print("=" * 60)
    print(f"New structures processed: {len(cursor)}")
    print(f"  New unique:                                    {n_new_unique}")
    print(f"  Duplicates (of existing checkpoint or this batch): {n_new_duplicate}")
    print()

    print_checkpoint_summary(state, args)
    export_checkpoint_representatives(state, res_files, args)


def analyse_self_uniqueness_by_run(cursor, args):
    """
    For each MatterGen run present in the cursor, compute uniqueness
    WITHIN that run only (ignoring every other run and any checkpoint
    history). This isolates each run's intrinsic diversity under its own
    generation settings, with no dependence on processing order or which
    runs happened to be checkpointed first -- unlike --mattergen-runs,
    whose "New unique" figures depend on the order runs were processed in.

    Uses matador's own get_uniq_cursor directly on each run's subgroup, so
    the duplicate-detection logic is identical to the full-batch method
    (same energy_tol + sim_tol AND gate), just scoped to one run at a time.
    """
    runs = defaultdict(list)
    n_no_run = 0
    for doc in cursor:
        r = get_mattergen_run(doc)
        if r is None:
            n_no_run += 1
            continue
        runs[r].append(doc)

    if not runs:
        print("--self-uniqueness-by-run: no filenames matched the '_R<N>_' "
              "pattern -- skipping.\n")
        return

    if n_no_run:
        print(f"--self-uniqueness-by-run: {n_no_run} structures had no "
              "parseable run number and are excluded.\n")

    print("=" * 60)
    print("SELF-UNIQUENESS BY RUN (each run assessed in isolation, no")
    print("dependence on checkpoint history or processing order)")
    print("=" * 60)
    print(f"{'Run':>5}  {'Total':>7}  {'Self-unique':>11}  {'Self-yield %':>12}")
    for r in sorted(runs):
        subgroup = runs[r]
        if len(subgroup) < 2:
            # get_uniq_cursor needs >=1 structure; a lone structure is
            # trivially 100% unique against itself.
            print(f"{r:>5}  {len(subgroup):>7}  {len(subgroup):>11}  {100.0:>11.1f}%")
            continue
        unique_inds, _, _, _ = get_uniq_cursor(
            subgroup,
            sim_tol=args.sim_tol,
            energy_tol=args.energy_tol,
            enforce_same_stoich=not args.diff_stoich,
            debug=False,
        )
        n_total = len(subgroup)
        n_unique = len(unique_inds)
        yield_pct = 100 * n_unique / n_total if n_total else 0
        print(f"{r:>5}  {n_total:>7}  {n_unique:>11}  {yield_pct:>11.1f}%")
    print()
    print("(\"Self-yield %\" = fraction of a run's OWN structures that are RDF-unique")
    print(" from each other, with no reference to any other run. This isolates the")
    print(" effect of that run's generation settings from checkpoint/processing order,")
    print(" unlike the cumulative Yield % in --mattergen-runs.)\n")


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
    parser.add_argument("--checkpoint", default=None,
                         help="Path to a checkpoint file (e.g. uniqueness_checkpoint.pkl). "
                              "If given, only NEW files (not already in the checkpoint) are "
                              "fingerprinted and compared against the checkpointed set, "
                              "instead of redoing the full pairwise comparison every time. "
                              "See run_checkpointed_analysis() docstring for caveats.")
    parser.add_argument("--reset-checkpoint", action="store_true",
                         help="Delete and start the checkpoint fresh instead of loading it")
    parser.add_argument("--self-uniqueness-by-run", action="store_true",
                         help="Assess each MatterGen run's uniqueness in isolation "
                              "(no dependence on other runs, checkpoint history, or "
                              "processing order) -- use this to compare generation "
                              "settings (e.g. diffusion_guidance_factor) cleanly")
    parser.add_argument("--unique-list-out", default=None,
                         help="Write the list of unique/representative structure file "
                              "paths to this text file (one per line)")
    parser.add_argument("--copy-unique-to", default=None,
                         help="Copy unique/representative .res files into this directory "
                              "(created if it doesn't exist) -- handy for pulling a set "
                              "of structures into VESTA/OVITO afterward")
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

    if args.self_uniqueness_by_run:
        # Standalone diagnostic mode: always loads everything fresh and
        # ignores --checkpoint, since the whole point is to be independent
        # of any processing-order/checkpoint-history confound.
        cursor, failures = res2dict(res_files, as_model=True)
        if failures:
            print(f"WARNING: {len(failures)} files failed to parse:")
            for f in failures:
                print(f"  - {f}")
            print()
        print(f"Loaded {len(cursor)} structures successfully.\n")
        if args.quaternary_only:
            n_before = len(cursor)
            cursor = [doc for doc in cursor if n_distinct_elements(doc) == 4]
            print(f"--quaternary-only: kept {len(cursor)}/{n_before} structures\n")
        analyse_self_uniqueness_by_run(cursor, args)
        return

    if args.checkpoint:
        run_checkpointed_analysis(res_files, args)
        return

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

    unique_paths = [first_source_path(cursor[i]) for i in unique_inds]
    export_structures(unique_paths, args, label="unique")

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
