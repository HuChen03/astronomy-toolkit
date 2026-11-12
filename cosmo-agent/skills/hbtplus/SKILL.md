---
name: hbtplus
description: 用 HBT+ 对模拟快照做 subhalo 识别与 merger tree 构建。当任务涉及 HBT、subhalo finder、halo 追踪、merger tree、SubSnap 输出、对接 GADGET/EAGLE 快照时使用。
metadata:
  software: HBT+
  version: "1.16.2.MPI (Kambrian/HBTplus, MPI-Hydro 分支, commit 6f87ace)"
  source: https://github.com/Kambrian/HBTplus
---

# HBT+

## 适用任务

基于历史追踪的 subhalo finder + merger tree 构建器（Han et al. 2018, MNRAS 474, 604）。输入 = 模拟快照 + 每快照 FoF halo 目录（HBT+ **自身不做 FoF**）；输出 subhalo 目录（SubSnap）与由 `TrackId` 天然构成的 merger tree。

## 运行入口（源码核实）

```
mpirun -np N ./HBT <param.conf> [snapshot_start] [snapshot_end]
```

- 只给 param：跑 `MinSnapshotIndex`（默认 0）到 `MaxSnapshotIndex`。
- 变体二进制：`HBT`（默认）、`HBTdouble`、`HBTi8`（64 位 ID）、`HBT.apostle`（EAGLE）等（Makefile 目标）。
- Slurm 模板：`assets/HBTjob_mpi.slurm`（源码自带）。

## 功能导航

| 任务 | 参考 |
|---|---|
| 参数文件（7 必选 + ~28 可选，含默认值） | `references/config.md` |
| 支持的快照/halo 格式与自定义 IO 接口 | `references/io-formats.md` |
| 编译（Makefile、HDF5/MPI/GSL、编译宏） | `references/building.md` |
| 续跑（从指定 snapshot 起）、输出结构、后处理 HBTReader | `references/running.md` |

## 标准流程

1. 准备 FoF 目录（可用 toolbox 里的串行 FoF 程序，或外部 FoF）。
2. 从 `assets/Example.conf` 改写配置：3 个路径 + SnapshotFileBase + MaxSnapshotIndex + BoxSize + SofteningHalo 必选。
3. 小范围验证应从首帧开始处理连续快照；从 K>0 续跑需要已存在 K-1 的 SrcSnap。不要在空目录直接跑最后一帧来验证追踪链路。
4. 成功判定：stdout 日志无异常退出 + `SubhaloPath/SubSnap_<NNN>.hdf5` 生成；用 `scripts/check_hbt_output.py <SubhaloPath> <snap_index>` 验证 HDF5 结构与 TrackId 字段。
5. 后处理读取：官方 `toolbox/HBTReader.py`（python2 时代代码，python3 需少量适配——**未实测**）。

## 分支选择（重要）

- `MPI-Hydro`（默认分支，6f87ace，v1.16.2.MPI）：reader 支持 gadget/apostle。
- **`MPI-Hydro-G4`（eada82e，tag v1.18.1.MPI-G4）：原生支持 Gadget-4 快照**（`SnapshotFormat gadget4_hdf`，src/io/gadget4_io.cpp）——接 GADGET-4 输出用这个分支。已实测编译通过（本仓库 sources/HBTplus-g4 为 worktree）。
- SWIFT 输出：用后继代码 HBT-HERONS（https://github.com/SWIFTSIM/HBT-HERONS）。

## 注意

- HDF5 ≥1.8 必需；**hdf5-1.12.0 有已知 bug**（超大 subhalo 存盘断言失败），用 1.8 或 ≥1.12.1（源码 `KnownIssues`）。
- 续跑需要前一 snapshot 的 `SrcSnap` 文件保留在 SubhaloPath 下。

## 本项目的 GADGET 对接与树导出

`scripts/prepare_hbt_inputs.py`（项目根目录）为单文件 Gadget 输出建立 reader 要求的路径链接，保留粒子原始排序。
`scripts/export_hbt_tree.py` 导出节点、跨帧连接及 `SinkTrackId`/`SnapshotIndexOfSink` 指定的并合边。
同一 TrackId 的延续与并合事件分开编码；sunk 后保留的孤儿记录不再形成延续边。字段语义以 G4 分支源码为准。
