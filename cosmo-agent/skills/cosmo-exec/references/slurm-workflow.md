# Slurm 作业工作流（原生 CLI，经 cosmo-exec 执行）

来源：Slurm 官方文档（sbatch/squeue/sacct/scancel man pages，https://slurm.schedmd.com/documentation.html）。
约定：轮询间隔 ≥30 秒；终态以 sacct 为准；成功以软件自身输出为准。

## 1. 作业脚本模板

```bash
#!/bin/bash
#SBATCH -J <jobname>
#SBATCH -p <partition>        # 来自环境清单 slurm.partitions
#SBATCH -N 1                  # 节点数
#SBATCH --ntasks-per-node=40  # MPI ranks
#SBATCH -t 24:00:00
#SBATCH -o %x-%j.out          # stdout+stderr 日志

set -euo pipefail
cd <run_dir>
mpirun -np $SLURM_NTASKS ./<binary> <paramfile>   # 无 srun 习惯时用 mpirun
```

## 2. 提交（可解析输出）

```bash
sbatch --parsable job.sh        # 成功: stdout 打印 "jobID[;cluster]"，退出码 0
```
- 记录 job_id：在 MCP 侧对提交的 exec 记录调用 `run_attach_slurm(run_id, job_id)`。
- **提交响应丢失**：先核查再重提——
  `squeue --me -h -o '%i %j %T'` 和 `sacct -X -P -n --format=JobID,JobName,State,Submit`
  按作业名/提交时间确认是否已在队列，确认没有才重新 sbatch。

## 3. 查询

- 在队列中：`squeue -j <job_id> -h -o '%i %T %M %R'`
  （%T: PD=PENDING, R=RUNNING, CG=COMPLETING）
- 终态（作业结束后从 squeue 消失，**必须**用 sacct）：
  `sacct -j <job_id> -X -P -n --format=JobID,State,ExitCode,Elapsed,Start,End`
  State: COMPLETED / FAILED / CANCELLED / TIMEOUT / OUT_OF_MEMORY；ExitCode 形如 `0:0`（exit:signal）。
- sacct 查不到且 squeue 也没有：作业可能从未提交成功——回到第 2 步核查，**不得视为成功**。

## 4. 等待脚本

`scripts/wait_slurm_job.sh <job_id> [间隔秒=30] [超时秒]`：内置退避轮询，
先 squeue 后 sacct，输出终态。经 MCP 用法：`exec_start` 启动，定期 `exec_output` 查看。

## 5. 取消

`scancel <job_id>`；已结束作业上幂等取消用 `scancel -Q <job_id>`。
默认先发 SIGTERM 给作业清理机会，勿默认 `--signal=KILL`。

## 6. 成功判定

`State=COMPLETED` 且 `ExitCode=0:0` 只是必要条件；还必须用各软件 Skill 的
输出检查脚本验证产物（snapshot 文件、日志成功标志等）。反之 State=FAILED
但软件日志显示正常收尾的情况也存在（如被 stop 文件优雅终止后非零退出），以日志为准。

## 7. 模拟后端（无真实集群时）

环境清单 `slurm.mock_backend` 指向一组同名模拟 CLI（sbatch/squeue/sacct/scancel/sinfo），
行为：立即把作业脚本作为本地后台进程执行，状态存在 `$MOCK_SLURM_STATE`。
用法：`env_extra={"PATH": "<mock_backend>:/usr/bin:/bin", "MOCK_SLURM_STATE": "<state_dir>/mock_slurm"}`。
**仅用于测试提交/查询/取消流程，不代表真实集群调度、排队与资源限制。**
