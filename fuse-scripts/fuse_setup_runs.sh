#!/bin/bash
# fuse_setup_runs.sh - Set up and submit FUSE runs for a given composition
# Usage: ./fuse_setup_runs.sh <composition> [source_dir] [--short] [--registry <path>]
# Example: ./fuse_setup_runs.sh In6Ga2ZnO13
#          ./fuse_setup_runs.sh In6Ga2ZnO13 /path/to/source --short --registry /abs/path/to/fuse_registry.csv
set -e

# --- Args ---
COMP="${1:?Usage: $0 <composition> [source_dir] [--short] [--registry <path>]}"
SOURCE_DIR="${2:-$PWD}"
RUN_TYPE="long"
REGISTRY=""

shift 2 2>/dev/null || shift $# 2>/dev/null
while [[ $# -gt 0 ]]; do
    case "$1" in
        --short)    RUN_TYPE="short"; shift ;;
        --registry) REGISTRY="$2";   shift 2 ;;
        *)          echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# --- Parse composition from formula string ---
parse_comp() {
    echo "$1" | python3 -c "
import re, sys
m = re.findall(r'([A-Z][a-z]?)(\d*)', sys.stdin.read())
d = {el: (int(n) if n else 1) for el, n in m if el}
print(\"{'In':%d,'Ga':%d,'Zn':%d,'O':%d}\" % (d['In'],d['Ga'],d['Zn'],d['O']))
"
}

# --- Find next run number from registry ---
get_next_run() {
    local algo="$1"
    local run_type="$2"
    if [[ -z "$REGISTRY" || ! -f "$REGISTRY" ]]; then
        echo 1
        return
    fi
    python3 -c "
import csv, re, sys

registry = '$REGISTRY'
comp     = '$COMP'
algo     = '$algo'
run_type = '$run_type'

max_n = 0
with open(registry) as f:
    for row in csv.DictReader(f):
        if row['stoich'] != comp or row['algo'] != algo or row['type'] != run_type:
            continue
        label = row['run_label_unified']
        n = int(re.sub(r's', '', label))
        if n > max_n:
            max_n = n

print(max_n + 1)
"
}

# --- Compute path relative to registry root ---
get_rel_path() {
    local dir="$1"
    if [[ -n "$REGISTRY" ]]; then
        local registry_root
        registry_root=$(dirname "$(realpath "$REGISTRY")")
        realpath --relative-to="$registry_root" "$dir"
    else
        echo "$dir"
    fi
}

# --- Validate source files exist ---
for f in mlgen_mace_input.py submit_FUSE; do
    if [[ ! -f "$SOURCE_DIR/$f" ]]; then
        echo "Error: '$f' not found in $SOURCE_DIR"
        exit 1
    fi
done

# --- Create parent composition directory if needed ---
if [[ ! -d "$COMP" ]]; then
    mkdir -p "$COMP"
    echo "Created directory: $COMP"

    # Copy and patch mlgen_mace_input.py with composition
    cp "$SOURCE_DIR/mlgen_mace_input.py" "$COMP/"
    cp "$SOURCE_DIR/submit_FUSE" "$COMP/"
    COMP_DICT=$(parse_comp "$COMP")
    sed -i "s/composition={'In':[0-9]*,'Ga':[0-9]*,'Zn':[0-9]*,'O':[0-9]*}/composition=${COMP_DICT}/g" \
        "$COMP/mlgen_mace_input.py"
    echo "Patched composition: ${COMP_DICT}"
else
    echo "Directory $COMP already exists — skipping composition setup"
fi

# --- Build algo dir names from registry ---
declare -A PRIMARY_DIR
declare -A SECONDARY_DIR
declare -A PRIMARY_LABEL
declare -A SECONDARY_LABEL

for algo in tpe rand pso; do
    next=$(get_next_run "$algo" "$RUN_TYPE")
    second=$(( next + 1 ))

    if [[ "$RUN_TYPE" == "short" ]]; then
        PRIMARY_DIR[$algo]="${algo}-s${next}"
        SECONDARY_DIR[$algo]="${algo}-s${second}"
        PRIMARY_LABEL[$algo]="s${next}"
        SECONDARY_LABEL[$algo]="s${second}"
    else
        if [[ $next -eq 1 ]]; then
            PRIMARY_DIR[$algo]="$algo"
        else
            PRIMARY_DIR[$algo]="${algo}-${next}"
        fi
        SECONDARY_DIR[$algo]="${algo}-${second}"
        PRIMARY_LABEL[$algo]="${next}"
        SECONDARY_LABEL[$algo]="${second}"
    fi
done

# --- Create algorithm subdirectories and copy files ---
for algo in tpe rand pso; do
    for dir in "${PRIMARY_DIR[$algo]}" "${SECONDARY_DIR[$algo]}"; do
        if [[ -d "$COMP/$dir" ]]; then
            echo "  WARNING: $COMP/$dir already exists — skipping"
            continue
        fi
        mkdir -p "$COMP/$dir"
        cp "$COMP/mlgen_mace_input.py" "$COMP/$dir/"
        cp "$COMP/submit_FUSE" "$COMP/$dir/"
    done
done
echo "Created subdirectories: $(for a in tpe rand pso; do echo -n "${PRIMARY_DIR[$a]} ${SECONDARY_DIR[$a]} "; done)"

# --- Patch gn_search and submit ---
for algo in tpe rand pso; do
    primary="${PRIMARY_DIR[$algo]}"
    secondary="${SECONDARY_DIR[$algo]}"

    sed -i "s/gn_search='[^']*'/gn_search='${algo}'/" "$COMP/$primary/mlgen_mace_input.py"
    echo "  $primary: patched gn_search='${algo}'"
    cp "$COMP/$primary/mlgen_mace_input.py" "$COMP/$secondary/"
    echo "  $secondary: copied from $primary"

    for dir in "$primary" "$secondary"; do
        job_id=$(cd "$COMP/$dir" && sbatch submit_FUSE | awk '{print $NF}')
        echo "  $dir: submitted job $job_id"

        # Append to registry if provided
        if [[ -n "$REGISTRY" && -f "$REGISTRY" ]]; then
            label="${PRIMARY_LABEL[$algo]}"
            [[ "$dir" == "$secondary" ]] && label="${SECONDARY_LABEL[$algo]}"
            raw_n="${label//s/}"
            rel_path=$(get_rel_path "$PWD/$COMP/$dir")
            echo "${COMP},${algo},${raw_n},${label},${RUN_TYPE},${rel_path},running,${job_id},N/A,N/A,N/A,N/A" >> "$REGISTRY"
            echo "  $dir: appended to registry"
        fi
    done
done

echo ""
echo "All runs submitted for $COMP (type: $RUN_TYPE)"
[[ -n "$REGISTRY" ]] && echo "Registry updated: $REGISTRY"
