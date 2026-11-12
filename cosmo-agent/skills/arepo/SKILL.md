---
name: arepo
description: 运行 Arepo 公开版（移动网格 Voronoi 流体 + N-body 宇宙学模拟）：编译（Config.sh/SYSTYPE）、参数文件、MPI/Slurm 提交、restart、FOF/Subfind 后处理、输出检查。当任务涉及 Arepo、moving mesh、宇宙学流体模拟时使用。
metadata:
  software: Arepo (public version)
  version: "gitlab.mpcdf.mpg.de/vrs/arepo；本地镜像 dnelson86/arepo @ d924fb3 (2020-01-01)"
  source: https://arepo-code.org/getting-started
---

# Arepo（公开版）

## 适用任务

移动网格（准拉格朗日 Voronoi）流体动力学 + TreePM 引力的宇宙学/星系模拟；理想 MHD、辐射冷却、Springel & Hernquist 恒星形成、zoom 模拟、1D/2D 测试算例。

**前提更正**：Arepo 公开版（GPLv3）可直接 `git clone https://gitlab.mpcdf.mpg.de/vrs/arepo`（镜像 github.com/dnelson86/arepo）；需要申请的只是开发版。本 Skill 针对公开版。

## 功能导航

| 任务 | 参考 |
|---|---|
| 编译（Config.sh + SYSTYPE + make） | `references/building.md` |
| 运行、restart flag、优雅中断、自动重提交 | `references/running.md` |
| 参数文件类别（与 GADGET-4 同构 + 移动网格专属） | `references/parameters.md` |

自带 examples（`sources/arepo/examples/`）：`cosmo_box_gravity_only_3d`、`cosmo_box_star_formation_3d`、`cosmo_zoom_gravity_only_3d`、`galaxy_merger_star_formation_3d`、`isolated_galaxy_collisionless_3d`（**IC 随仓库提供，最小免下载算例**）、`gresho_2d`、`mhd_shocktube_1d`、`noh_2d` 等。批量验证：`sh test.sh`。

## 标准流程

1. 选最接近的 example：`cp -r examples/<x> <run_dir>`；按其 `create.py` 生成/准备 IC（部分例子会下载第三方 IC 工具）。
2. 编译：`make CONFIG=<run_dir>/Config.sh BUILD_DIR=... EXEC=...`（SYSTYPE 选择编译器/库路径模板）。
3. 运行：`mpirun -np N ./Arepo param.txt`；Slurm 模板 `assets/job.slurm`。
4. 成功判定：`check.py`（example 自带）或 `scripts/check_arepo_run.py <run_dir>`（查 output/snapdir、energy.txt、日志尾部）。
5. restart：`./Arepo param.txt 1`（同 rank 数）；`touch stop` 优雅中断；`ResubmitOn 1` + `ResubmitCommand` 自动重提交。

## 注意

- 公开版**纯 MPI**（文档明确；无 OpenMP）。MPI ≥ 2.0、GSL 必需；FFTW3 仅 `PMGRID`；HDF5（`HAVE_HDF5`，SnapFormat 3）强烈推荐。
- 输出 snapshot 与 Gadget 格式兼容（SnapFormat 1/2/3）；FOF/Subfind 目录格式与 Gadget 一致。
- 开发版高级物理（TNG 反馈、宇宙线等）不在公开版；差异清单见 userguide "Differences to the development Version"（本仓库未逐条核实）。
- 构建时 `check.py` 会校验 Config.sh 宏拼写；可执行名 `Arepo`。
