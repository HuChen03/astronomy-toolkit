# GrGadget fork 编译（meson 路径，唯一可行）

来源：`sources/Gadget4/meson.build`、`meson_options.txt`、实测（2026-09-10）。

## 为什么不用官方 GNU Make 流程

官方流程（`Config.sh` + `Makefile.systype` + `make DIR=examples/xxx`）在本 fork **已损坏**（实测）：
1. 源码被重构进 `gadget/src/`，但 `Makefile` 仍引用旧路径（`src/io/parameters.cc` 等 ~20 个文件不存在）；
2. `Makefile` 第 103 行调 `bash git_version.sh`，但脚本已移到 `buildsystem/` 且需要第 3 个参数（模板文件），`SYSTYPE=Generic-gcc` 的库路径假设本地自编译库；
3. `Template-Config.sh` 新增 `IDS_32BIT/48/64BIT` 但 `documentation/04_config-options.md` 未记录，触发 config.check 失败（本仓库已在本地补文档修复，见「已做修改」）。

**结论：该 fork 以 meson 为维护构建路径，必须走 meson。** 官方文档 `documentation/02_running.md` 的 Make 流程不适用于本 fork。

## meson 构建步骤（实测命令）

依赖（Ubuntu 22.04 包名）：`meson ninja-build pkg-config libopenmpi-dev libfftw3-dev libgsl-dev libhdf5-openmpi-dev libchealpix-dev libboost-mpi-dev libboost-serialization-dev libboost-test-dev`（hwloc 可选）。

meson.build **无条件**链接 LATfield2 与 gevolution（即使跑纯牛顿算例），以 subproject 方式提供（仓库不带 .wrap 文件，须手动放入）：

```bash
cd sources/Gadget4
git clone --depth 1 https://github.com/daverio/LATfield2 subprojects/LATfield2
git clone --depth 1 https://github.com/gevolution-code/gevolution-1.2 subprojects/gevolution-1.2
# 注意名字必须叫 LATfield2 和 gevolution-1.2（meson.build 的 fallback 名）
meson setup build-dml50 -Dconfig_file=examples/DM-L50-N128/Config.sh
ninja -C build-dml50        # 生成 build-dml50/Gadget4
```

- `-Dconfig_file=` 指定 Config.sh；不指定则用 build 目录下的 `Config.sh`。
- 编译期配置检查脚本（buildsystem/check.py）在 meson 路径同样运行，Config.sh 拼写错误会在编译期报出。
- GR 功能：在 Config.sh 中加 `GEVOLUTION_PM`/`GEVOLUTION_GR` 宏启用（未在文档中记录，依据论文 arXiv:2301.11854 与源码，**未官方核实**）。

## 已做修改（本地，供复现）

- `git_version.sh -> buildsystem/git_version.sh` 符号链接（仅 GNU Make 路径需要；meson 路径不需要）。
- `documentation/04_config-options.md` 补了 `IDS_32BIT/48/64BIT` 三个条目（仅 GNU Make 的 config.check 需要）。

## 版本固定

二进制构建后，把 `git rev-parse HEAD`（Gadget4、LATfield2、gevolution-1.2 三个仓库）与 Config.sh 副本存入运行目录。
