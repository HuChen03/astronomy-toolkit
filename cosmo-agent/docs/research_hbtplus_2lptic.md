# HBT+ 与 2LPTIC 用户级功能调研报告

调研日期：2026-09-10。调研目标：为 AI Agent 编写调用这两个宇宙学软件的 Skill 文档提供事实依据。

**图例**：每条结论后标注来源。`[本地]` = 本机源码 `sources/HBTplus`（或 /tmp 下下载的官方 2LPTIC 包）；`[URL]` = 网络来源；`[推测]` = 未经一手资料核实。

---

## 一、HBT+ (Hierarchical-Bound-Tracing Plus)

仓库：https://github.com/Kambrian/HBTplus （本地克隆：`sources/HBTplus`，默认分支 `MPI-Hydro`）
本地 commit：`6f87acea5551e52ca6c683ed3e2d1b5394e02705`（2026-04-02, "docs: add LGPLv3 SPDX headers"）
代码内版本号：`HBT_VERSION "1.16.2.MPI"` [本地 `src/config_parser.h:18`]
官方文档 wiki：https://github.com/Kambrian/HBTplus/wiki [已克隆核实，内容见下文]

### 1. 科学任务

- HBT+ 是**基于历史追踪的 subhalo finder + merger tree 构建器**：通过追踪 subhalo 随时间的形成与演化来识别子结构，避免传统算法常见缺陷 [本地 `README.md`; wiki Home]。
- 输入为**模拟快照 + 每快照的 FoF halo 目录**（HBT+ 自身不做 FoF；Hydro 分支的 toolbox 提供一个串行 FoF 程序可先生成） [wiki Compile-and-Run / FoF-halos]。
- 同时输出 subhalo 目录与 merger tree（通过跨快照不变的 `TrackId` 天然构成树） [wiki Outputs]。
- 引用文献：Han et al. 2018 (MNRAS 474, 604)、Han et al. 2012 (MNRAS 427, 2437) [本地 README.md]。

### 2. 支持的快照 / halo 目录格式

本地 MPI-Hydro 分支（`src/io/snapshot_io.cpp`、`config_parser` 与 `configs/Example.conf` 注释核实）：

- `SnapshotFormat`：
  - `gadget`（默认）—— Gadget 二进制格式快照（Gadget-2 风格二进制）；
  - `apostle` —— EAGLE/APOSTLE 模拟（HDF5 快照，需配 `snapshotlist.txt`）；
  - `mysnapshot` —— 用户自定义接口（在 `src/io/snapshot_io.cpp` 中自行实现）。
- `GroupFileFormat`：
  - `gadget3_int`（默认）/ `gadget3_long` / `gadget2_int` / `gadget2_long` —— Gadget group 目录，int/long 指文件中整型宽度；
  - `hbt_group_hdf5` —— HBT 自带 FoF 程序的输出格式；
  - `apostle_particle_index` —— EAGLE 模拟。
- **Gadget-4 与 SWIFT**：本地 MPI-Hydro 分支的 gadget reader 中**未见** Gadget-4 / SWIFT 关键字 [本地 grep `src/io/gadget_io.cpp` 无匹配]。SWIFT 输出由后继代码 **HBT-HERONS**（https://github.com/SWIFTSIM/HBT-HERONS ）支持；HBT-HERONS 是 HBT+ 的更新版本，兼容 SWIFT 输出 [URL: https://github.com/SWIFTSIM/HBT-HERONS ; https://arxiv.org/abs/2502.06932]。Gadget-4 快照直接支持情况：**未核实**（wiki 中另有 `custom_io.cpp`/`my_group_format` 自定义接口可接入任意格式 [wiki FoF-halos]）。

### 3. 运行入口与命令行

- 可执行文件：`HBT`（`make` 默认目标，单精度）。变体：`HBTdouble`（8 字节 int + double）、`HBTi8`（8 字节整型 ID）、`HBT_majormerger_test`、`HBT.apostle`、`HBT.apostle_thermal`、`HBT.nostrip`（不解绑，纯追踪） [本地 `Makefile:5-21`]。
- 用法 [本地 `src/config_parser.cpp:161-183`; wiki Compile-and-Run]：

  ```
  ./HBT  param_file [snapshot_start] [snapshot_end]        # Hydro(OpenMP) 版
  mpirun -np N ./HBT param_file [snapshot_start] [snapshot_end]   # MPI 版
  ```

  - 只给 `param_file`：跑 `MinSnapshotIndex`（默认 0）到 `MaxSnapshotIndex`；
  - 只给 `snapshot_start`：只处理该快照；
  - 两个都给：处理 `[start, end]` 闭区间。
- MPI 用法：MPI 版必须 `mpirun -np N`；OpenMP 在 MPI 版中默认关闭，如需混合并行需在 `Makefile.inc` 取消 `OMPFLAG` 注释重编译 [本地 `HBTjob_mpi.slurm` 注释; wiki]。
- Slurm 示例：`mpirun -np $SLURM_NTASKS ./HBTi8 configs/${SLURM_JOB_NAME}.conf $snapstart $snapend` [本地 `HBTjob_mpi.slurm`]。

### 4. 编译

- 构建系统：手写 Makefile（`Makefile` + `Makefile.inc`）；也有社区贡献的 CMake 支持（PR #11，`CMakeLists.txt` 存在于仓库根目录） [本地; wiki]。
- 依赖 [wiki Compile-and-Run; 本地 `Makefile.inc`]：
  - C++ 编译器，需 C++11（及 OpenMP 3.1，若启用 OpenMP），如 gcc ≥ 4.8.1；
  - **HDF5 C 库 ≥ 1.8.0**（必需；注意 hdf5-1.12.0 有已知 bug，超大 subhalo 存盘会断言失败，用 1.8 或 1.12.1+ [本地 `KnownIssues`]）；
  - **MPI 库**（MPI 版必需，如 OpenMPI/MPICH/IntelMPI）；
  - **GSL（可选）**：仅用于 subhalo 惯性张量的特征分解（输出形状/方向），在 `Makefile.inc` 中取消 GSL 块注释启用（`-DHAS_GSL -lgsl -lgslcblas`）。
- 常用编译宏（加在 `CXXFLAGS`）：`HBT_INT8`（8 字节整型）、`HBT_REAL8`（双精度）、`DM_ONLY`（只处理暗物质粒子，省内存）、`SAVE_BINDING_ENERGY`、`HAS_THERMAL_ENERGY` / `UNBIND_WITH_THERMAL_ENERGY`（热能用能解绑，流体力学模拟用） [wiki; 本地 Makefile.inc 注释]。
- 编译命令：`make`（生成 `HBT`）或 `make HBTdouble` 等。

### 5. 参数文件完整清单

配置文件为纯文本键值对，`#` 或 `[` 之后为注释；大小写敏感；未识别的键会报错退出 [本地 `src/config_parser.cpp:64-74`]。模板见 `configs/Example.conf`；以下以源码 `src/config_parser.h`（默认值）与 `config_parser.cpp` 为准。

**必选参数（7 个，缺一不可，否则报 "entry N missing"）**：

| 参数 | 含义 |
|---|---|
| `SnapshotPath` | 快照文件目录 |
| `HaloPath` | FoF group 文件目录 |
| `SubhaloPath` | subhalo 输出目录（程序会 mkdir） |
| `SnapshotFileBase` | 快照文件名前缀（如 `snap_milli`） |
| `MaxSnapshotIndex` | 最后一个快照的索引 |
| `BoxSize` | 模拟盒子尺寸（与快照 header 做一致性检查，单位见 Units） |
| `SofteningHalo` | 暗物质粒子引力软化长度 |

**可选参数（默认值来自 `src/config_parser.h:82-115`）**：

| 参数 | 默认 | 含义 |
|---|---|---|
| `SnapshotFormat` | `gadget` | 快照格式，见上节 |
| `GroupFileFormat` | `gadget3_int` | halo 目录格式，见上节 |
| `MaxConcurrentIO` | 10 | 同时做 IO 的线程数上限（Example.conf 注释写 16） |
| `MinSnapshotIndex` | 0 | 起始快照索引；跳过早期无 halo 快照时设大 |
| `MinNumPartOfSub` | 20 | subhalo 最少束缚粒子数（低于此值追踪为 orphan） |
| `GroupParticleIdMask` | 0 | 特殊 gadget 格式的粒子 ID 掩码（十六进制读入） |
| `MassInMsunh` | 1e10 | 质量单位（Msun/h） |
| `LengthInMpch` | 1 | 长度单位（Mpc/h） |
| `VelInKmS` | 1 | 速度单位（km/s） |
| `PeriodicBoundaryOn` | true | 周期边界 |
| `SnapshotHasIdBlock` | true | 快照是否含 ID 块（按 ID 排序的无 ID 块快照设为 false） |
| `ParticleIdRankStyle` | false | 性能相关（代码注释：未实现，待移除） |
| `ParticleIdNeedHash` | true | 是否对粒子 ID 建哈希（性能相关） |
| `SnapshotIdUnsigned` | false | 快照 ID 是否为无符号 |
| `SaveSubParticleProperties` | false | 是否保存每个 subhalo 粒子的位置/速度 |
| `MergeTrappedSubhalos` | true | 是否合并轨道上重叠的 subhalo（见 code paper） |
| `SnapshotIdList` | 空 | 显式列出快照编号（用于缺快照或编号不连续）；此时 `MaxSnapshotIndex` 必须等于列表长度-1 |
| `MajorProgenitorMassRatio` | 0.8 | 主祖先判定质量比 |
| `BoundMassPrecision` | 0.995 | 束缚质量精度 |
| `SourceSubRelaxFactor` | 3.0 | source subhalo 弛豫因子 |
| `SubCoreSizeFactor` | 0.25 | coresize = Nbound × 该因子（用于 KineticDistance 检验的中心坐标） |
| `SubCoreSizeMin` | 20 | coresize 下限 |
| `TreeAllocFactor` | 0.8 | 树内存分配因子（2 足够） |
| `TreeNodeOpenAngle` | 0.45 | 树张开角 |
| `TreeMinNumOfCells` | 10 | 树最少 cell 数 |
| `MaxSampleSizeOfPotentialEstimate` | 1000 | 解绑时计算势能用到的最大采样粒子数；0 = 用全部粒子（精确但慢） |
| `RefineMostboundParticle` | true | 采样势能时是否进一步精炼最束缚粒子 |

另外：`SubhaloPath/snapshotlist.txt` 可提供每快照的文件名列表（EAGLE 等文件名复杂时用，可用 `toolbox/CreateSnapshotList.py` 生成） [本地 `config_parser.cpp:113-138`; wiki]。
FoF 程序额外参数（仅 toolbox FoF 用）：`FoFLinkParam`(0.2)、`FoFSizeMin`(20)、`FoFDarkMatterMassFraction`(1.0) [wiki FoF-halos]。

### 6. 输入要求与输出内容

**输入**：
- 快照目录 `SnapshotPath` 下按 `SnapshotFileBase` 命名的快照（gadget 二进制或 HDF5，取决于格式）；halo 目录在 `HaloPath`。文件名中的编号即 SnapshotId（0..MaxSnapshotIndex 或用 SnapshotIdList/snapshotlist.txt 映射）。
- 单位通过 `MassInMsunh/LengthInMpch/VelInKmS` 告知；内部 G 按这些单位推导（`G=43.0071*(MassInMsunh/1e10)/VelInKmS^2/LengthInMpch`） [本地 `config_parser.cpp:98`]。

**输出**（均在 `SubhaloPath` 下，HDF5 格式） [wiki Outputs; 本地 `src/io/subhalo_io.cpp:112-119`]：
- `NNN/SubSnap_NNN.iFile.hdf5`：每个快照的 subhalo 目录（NNN 为 3 位快照索引子目录，iFile 为分文件号）。字段：TrackId、Nbound、Mbound、HostHaloId、Rank、Depth、LastMaxMass、各 SnapshotIndexOf*、RmaxComoving、VmaxPhysical、ComovingMostBoundPosition、PhysicalMostBoundVelocity、SinkTrackId、BoundM200Crit、InertialTensor 等（完整列表见 `src/subhalo.h`）。
- `NNN/SrcSnap_NNN.iFile.hdf5`：source（前身）subhalo 目录，**仅用于续跑重启**，跑完后可删除（只保留最后一个即可）。
- `Parameters.log`：记录版本号与全部参数值。
- `timing.log`：每快照各阶段耗时 [本地 `HBT.cpp:53`]。
- **Merger tree**：无单独树文件——同一 `TrackId` 跨快照即同一演化轨道；`SinkTrackId` 记录并合去向 [wiki Outputs]。

**成功判断依据**：
- 进程正常退出（MPI_Finalize，退出码 0）；
- stdout 中出现阶段性输出，如每快照的 `unbinding...`，启动时 `Reading configuration file ...`、`... run using N mpi tasks` [本地 HBT.cpp]；
- 每个快照生成 `SubhaloPath/NNN/SubSnap_NNN.*.hdf5`；`Parameters.log` 与 `timing.log` 存在并持续追加；
- 出错时报错文本含 `Error`（如 "Error reading SubSnap ... loaded=..."、`unrecognized configuration entry`）[本地 subhalo_io.cpp:171; config_parser.cpp:71]。

### 7. 重启 / 续跑机制

**支持**。命令行指定 `snapshot_start > MinSnapshotIndex` 时，HBT+ 假定上次运行在 `snapshot_start-1` 停止，自动加载 `SrcSnap_(start-1).hdf5` 并从 `snapshot_start` 继续 [wiki Compile-and-Run; 本地 `HBT.cpp:47` `subsnap.Load(world, snapshot_start-1, ... SrcParticles)`]。因此续跑前**必须保留前一快照的 SrcSnap 文件**。

### 8. 后处理工具

- 官方 `toolbox/HBTReader.py`：Python 读取模块。用法：
  ```python
  from HBTReader import HBTReader
  reader = HBTReader('/hbt/output')          # 自动解析输出目录的 Parameters.log
  subs = reader.LoadSubhalos(snapnum)        # -1 表示最后快照；可指定字段或 subindex
  track = reader.GetTrack(trackid)
  ```
  [wiki Outputs; 本地 toolbox/HBTReader.py]
- 输出是标准 HDF5，可用 h5py / HDFView / ViTables 直接读。
- toolbox 下还有 `combineSubSnap.py`（合并分文件）、`SplitSubSnap.py`、`CreateSnapshotList.py`、`analysis/`（C++ 分析模板，如 BranchStat）、`halo_virial`（Hydro 分支，计算 FoF 主 halo 的 SO 质量/半径，需在 HBT 跑完后运行） [本地 toolbox; wiki]。
- 第三方：`swiftascmaps`/HBT-HERONS 生态对 SWIFT 用户更友好 [推测，未深入核实]。

---

## 二、2LPTIC（2LPT initial conditions code）

官方页面：http://cosmo.nyu.edu/roman/2LPT/ （本次调研时可访问；本机 `sources/2lptic` 的 git clone 来源 `github.com/pocco81/2lptic` 已失败/为空——该仓库需要认证或已删除，**不可用**）。
ASCL 登记：ascl:1201.005（作者 Crocce, Pueblas, Scoccimarro）[URL: https://ascl.net/1201.005]。

**本次调研已从官方站下载并核实原始源码包**：`2LPTic.tar.gz`（27.6 KB）与示例运行包 `run2LPT.tar.gz`（/tmp/2lptic_orig 下解包核实）。

### 1. 官方源码包获取

官方页面提供三个下载 [URL: http://cosmo.nyu.edu/roman/2LPT/ ，curl 核实]：

| 文件 | 说明 |
|---|---|
| `2LPTic.tar.gz` | **MPI 并行版（高斯初始条件）**，C 语言，基于 Volker Springel 的 N-GenIC，由 Sebastian Pueblas 并行化。页面注明可跑至 1625³ 粒子 |
| `run2LPT.tar.gz` | 官方示例运行包（LasDamas Carmen 模拟用过）：含 `2lpt_Carmen.param`、`run2LPT.sh`、`2lpt.sh`、`glass1_le`/`glass1_be`（glass 文件，小端/大端）、`input_spectrum_LasDamas.dat`（输入功率谱） |
| `2LPT_PNGnonlocal.tgz` | 带原初非高斯（local/non-local PNG）版本，Marc Manera 开发，也可跑高斯模式 |
| `2LPTic_serial.tar.gz` | **串行版，Fortran77**，需 FFTW 2.1.5；算法见 Scoccimarro 1998 (astro-ph/9711187) 附录 D2 |

镜像情况：知名镜像 `github.com/manodeep/2LPTic`（Manodeep Sinha 维护），在原始代码上做了改进（NR 依赖换成 GSL、INT/64bit ID 溢出检查、可接受 CAMB P(k)、一致粒子 ID），但其 subsample 功能有已知 bug（作者警告 GlassTileFacSampleNumerator/Denom 必须设为 1）[URL: https://github.com/manodeep/2LPTic]。本次核实以**官方原始包**为准。

### 2. 科学任务

用**二阶拉格朗日微扰理论（2LPT）**生成宇宙学 N-body 模拟初始条件（位移场 + 速度场），相比一阶 Zel'dovich 近似可显著压低高阶增长误差导致的瞬态（transients），允许更晚的起始红移 [URL: 官方页面; ascl:1201.005; Crocce, Pueblas & Scoccimarro 2006, astro-ph/0606505]。编译时加 `-DONLY_ZA` 可退化为 ZA。

### 3. 编译

MPI 版（`2LPTic.tar.gz` 内 `Makefile`，已核实）：

- 编译器：MPI C 编译器 `mpicc`（Makefile 中写死了 openmpi-1.2.2 的路径，**必须改**）。
- 依赖：
  - **FFTW 2.1.5**（双精度 MPI 版）：链接 `-ldrfftw_mpi -ldfftw_mpi -ldrfftw -ldfftw`——注意是 **FFTW2 不是 FFTW3**（API 不兼容，fftw3 需自行移植或用 `-DFFTW3` 补丁，原始包不支持）；
  - **GSL**：`-lgsl -lgslcblas`（原始包 Makefile 已含 GSL 路径，示例为 gsl 1.9）；
  - **Numerical Recipes (C)**：所需例程已**随包附带**（`nrsrc/`：qromb、trapzd、polint、nrutil），无需外装；
  - MPI 库（`-lmpi` / `-lmpich`）。
- 编译宏选项（Makefile 中注释列出）：`-DPRODUCEGAS`（由单组分 DM 自动交错产生气体粒子）、`-DMULTICOMPONENTGLASSFILE`、`-DDIFFERENT_TRANSFER_FUNC`、`-DNO64BITID`（原始包默认开启，即 32 位 ID）、`-DCORRECT_CIC`（glass 起点时做 CIC 修正）、`-DONLY_ZA`（只做 ZA 而非 2LPT）。
- 构建：`make` 生成可执行文件 **`2LPTic`**。
- 串行版：Fortran77，依赖 FFTW 2.1.5，与 MPI 版是独立代码 [URL: 官方页面]。

### 4. 参数文件完整清单

以原始包 `read_param.c`（全部 tag，已核实）+ 官方示例 `run2LPT.tar.gz` 内 `2lpt_Carmen.param` 注释为准。参数文件格式：`键 值`，`%` 后为注释。**以下参数全部必须出现**，缺失时报 `Error. I miss a value for tag '...'` [原始包 read_param.c:196-199]：

| 参数 | 含义与单位 |
|---|---|
| `Nmesh` | 计算位移场的 FFT 网格尺寸，须 Nmesh ≥ Nsample |
| `Nsample` | 使用的最大波数，即粒子网格 Nyquist 频率 k_Nyquist = 2π/Box·Nsample/2；通常 Ntot = Nsample³ 为总粒子数 |
| `Box` | 周期盒子边长（按输出单位，典型 Mpc/h） |
| `FileBase` | 输出文件基名 |
| `OutputDir` | 输出目录 |
| `GlassFile` | glass 文件路径（Gadget format 1 二进制；官方包附带的 glass1_le/glass1_be 只含 1 个粒子，配合 GlassTileFac 平铺；已核实 glass1_le 为 284 字节 = header+单粒子坐标） |
| `GlassTileFac` | glass 平铺因子；用单粒子 glass 时设为 = Nsample |
| `Omega` | z=0 总物质密度 Ω_m |
| `OmegaLambda` | z=0 宇宙学常数 Ω_Λ |
| `OmegaBaryon` | z=0 重子密度 Ω_b |
| `OmegaDM_2ndSpecies` | 第二暗物质组分的 Ω（无则 0） |
| `HubbleParam` | 哈勃参数 h |
| `Redshift` | 起始红移（示例 z=49/99） |
| `Sigma8` | 功率谱归一化 σ8 |
| `SphereMode` | 1 = 只取 \|k\|<k_Nyquist 的球内模式；0 = 取 \|k_x\|,\|k_y\|,\|k_z\|<k_Nyquist 的立方体 |
| `WhichSpectrum` | 1 = Eisenstein & Hu 解析谱；2 = 读 FileWithInputSpectrum 的列表谱；其他 = Efstathiou 参数化 |
| `FileWithInputSpectrum` | 列表输入功率谱文件名（WhichSpectrum=2 时用；格式 k [h/cm 按 InputSpectrum 单位], P(k)） |
| `InputSpectrum_UnitLength_in_cm` | 输入谱的长度单位（cm/h），如 3.085678e24（=1 Mpc） |
| `ShapeGamma` | Efstathiou 谱形状参数 Γ（仅 Efstathiou 用） |
| `PrimordialIndex` | 原初谱指数 n_s（可做 tilt） |
| `Seed` | 随机数种子 |
| `NumFilesWrittenInParallel` | 并行写盘的文件数上限；**MPI 进程数必须 ≥ 该值且能整除**（save.c:18-28 核实） |
| `UnitLength_in_cm` | 输出长度单位（cm/h），3.085678e24 = Mpc/h |
| `UnitMass_in_g` | 输出质量单位（g），1.989e43 = 10¹⁰ Msun/h |
| `UnitVelocity_in_cm_per_s` | 输出速度单位（cm/s），1e5 = 1 km/s |
| `WDM_On` | 1 = 启用 WDM 小尺度功率谱平滑 |
| `WDM_Vtherm_On` | 1 = 给 WDM 粒子加随机热速度 |
| `WDM_PartMass_in_kev` | WDM 粒子质量（keV） |

（manodeep 镜像额外增加了 `GlassTileFacSampleNumerator/Denom` 等参数，**不属于原始版本**。）

### 5. 运行方式与输出格式

- 运行（官方示例 `run2LPT.sh`，PBS 作业）：

  ```
  mpirun -np N ./2LPTic 2lpt_Carmen.param
  ```

  N 须满足：N ≥ NumFilesWrittenInParallel 且 N % NumFilesWrittenInParallel == 0 [原始包 save.c]。
- 无命令行帮助；缺参数时打印 `Parameters are missing. Call with <ParameterFile>` [main.c:40-41]。
- 输出 [原始包 save.c 核实]：
  - **Gadget format 1**（经典无块名 Fortran 记录格式，save.c 用 SKIP 哑元写 header/POS/VEL/ID 块）；官方页面明确说明输出为 Gadget 格式；
  - NTask=1 时写单文件 `OutputDir/FileBase`；多进程写 `OutputDir/FileBase.0 ... FileBase.(NTask-1)` 多文件；
  - ID 默认 32 位（原始包 Makefile 默认 `-DNO64BITID`；>2³¹ 粒子须去掉该宏）。

### 6. 成功判断依据

- stdout 末尾打印 `IC's generated.` 与 `Initial scale factor = ...` [原始包 main.c:69-70]；
- 运行中阶段性输出：`start computing displacement fields...`、`Done Zeldovich.`、`Maximum displacement: ... kpc/h, in units of the part-spacing= ...`（可用于合理性检查，位移应远小于粒子间距）；
- `OutputDir/FileBase[.N]` 文件生成且尺寸符合预期（header 256B + 每粒子 3×4B 位置 + 3×4B 速度 + 4B/8B ID + 记录标记）。

### 7. 与 N-GenIC 的关系及常见替代

- 2LPTIC 直接基于 Volker Springel 的 **N-GenIC**（Gadget 的 ZA 初始条件代码）开发，由 Sebastian Pueblas 并行化并替换为 2LPT 位移/速度计算；参数文件格式与 N-GenIC 几乎一致，官方页面建议参考 N-GenIC 文档 [URL: 官方页面; arXiv:2310.07767 指出两代码在初始均匀粒子分布与密度扰动上流程相同，区别在位移/速度用 2LPT 而非 ZA]。
- 常见替代/现代选择：**N-GenIC / Gadget-4 自带 IC**（ZA）、**MUSIC**（多尺度/嵌套网格 IC）、**monofonIC**（现代 2LPT/3LPT IC 生成器，支持 FFTW3、相对论修正等）、**HBT 生态无关**。对纯 2LPT IC，monofonIC 是目前最常用维护良好的替代 [推测性建议，依据社区常识；未逐一核实]。

---

## 三、核实状态汇总

| 事项 | 状态 |
|---|---|
| HBT+ 全部参数清单、命令行、重启机制、输出文件结构 | 本地源码 + 官方 wiki 双重核实 |
| HBT+ 支持格式 gadget/apostle/hbt_group_hdf5 | 源码核实；**Gadget-4/SWIFT 原生支持未核实**（MPI-Hydro 分支无对应 reader；SWIFT 应使用 HBT-HERONS） |
| HBT+ 版本 | 本地 commit 6f87ace（2026-04-02），代码内 1.16.2.MPI |
| 2LPTIC 官方下载链接与包内容 | curl 从 cosmo.nyu.edu 实际下载核实（页面在本环境可访问；通用性未保证） |
| 2LPTIC 参数清单、Makefile、FFTW2 依赖、NR 附带、输出格式、成功输出 | 官方原始包源码核实 |
| 2LPTIC 与 N-GenIC 关系 | 官方页面 + 文献核实 |
| monofonIC/MUSIC 作为替代的建议 | 推测（社区常识，未逐一核实） |
| 本机 `sources/2lptic` | 空仓库（origin pocco81/2lptic 克隆失败，需认证）；不可作为源码依据 |
