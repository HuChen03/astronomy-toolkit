---
name: twolptic
description: 用 2LPTIC 生成宇宙学模拟初始条件（2LPT 位移场，Gadget format 1 输出）。当任务涉及 initial conditions、2LPT、Zel'dovich、glass 起点、给 GADGET/Arepo 准备 IC 时使用。
metadata:
  software: 2LPTIC
  version: "2LPTic.tar.gz (官方 tar 包, md5 538127510b8700637636ba3c8f577c0c)"
  source: http://cosmo.nyu.edu/roman/2LPT/
---

# 2LPTIC

## 适用任务

基于二阶 Lagrangian 扰动理论（2LPT）生成 cosmological N-body 初始条件，输出 Gadget format 1 快照（可作为 GADGET-4 的 `InitCondFile`，ICFormat=1）。基于 N-GenIC 修改（Crocce et al. 2006；Scoccimarro 1998）。

## 关键事实（已核实）

- **无官方 git 仓库**：源码为 tar 包 `2LPTic.tar.gz`（http://cosmo.nyu.edu/roman/2LPT/ ，示例包 `run2LPT.tar.gz`）。
- **依赖 FFTW 2.1.5**（不是 FFTW3！）、MPI、GSL；Numerical Recipes 例程随包附带（nrsrc/）。
- 可执行文件 `2LPTic`；运行：`mpirun -np N ./2LPTic <paramfile>`。**root 账户下必须加
  `--allow-run-as-root`**（本机服务端进程即 root，裸 `mpirun` 必被 OpenMPI 拒绝）；环境清单的
  `mpi.notes` 里有这条，但没有环境清单时应默认按 root 场景准备。
- **28 个参数全部必填**（详见 references/parameters.md）。
- 需要一个 **glass 文件**（Gadget format 1，只读 header+POS）。没有真实 glass 时用 `scripts/make_grid_glass.py` 生成 1 粒子 glass + `GlassTileFac=Nsample` 得到规则网格起点。
- 输出：`OutputDir/FileBase.<task>`，Gadget format 1；**后缀是写盘 MPI task 号，不保证连续**（见「运行注意」）。
  成功标志 stdout 打印 `IC's generated.`。
- 编译宏：`NO64BITID`（32 位 ID）、`PRODUCEGAS`（交错产生气体粒子）、`CORRECT_CIC`（仅真 glass 起点需要）、`ONLY_ZA`（退化为一阶）、`MULTICOMPONENTGLASSFILE`、`DIFFERENT_TRANSFER_FUNC`。

## 标准流程

1. 编译：见 `references/building.md`（FFTW 2.1.5 需从源码装，`--enable-mpi --enable-type-prefix`；现代 gcc 需 `-fno-pie` 编译 + `-no-pie` 链接）。
2. 参数文件从 `assets/2LPT-small.param` 改写：Nmesh/Nsample/Box/宇宙学/Redshift/单位制。
3. 生成或准备 glass 文件：`python3 scripts/make_grid_glass.py glass.dat`（客户端读脚本 → file_write 到服务端执行）。
4. `mpirun -np N ./2LPTic 2LPT.param`：**N ≥ `NumFilesWrittenInParallel`** 即可
   （`save.c:18` 的硬性检查；**没有整除要求**）。注意上游报错措辞是反的
   （`Number of processors must be a smaller or equal than 'NumFilesWrittenInParallel'`），别按字面理解。
5. 检查：stdout 含 `IC's generated.`，再用
   `scripts/check_2lptic_output.py <OutputDir> <FileBase> [期望文件数] [期望总粒子数]`。
   退出码 0 不能单独作为成功依据（见「运行注意」里的错误路径返回 0）。
6. 结果可直接作 GADGET-4 输入：`ICFormat 1`，`InitCondFile <OutputDir>/<FileBase>`——填**不带数字后缀**
   的前缀，多文件时 GADGET-4 自己按 `<InitCondFile>.0/.1/...` 查找。

## 运行注意（实测）

- **`OutputDir` 必须先存在**，否则直接 `FatalError`；`GlassFile` / `OutputDir` 的相对路径是相对
  **执行时的 cwd**。经 MCP `exec_run` 执行时默认 cwd 是 allowed_root 而不是运行目录，所以要么显式传
  `cwd`，要么在参数文件里写绝对路径——两边都做最稳。
- **错误路径返回 0**：参数名未知或重复会置 `errorFlag` 然后 `MPI_Finalize(); exit(0)`
  （见 `read_param.c`）。**退出码 0 不代表成功**，必须看 stdout 是否出现 `IC's generated.`。
- **输出文件命名**：`sprintf("%s/%s.%d", OutputDir, FileBase, ThisTask)`（`save.c:69`），只有
  `NumPart > 0` 的 task 才写盘；FFTW2 的 `rfftwnd_mpi_local_sizes` 允许某些 task 的 `Local_nx = 0`，
  因此**序号可能不连续**，且 `header.num_files` = 真正写盘的 task 数，**不等于**
  `NumFilesWrittenInParallel`。检查和枚举一律用 glob `FileBase.*`，不要循环 `0 .. N-1`。
- **未记录的副作用**：还会写 `<OutputDir>/inputspec_<FileBase>.txt`（功率谱表）。基于「目录内容计数」
  或「目录里只有 IC 文件」的检查会踩坑。
- **`scripts/check_2lptic_output.py` 覆盖到哪**：校验头块与结束标记、POS/VEL/ID 三个块的尺寸与结束标记、
  文件长度与块结构自洽、头字段合理性、各文件 `npartTotal` 一致、可选的总粒子数断言。
  它**不**校验粒子数值（位置是否非零、ID 是否唯一）——需要时另行抽样核对。
- **stdout 自带两处误导标签**：`Maximum displacement: ... kpc/h` 的单位实际是 Mpc/h 量级；
  `part-spacing` 用的是 `Box/Nmesh` 而不是粒子平均间距 `Box/Nsample`（`main.c:655-656`）。
  别拿这两个数字做物理合理性自检。

## 注意事项

- 该代码无 `--help`/`--version`；无参数运行直接报参数文件错误。
- 现代替代：monofonIC、MUSIC（如需 PANPHASIA 或更高精度，但不在本 Skill 范围）。
- 与 GADGET-4 内建 NGENIC 的关系：功能重叠；2LPTIC 独立生成 IC 文件，可复用/共享。
