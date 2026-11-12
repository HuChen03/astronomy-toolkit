# GADGET-4 运行与 RestartFlag（GrGadget fork 实测）

来源：`sources/Gadget4/src/main/main.cc:195-241`、`documentation/02_running.md`，fork commit d0e3eee。

## 命令行

```
mpirun -np <N> ./Gadget4 <ParameterFile> [RestartFlag] [SnapNum]
```

不带参数运行：打印 RestartFlag 用法后退出（**没有** --help/--version）。

| RestartFlag | 动作 | 备注 |
|---|---|---|
| 0（缺省） | 从 `InitCondFile` 开始新模拟 | 若编译了 `CREATE_GRID`+`NGENIC`，且 RestartFlag=6 会先生成 IC |
| 1 | 从 restart 文件恢复 | **MPI rank 数必须不变**，同机器同编译器 |
| 2 | 从 snapshot 恢复：`Gadget4 param.txt 2 7` | **可变 rank 数**，可跨机器 |
| 3 | 后处理：对指定 snapshot 跑 FOF（+SUBFIND） | 需编译 `FOF`/`SUBFIND` |
| 4 | 计算物质功率谱 | |
| 5 | snapshot 格式转换（ICFormat→SnapFormat） | |
| 6 | 生成宇宙学初始条件（内建 N-GenIC/2LPT） | 需编译 `NGENIC=<n>` |
| 7/8 | 并合树后处理 | 需编译 `MERGERTREE` |
| 9 | I/O 带宽测试 | 用于设定 `MaxFilesWithConcurrentIO` |
| 10/11 | 光锥/最束缚粒子数据按并合树重排 | |

## 中断与续跑

- 优雅中断：在 `OutputDir` 创建名为 `stop` 的文件 → 写完 restart 后退出。
- 自动 checkpoint：运行时间超过 85% `TimeLimitCPU`（秒）时自动写 restart 退出，并留下 `cont` 文件（供自动重提交脚本检测）。
- restart 文件：每 rank 一个 `restart.<rank>`，写新一组前旧组自动改名 `bak-restart.<rank>`。
- 续跑：`mpirun -np N ./Gadget4 param.txt 1`（同 rank 数）；改 rank 数必须从 snapshot 用 flag 2。

## MPI 要点

- 纯 MPI + 节点内共享内存；**多节点时每节点至少 2 个 rank**（每节点 1 个 rank 被留作通信 ghost rank，单节点运行不受此限）。
- rank 数不必是 2 的幂（2 的幂略高效）；单 rank 串行也可以（仍需 MPI 库）。
- 每节点 rank 数 > 64 时需编译 `NUMBER_OF_MPI_LISTENERS_PER_NODE=X`。
- OpenMPI 以 root/容器运行：`mpirun --allow-run-as-root` 或环境变量 `OMPI_ALLOW_RUN_AS_ROOT=1`。

## 成功判定

- stdout 末段出现正常收尾（`Final time` 到达 `TimeMax`、写最终 snapshot），无 `ERROR`/`Fatal`。
- `OutputDir` 出现 `snapdir_XXX/snapshot_XXX.*`（SnapFormat=3 时为 `.hdf5`）。
- 诊断文件：`energy.txt`（能量守恒检查）、`cpu.txt`、`memory.txt`、`timings.txt`、`balance.txt`。
- 用 `scripts/check_gadget4_run.py <run_dir>` 自动核对。

## 资源估算（官方 example job.sh 参照）

- DM-L50-N128：1 节点 × 40 rank、24 h 上限（实际小规模验证可缩小网格/rank）。
- G2-galaxy：16 rank、1 h。
- 内存：`MaxMemSize`（MB/rank）× 每节点 rank 数 ≤ 节点内存；下限由上次运行 `memory.txt` 中 "Largest Allocation Without Generic" 反推。
