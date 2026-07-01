#!/bin/bash
# continue_fuse_run.sh - Set up and submit a continuation of a completed FUSE run
# Usage: ./continue_fuse_run.sh [--dry-run]
# Run from inside the completed calculation directory (e.g. pso/, rand-2/)

set -e

DRY_RUN=false
[[ "${1}" == "--dry-run" ]] && DRY_RUN=true

SOURCE_DIR="$PWD"
ALGO=$(basename "$SOURCE_DIR")
CONT_DIR="${SOURCE_DIR}-cont"

# --- Validate we look like a FUSE run directory ---
if [[ ! -f "$SOURCE_DIR/mlgen_mace_input.py" ]]; then
    echo "Error: mlgen_mace_input.py not found in $SOURCE_DIR"
    echo "Run this script from inside a completed FUSE calculation directory."
    exit 1
fi

# --- Copy directory, excluding slurm output files ---
echo "Copying $ALGO -> $(basename $CONT_DIR) ..."
cp -r "$SOURCE_DIR" "$CONT_DIR"
rm -f "$CONT_DIR"/slurm-*.out

# --- Patch mlgen_mace_input.py ---
sed -i "s/restart=False/restart=True/" "$CONT_DIR/mlgen_mace_input.py"
sed -i "s/clear_previous_structures=True/clear_previous_structures=False/" "$CONT_DIR/mlgen_mace_input.py"

# --- Verify the changes landed ---
echo "Verifying patches:"
grep -E "restart=|clear_previous_structures=" "$CONT_DIR/mlgen_mace_input.py"

# --- Submit ---
if $DRY_RUN; then
    echo "[dry run] would run: sbatch $CONT_DIR/submit_FUSE"
else
    job_id=$(cd "$CONT_DIR" && sbatch submit_FUSE | awk '{print $NF}')
    echo "Submitted job $job_id from $(basename $CONT_DIR)"
fi
