---
name: gadget4
description: 运行 GADGET-4（GrGadget 分支，含相对论 PM 扩展）宇宙学 N-body/SPH 模拟：编译（Config.sh/Makefile.systype 或 meson）、参数文件准备、MPI/Slurm 提交、restart 续跑、FOF/SUBFIND 等内建后处理、输出检查。当任务涉及 GADGET-4、GrGadget、宇宙学模拟、TreePM、N-body、SPH 时使用。
metadata:
  software: GADGET-4 (GrGadget fork)
  version: "master d0e3eee (2022-09-21)"
  source: https://github.com/GrGadget/Gadget4
---

# GADGET-4（GrGadget 分支）

## 适用任务

宇宙学/星系尺度 N-body 与 SPH 流体模拟、初始条件生成（内建 N-GenIC/2LPT）、FOF/SUBFIND、功率谱、光锥、并合树。本 Skill 针对 **GrGadget fork**（arXiv:2301.11854），它与官方 GADGET-4 的关系见 `references/gr-fork.md`——**不要用官方版的构建说明直接套这个 fork**（fork 的 GNU Make 路径已坏，须用 meson，见 references/building.md）。

## 功能导航（按任务查 references）

| 任务 | 入口 | 参考文件 |
|---|---|---|
| 编译 | meson（推荐，fork 维护）/ 官方 GNU Make（fork 中已损坏） | `references/building.md` |
| 新模拟 | `mpirun -np N ./Gadget4 param.txt`（RestartFlag 0） | `references/running.md` |
| 生成宇宙学 IC | RestartFlag 6，或 Config.sh 开 `NGENIC`+`CREATE_GRID` 在线生成 | `references/running.md` |
| 续跑 | RestartFlag 1（restart 文件，rank 数不变）/ 2（从 snapshot，可变 rank） | `references/running.md` |
| FOF/SUBFIND 后处理 | RestartFlag 3 | `references/running.md` |
| 功率谱 | RestartFlag 4 / 编译 `POWERSPEC_ON_OUTPUT` | `references/running.md` |
| 参数文件 | 全部运行时参数 | `references/parameters.md` |
| 编译选项 | Config.sh 全部宏 | `references/config-options.md` |
| 本 fork 与官方差异 | GR PM、meson、文档缺口 | `references/gr-fork.md` |

## 标准流程

1. 读环境清单确认 `software.gadget4.binary` 已编译且 Config 与任务匹配；否则先编译（编译期选项决定二进制能力，不同算例需要不同二进制）。
2. 每次运行建独立目录（见 cosmo-exec Skill），把参数文件、Config.sh 副本、命令、版本 commit 放进去。
3. 参数文件从 `assets/param-DM-L50-N128.txt`（纯 DM 宇宙学盒子，在线生成 IC，**无需外部输入**）或其他 example 模板改写；格式为「关键字 值」，每个关键字恰好出现一次。
4. 本地小规模（≤几节点核数）用 `exec_run`/`exec_start` 直接 `mpirun -np N ./Gadget4 param.txt`；正式计算写作业脚本走 Slurm（模板 `assets/job.slurm`）。
5. root 或容器环境运行 OpenMPI 需加 `--allow-run-as-root`（或设 `OMPI_ALLOW_RUN_AS_ROOT=1`）。
6. 成功判定：进程退出码 0 **且** 输出目录中出现预期 snapshot（`snapdir_XXX/`）且日志尾部无 ERROR。用 `scripts/check_gadget4_run.py <run_dir>` 检查（会核对 snapshot HDF5 头、energy.txt 等）。

## 执行约定

- 二进制、参数文件、输出目录全部是**服务端路径**；模板从本 Skill 的 assets 读取后经 `file_write` 落到服务端（见 cosmo-exec Skill）。
- GADGET-4 **没有** `--help`/`--version`/dry-run；不带参数运行只打印 RestartFlag 用法。版本以源码 git commit 为准。
- 优雅中断：在 OutputDir 放 `stop` 文件；达到 85% `TimeLimitCPU` 自动写 restart 并退出。
- 多节点运行每节点至少 2 个 MPI rank（1 个为通信 ghost rank）。
