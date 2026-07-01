#!/bin/bash

# Find next available RUNX directory
run_num=1
while [ -d "RUN${run_num}" ]; do
    run_num=$((run_num + 1))
done
target="RUN${run_num}"

echo -n "This will archive the current FUSE calculation to ${target}/ and reset the directory. Are you sure? (y: yes): "
read ans
if [ "$ans" != "y" ]; then
    echo "Nothing is done..."
    exit 1
fi

mkdir -p "${target}"

# Move files
for f in \
    cubes.p \
    hexagonal.p \
    monoclinic.p \
    orthorhombic.p \
    tetragonal.p \
    bondtable.npz \
    current_structure.cif \
    global_minimum.cif \
    output.txt \
    log_file.csv \
    job_timing.txt \
    relax.traj \
    TEST.db \
    slurm-*.out
do
    for matched in $f; do
        [ -e "$matched" ] && mv "$matched" "${target}/"
    done
done

# Move directories
for d in \
    backup \
    restart \
    structures \
    plots \
    gn-boss \
    reference_structures
do
    [ -d "$d" ] && mv "$d" "${target}/"
done

# Copy input files for new run
cp "${target}/mlgen_mace_input.py" .
cp "${target}/submit_FUSE" .

echo "Archived to ${target}/. Ready for new run."
