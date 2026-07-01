#!/bin/bash
echo -n "This will clean the current FUSE calculation directory. Are you sure? (y: yes): "
read ans
if [ "$ans" != "y" ]; then
    echo "Nothing is done..."
    exit 1
fi

/bin/rm -f \
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

/bin/rm -rf \
    backup \
    restart \
    structures \
    plots \
    gn-boss \
