#!/bin/bash
# Arepo Slurm 作业模板。使用前替换 <...>；分区名来自环境清单。
#SBATCH --job-name=arepo-run
#SBATCH --time=24:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=<ranks>
#SBATCH -o %x-%j.out

set -euo pipefail
cd <run_dir>   # 含 param.txt（及 ICs/ 等输入）

mpiexec -np $SLURM_NTASKS <path-to>/Arepo param.txt

# 自动重提交（可选）：在 param.txt 中设 ResubmitOn 1、ResubmitCommand 指向 sbatch 命令
