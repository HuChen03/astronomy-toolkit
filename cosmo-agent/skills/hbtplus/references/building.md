# HBT+ 编译

来源：`sources/HBTplus/Makefile`、`Makefile.inc`、KnownIssues、wiki Compile-and-Run。

## 依赖

- C++11 编译器（gcc ≥ 4.8.1；OpenMP 3.1 若启用 OpenMP）
- HDF5 C 库 ≥ 1.8.0（**避开 1.12.0**，见 KnownIssues）
- MPI（MPI 版必需）
- GSL（可选，仅 subhalo 惯性张量特征分解；在 Makefile.inc 取消 GSL 块注释启用，`-DHAS_GSL -lgsl -lgslcblas`）

## 编译

```bash
cd sources/HBTplus
# 编辑 Makefile.inc 指向 HDF5/MPI（或用环境变量覆盖）
make            # -> ./HBT（默认单精度、int32 ID）
make HBTdouble  # 双精度坐标
make HBTi8      # 64 位粒子 ID
```

常用编译宏（加在 CXXFLAGS）：`HBT_INT8`、`HBT_REAL8`、`DM_ONLY`（只处理 DM，省内存）、`SAVE_BINDING_ENERGY`、`HAS_THERMAL_ENERGY`/`UNBIND_WITH_THERMAL_ENERGY`（流体模拟解绑）。

社区 CMake 支持（PR #11，`CMakeLists.txt` 在仓库根）存在，非官方主路径，**未实测**。

## Ubuntu 22.04 实测要点

- `libhdf5-openmpi-dev`（1.10.7）满足要求。
- Makefile.inc 默认路径需按本机 HDF5 安装位置调整（hdf5-openmpi 在 `/usr/include/hdf5/openmpi` 与 `/usr/lib/x86_64-linux-gnu/hdf5/openmpi`）。
