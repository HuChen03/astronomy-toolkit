# HBT+ 输入/输出格式

来源：`sources/HBTplus/src/io/`、wiki（https://github.com/Kambrian/HBTplus/wiki）。

## 快照格式（SnapshotFormat）

- `gadget`（默认）：Gadget-2 风格二进制快照。
- `apostle`：EAGLE/APOSTLE（HDF5，需 snapshotlist.txt）。
- `mysnapshot`：自定义接口——在 `src/io/snapshot_io.cpp` 中实现自己的 reader 后编译。

## FoF 目录格式（GroupFileFormat）

- `gadget3_int`（默认）/ `gadget3_long` / `gadget2_int` / `gadget2_long`：Gadget group 目录，int/long 指整型宽度。
- `hbt_group_hdf5`：HBT 自带 FoF 程序的输出。
- `apostle_particle_index`：EAGLE。

## Gadget-4 / SWIFT 支持状态

- **更正（2026-09-13 核实）**：`MPI-Hydro-G4` 分支（tag v1.18.1.MPI-G4）含 `src/io/gadget4_io.cpp`，
  `SnapshotFormat gadget4_hdf` 原生读取 Gadget-4 HDF5 快照；`gadget4_hdf2` 为等价但更慢的变体
  （configs/Example.conf 注释）。接 GADGET-4 请用该分支。
- 该分支的 GroupFileFormat 选项见 `configs/Example.conf`（含 gadget4 group 目录支持）。
- 默认分支（MPI-Hydro）不含 gadget4 reader；SWIFT 输出用 HBT-HERONS。

## 输出

- `SubhaloPath/SubSnap_NNN.hdf5`（及多文件 .0/.1...）：subhalo 属性表；`TrackId` 跨快照不变 → merger tree。
- `SubhaloPath/SrcSnap_NNN.hdf5`：source 粒子信息，**续跑所必需**（删了就只能从更早点重跑）。
- `HBTReader`（toolbox/HBTReader.py）：读 SubSnap、按 TrackId 取 progenitor 树。
