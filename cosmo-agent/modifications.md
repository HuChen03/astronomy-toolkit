# 对上游源码的本地修改记录（cosmo-agent/sources/ 下）

所有修改均为让软件在本环境可编译/可运行的**最小必要调整**，均已验证。各条目附证据。

## Gadget4（GrGadget fork @ d0e3eee）

1. `git_version.sh -> buildsystem/git_version.sh` 符号链接。
   证据：Makefile:103 调 `bash git_version.sh`，脚本在 buildsystem/ 且需第 3 参数（模板）。仅 GNU Make 路径需要；meson 路径用不到。
2. `documentation/04_config-options.md` 补 `IDS_32BIT/48/64BIT` 三条文档。
   证据：Template-Config.sh:104-106 有这三项但文档未记录，make 的 config.check 报错退出。
3. `gadget/meson.build`：gadget 库 dependencies 增加 `mpi,hdf5,gsl,fftw3,latfield,gevolution,healpix,boost`。
   证据：原文件只列 vectorclass/half，编译报 `mpi.h/hdf5.h: No such file or directory`。
4. `meson.build`：增加 `fftw3f` 依赖并链入可执行。
   证据：未设 DOUBLEPRECISION_FFTW 时链接报 `undefined reference to fftwf_destroy_plan`。
5. `src/fof/fof.h`、`src/fof/fof_nearest.cc`：内容包入 `namespace gadget{}`。
   证据：fork 把公共类迁入 namespace gadget（如 setcomm），这两个文件漏迁，报 `expected class-name before '{'`。
6. `src/domain/domain_box.cc`：增加 `#include "../system/system.h"`（get_random_number）。
7. `gadget/src/pm_periodic.cc`：`set_acceleration` 调用处 double→MyFloat 显式转换。
   证据：原代码 `array<double,3>` 直接传给 `array<float,3>` 形参（单精度配置下编译错误）。
8. `src/ngenic/ngenic.cc:658`：`fft(&fft_of_grid[0], ...)` 改为 `fft((fft_real*)fft_of_grid, ...)`（与同文件 FFT_COLUMN_BASED 分支一致）。
9. `src/data/simparticles.h`：`set_acceleration` 写 `GravPM` 的语句按 `PMGRID && PERIODIC && !TREEPM_NOTIMESPLIT` 条件保护（与 particle_data.h:77 的字段定义条件一致）。
10. `subprojects/LATfield2`、`subprojects/gevolution-1.2`：来自 GrGadget 组织的同名 fork 的 master 分支（提供 meson `liblatfield_dep`/`libgevolution_dep`）。注意 meson.build 的 fallback 名要求目录名必须是这两个。

注：以上 3-9 只影响编译；未改动数值算法。完整 FOF 配置（DM-L50-N128 原版）的编译**尚未完全修复**（fof_io.h 等更多 namespace 问题）；当前可运行二进制为去 FOF/POWERSPEC 的最小配置。

## Arepo（dnelson86/arepo @ d924fb3）

1. `Makefile`：新增 `SYSTYPE="CosmoLinux"` 段（mpicc + Ubuntu 系统库路径，HDF5 用 openmpi 变体）。
2. `Makefile`：把作者遗留的无条件 "AREPOVTK" 默认段包进 `ifeq ($(SYSTYPE),"AREPOVTK")`。
   证据：该段在任何 SYSTYPE 下都覆盖库路径，导致 hdf5.h 找不到。

## 2LPTIC（官方 2LPTic.tar.gz）

- 未改源码；构建用 make 命令行变量覆盖（FFTW2 路径、`-fno-pie`/`-no-pie`），见 skills/twolptic/references/building.md。

## HBT+（Kambrian/HBTplus @ 6f87ace）

- 未改源码；构建用 make 命令行变量覆盖 HDF5 路径（hdf5-openmpi）。
