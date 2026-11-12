#!/bin/bash
# GADGET-4 (GrGadget) Slurm 作业模板。
# 来源：sources/Gadget4/examples/DM-L50-N128/job.sh（官方模板改写）。
# 使用前替换 <...>；分区名来自环境清单 slurm.partitions。
#SBATCH --job-name=gadget4-dm
#SBATCH --time=24:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=<ranks_per_node>   # 多节点时每节点 >=2（ghost rank）
#SBATCH -o %x-%j.out

set -euo pipefail
cd <run_dir>          # 含 param.txt、outputs.txt 的运行目录

echo "Running on hosts: $SLURM_NODELIST"
echo "ntasks: $SLURM_NTASKS"

# root/容器环境加 --allow-run-as-root，或设 OMPI_ALLOW_RUN_AS_ROOT=1
mpiexec -np $SLURM_NTASKS <path-to>/Gadget4 param.txt

# 可选：运行后自动检查（脚本来自 skills/gadget4/scripts/，需先 file_write 到服务端）
# python3 check_gadget4_run.py <run_dir>
