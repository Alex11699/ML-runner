#!/bin/bash
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=128
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=3850
#SBATCH --account=su007-bk
#SBATCH --partition=compute
#SBATCH --time=24:00:00
#SBATCH --job-name=bandgap_worker_origcell
#SBATCH --output=%RUN_ROOT%/_worker_logs/slurm-%j.out
#SBATCH --error=%RUN_ROOT%/_worker_logs/slurm-%j.err

module purge
module load intel/2019b HDF5/1.10.5

export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK}
unset I_MPI_PMI_LIBRARY

ulimit -s unlimited #needed for VASP !!!

path=$HOME/APPS/vasp.6.3.2
exe=vasp_std
APP=$path/$exe

export ASE_VASP_COMMAND="srun $APP"
export VASP_PP_PATH="/home/m/msrbzq/VASP-PPs"
export VDW_KERNEL_PATH="$HOME/APPS/vasp.6.3.2/vdw_kernel.bindat"
# only needed when the config's "functional" is optb88-vdw -- harmless to
# leave set otherwise, same as the regular bandgap templates.

source /home/m/msrbzq/APPS/miniconda3/etc/profile.d/conda.sh
conda activate bandgap-env

cd %CODE_DIR%
mkdir -p %RUN_ROOT%/_worker_logs

# ONE-OFF TEST VARIANT -- calls driver_local_origcell.py (original-cell,
# non-primitivized seekpath k-path), not driver_local.py. Same job-packing
# pattern as submit_worker.sh.template otherwise: no --limit, drains the
# pending pool until empty or walltime runs out; --reclaim-stale-minutes 180
# sweeps up anything left stuck by a worker that hit its own walltime.
python driver_local_origcell.py --structures-dir %STRUCTURES_DIR% --run-root %RUN_ROOT% \
    --config %CONFIG_PATH% \
    --reclaim-stale-minutes 180

# --------------------------------------------------------------------------
# Usage: via launch_workers_origcell.py, not launch_workers.py -- see that
# script's docstring. Point --run-root at something separate from your
# regular bandgap runs (e.g. runs_origcell/).
# --------------------------------------------------------------------------

