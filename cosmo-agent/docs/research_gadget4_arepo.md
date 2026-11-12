# GADGET-4（GrGadget 分支）与 Arepo 用户级功能调研

> 调研日期：2026-09-10。用途：为 AI Agent 编写调用这两个宇宙学模拟软件的 Skill 文档提供事实依据。
> 每条结论均标注来源：本地源码（`sources/Gadget4/...`，commit `d0e3eee`）或公开网页。查不到的标注「未核实」。

---

## 一、GADGET-4（GrGadget fork）

### 1.1 版本与来源

- 本地源码：`sources/Gadget4`，仓库 https://github.com/GrGadget/Gadget4，分支 master / fix-lightcones / units / gevolution-pm 均已克隆。
- master HEAD：`d0e3eee` "fixed a bug in snapshot header construction"（2022-09-21，来源：`git log`）。
- **四个分支的内容已全部合入 master**：`git log origin/master..origin/gevolution-pm`、`.../units`、`.../fix-lightcones` 均无额外 commit（来源：git 命令实测）。
- 许可证：GPLv3（`sources/Gadget4/LICENSE`）。
- 方法学论文：Quintana-Miranda 等，"GrGadget: an N-body TreePM relativistic code for cosmological simulations"，[arXiv:2301.11854](https://arxiv.org/abs/2301.11854)（2023）。该 fork 即此论文对应的代码。

### 1.2 与官方 GADGET-4 的关系与差异

官方发布渠道（已核实，[wwwmpa.mpa-garching.mpg.de/gadget4](https://wwwmpa.mpa-garching.mpg.de/gadget4/)）：
- 官方 GADGET-4 现在通过 **MPCDF GitLab 公共仓库**发布：`git clone http://gitlab.mpcdf.mpg.de/vrs/gadget4`。
- 官方论文：Springel, Pakmor, Zier, Reinecke, arXiv:2010.03567（MNRAS 2021）。
- 注意区分：**MP-Gadget 是另一套代码**（Yu Feng 基于 GADGET-2/3 的 fork），与官方 gadget4 无关。

fork 差异（来源：`git log --format='%an'` 统计与代码阅读；fork 基点为官方 master 截至 `8935b95`，2020-11-15，Volker Springel；此后 ~176 个 commit 由 Eduardo Quintana Miranda（署名 Eduardo / Lagrang3）提交）：

1. **Meson 构建系统**：新增 `meson.build` / `meson_options.txt`（项目名 `OpenGadget4`，C++17），代码被重构为若干独立库（`gadget/`、`half/`、`md5/`、`vectorclass/`）；保留了官方 GNU Make 构建方式（`Makefile` + `Template-Makefile.systype` 仍在）。
2. **新增依赖**（`meson.build`）：Boost（mpi、serialization、unit_test_framework）、chealpix（HEALPix）、**LATfield2**、**gevolution（libgevolution）**（后两者带 subproject fallback）、hwloc（可选）。官方版仅需 MPI/GSL/FFTW3/HDF5/hwloc（可选）。
3. **相对论（GR）PM 求解器**（fork 的核心改动）：编译宏 `GEVOLUTION_PM` / `GEVOLUTION_GR`，用 libgevolution 的相对论 PM（Poisson 规范下的度规扰动）替换官方 PM 长程力（`src/pm/pm.h`、`gadget/include/gadget/addons/gevolution-pm.hpp`、`latfield_handler.hpp`）；粒子携带相对论动量（Momentum），时间积分改用动量漂移，`NEWTONIAN_DRIFT` 宏可恢复牛顿漂移；含 GR 力指数截断参数（GR_CUT，后续 commit 有 revert/调整）、相对论 PM 的 CIC 修正、gevolution 功率谱输出。
4. **units 分支**：物理基本常数调整、meson 增加 `config_file` 选项（可指定 Config.sh 路径）、hwloc 可选化、`IMPOSE_PINNING`。
5. **fix-lightcones 分支**：已并入 master，无独立差异。
6. master 顶端修复：snapshot header 构造 bug（`d0e3eee`）。

**文档缺口（重要）**：fork 的 `README.md`、`documentation/`、`Template-Config.sh` 均与官方版基本一致，**完全没有记录 GEVOLUTION_PM / GEVOLUTION_GR 等新选项**（grep 实测无匹配）。GR 功能的权威说明只有论文 arXiv:2301.11854 和源码本身。`GEVOLUTION_PM` 不在 `Template-Config.sh` 中，启用方式（直接在 Config.sh 添加该宏）未经官方文档核实——标注「未核实，推测」。

### 1.3 科学任务清单（来源：`Template-Config.sh`、`documentation/04_config-options.md`、`documentation/03_simtypes.md`、各 examples 的 `Config.sh`）

由 Config.sh 编译期开关选择：

| 任务 | 关键编译选项 | 实证出处 |
|---|---|---|
| 纯引力 N-body（无碰撞） | `SELFGRAVITY`（NTYPES 内无 type-0 气体） | 所有 example Config.sh |
| 宇宙学共动积分 | 参数 `ComovingIntegrationOn 1`（非编译期） | 05_parameterfile.md |
| 周期边界 | `PERIODIC` | DM-L50-N128 等 |
| TreePM 引力 | `PMGRID=<n>`（+`ASMTH`、`RCUT`、`TREEPM_NOTIMESPLIT`） | DM-L50-N128: `PMGRID=384` |
| FMM / 高阶多极 | `FMM`、`MULTIPOLE_ORDER` | 04_config-options.md |
| Zoom 模拟 | `PLACEHIGHRESREGION`、`PM_ZOOM_OPTIMIZED`、`HRPMGRID` | DM-Zoom-Aq-C-5 |
| SPH 流体 | 默认含 type-0 粒子即启用；`PRESSURE_ENTROPY_SPH` 为压强 SPH 变体 | SantaBarbara-PSPH-64 |
| 辐射冷却 | `COOLING`（需 TREECOOL 文件） | CollidingGalaxiesSFR |
| 恒星形成+反馈（Springel & Hernquist 2003 子网格模型） | `STARFORMATION` | CollidingGalaxiesSFR |
| FOF 群寻找 | `FOF`（`FOF_GROUP_MIN_LEN` 等） | DM-L50-N128、DM-Zoom-Aq-C-5 |
| SUBFIND 子结构 | `SUBFIND` | DM-Zoom-Aq-C-5 |
| 内建初始条件生成（N-GenIC，2LPT） | `NGENIC=<n>`、`NGENIC_2LPT`、`CREATE_GRID` | DM-L50-N128 |
| 功率谱 | `POWERSPEC_ON_OUTPUT` / RestartFlag 4 | DM-L50-N128 |
| 光锥输出 | `LIGHTCONE`、`LIGHTCONE_MASSMAPS`、`LIGHTCONE_PARTICLES` | 04/05 文档 |
| 并合树 | `MERGERTREE`（RestartFlag 7/8/10/11） | 02_running.md |
| 外势 | `EXTERNALGRAVITY`、`EXTERNALGRAVITY_STATICHQ`（Hernquist 晕） | 04 文档 |
| 2D/1D SPH 测试 | `TWODIMS`、`ONEDIMS` | 04 文档 |

模拟类型矩阵（牛顿空间/周期箱/共动/TreePM/Zoom 共 10 种组合）见 `documentation/03_simtypes.md`。

### 1.4 运行入口（来源：`src/main/main.cc:195-241`、`documentation/02_running.md`）

可执行文件名 **`Gadget4`**。命令行：

```
mpirun -np <N> ./Gadget4 <ParameterFile> [RestartFlag] [SnapNum/其他参数]
```

不带参数运行会打印 RestartFlag 帮助（main.cc 实测）。RestartFlag 语义：

| Flag | 动作 |
|---|---|
| 0（缺省） | 读 InitCondFile 开始新模拟 |
| 1 | 从 restart 文件恢复（**MPI rank 数不可变**） |
| 2 | 从指定 snapshot 恢复，如 `param.txt 2 7`（**可改 rank 数**，可跨机器/编译器） |
| 3 | 后处理：对指定 snapshot 跑 FOF（+SUBFIND） |
| 4 | 计算物质功率谱 |
| 5 | 转换 snapshot 格式（ICFormat→SnapFormat） |
| 6 | 生成宇宙学初始条件 |
| 7/8 | 后处理并合树（需 `MERGERTREE`） |
| 9 | I/O 带宽测试（定 MaxFilesWithConcurrentIO） |
| 10/11 | 光锥/最束缚粒子数据按并合树重排 |

中断与恢复（02_running.md 核实）：在 OutputDir 下放 `stop` 文件可优雅中断并写 restart；达到 85% `TimeLimitCPU` 自动中断并留 `cont` 文件；旧 restart 自动备份为 `bak-restart.X`。

### 1.5 编译（来源：`documentation/02_running.md`、`Makefile`、`Template-Makefile.systype`、fork 的 `meson.build`）

官方 Make 流程：
1. `cp Template-Config.sh Config.sh`，按需注释/启用选项。
2. `cp Template-Makefile.systype Makefile.systype` 选定 `SYSTYPE`（或设环境变量）；库路径/编译器在 `buildsystem/` 的 stub 中配置。
3. `make -j 8` 生成 `Gadget4`；可用 `make CONFIG=... EXEC=... DIR=examples/xxx` 覆盖。`make build` 跳过符号/文档检查（不推荐）。
4. 构建时 python 脚本会校验 Config.sh 选项拼写及文档完整性（`defines_extra` 豁免）。

依赖（02_running.md 核实）：MPI ≥ 3.0、GSL、FFTW3（TreePM/功率谱/IC 生成时需要）、HDF5（SnapFormat=3 需要，强烈推荐）、hwloc（可选，仅 `IMPOSE_PINNING`）、vectorclass（已随源码附带于 `vectorclass/`）。需 C++ 编译器（官方 ≥ C++11）、GNU Make、Python。
fork 的 meson 路径额外需要：C++17、Boost（mpi/serialization/unit_test_framework）、chealpix、LATfield2、gevolution（meson.build 实测）。

### 1.6 参数文件（来源：`documentation/05_parameterfile.md`、`examples/*/param.txt` 实测）

格式：每行「值 关键字」或「关键字 值」——注意 GADGET-4 惯例是 **关键字在前、值在后**（文档示例：`OutputDir /path`），`%`/`#` 开头为注释；每个关键字必须恰好出现一次（多/少都报错）。类别：

- **文件与格式**：`InitCondFile`、`OutputDir`、`SnapshotFileBase`、`ICFormat`、`SnapFormat`（1/2 二进制，**3=HDF5 推荐**）、`NumFilesPerSnapshot`、`MaxFilesWithConcurrentIO`
- **CPU/内存**：`TimeLimitCPU`（秒，85% 触发自动 checkpoint）、`CpuTimeBetRestartFile`、`MaxMemSize`（每 MPI rank MB）、`FlushCpuTimeDiff`
- **时间跨度**：`TimeBegin`、`TimeMax`（共动时为尺度因子 a）、`ComovingIntegrationOn`、`BoxSize`
- **宇宙学**：`Omega0`、`OmegaLambda`、`OmegaBaryon`、`HubbleParam`、`Hubble`
- **单位制**：`UnitLength_in_cm`（cm/h）、`UnitMass_in_g`、`UnitVelocity_in_cm_per_s`、`GravityConstantInternal`（0=自动）
- **力精度**：`TypeOfOpeningCriterion`、`ErrTolTheta`、`ErrTolForceAcc`、`ErrTolThetaMax`、`ActivePartFracForPMinsteadOfEwald`
- **时间积分**：`MaxSizeTimestep`、`MinSizeTimestep`、`ErrTolIntAccuracy`、`CourantFac`
- **域分解**：`ActivePartFracForNewDomainDecomp`、`TopNodeFactor`
- **输出**：`OutputListOn`、`OutputListFilename`、`TimeOfFirstSnapshot`、`TimeBetSnapshot`（共动时为乘性 ln(a) 间隔）、`TimeBetStatistics`
- **SPH**：`DesNumNgb`、`MaxNumNgbDeviation`、`InitGasTemp`、`ArtBulkViscConst`、`MinEgySpec`
- **软化**：`SofteningClassOfPartTypeX`、`SofteningComovingClassX`、`SofteningMaxPhysClassX`、自适应气体软化三参数
- **SUBFIND**：`DesLinkNgb`
- **N-GenIC**（编译 `NGENIC` 时）：`NSample`、`GridSize`、`PowerSpectrumType`（1=Eisenstein&Hu，2=表，其他=Efstathiou 解析）、`PowerSpectrumFile`、`InputSpectrum_UnitLength_in_cm`、`Sigma8`、`PrimordialIndex`、`ReNormalizeInputSpectrum`、`SphereMode`、`Seed`
- **光锥**：`LightConeDefinitionFile`、`LightConeMassMapsNside` 等
- **冷却/恒星形成**：`MaxSfrTimescale`、`TempClouds`、`TempSupernova`、`FactorEVP`、`FactorSN`、`CritPhysDensity`、`CritOverDensity`、`TreecoolFile`
- **外势**：`A_StaticHQHalo`、`Mass_StaticHQHalo`

### 1.7 自带 examples 与最小可跑算例（来源：`examples/` 目录实测、`documentation/10_examples.md`、`make-examples.sh`）

8 个例子（每个含 `Config.sh`、`param.txt`、`job.sh`）：`DM-L50-N128`、`DM-Zoom-Aq-C-5`、`CollidingGalaxiesSFR`、`SantaBarbara-PSPH-64`、`G2-galaxy`、`G2-gassphere`、`G2-cluster`、`G2-lcdm-gas`。

- **最小可跑算例（无需下载任何 IC）：`DM-L50-N128`**——`CREATE_GRID`+`NGENIC=256`+`NGENIC_2LPT` 启动时在线生成 128³ IC；`PowerSpectrumType 0` 走 Efstathiou 解析谱，目录中无外部功率谱文件也能跑（实测目录仅 Config.sh/job.sh/outputs.txt/param.txt）。编译：`make -j 8 DIR=examples/DM-L50-N128`，运行：`cd examples/DM-L50-N128 && mpiexec -np <N> ./Gadget4 param.txt`。
- `CollidingGalaxiesSFR`：自带 `TREECOOL` 文件，但 IC（星系模型）需另行获取。
- G2-galaxy / G2-gassphere / G2-cluster / G2-lcdm-gas / DM-Zoom-Aq-C-5：IC 需从官网下载 [example_ics.tar（183 MB）](https://wwwmpa.mpa-garching.mpg.de/gadget4/example_ics.tar)。
- 批量编译：`bash make-examples.sh`。

### 1.8 输出、restart、后处理（来源：`documentation/06_snapshotformat.md`、`07_diagnosticfiles.md`、`08_groupfiles.md`、02_running.md）

- snapshot：格式 3 = HDF5（推荐，文件名自动加 `.hdf5`）；多文件时存于 `snapdir_XXX/snapshot_XXX.Y.hdf5`。FOF/SUBFIND 群目录、并合树、光锥在 HDF5 模式下也为 HDF5。
- 诊断日志：`energy.txt`、`cpu.txt`、`memory.txt`（可查 "Largest Allocation Without Generic" 反推最小 MaxMemSize）、`timings.txt`、`balance.txt` 等。
- restart 机制：每 rank 一个 `restart.X` 二进制文件，旧集自动改名 `bak-restart.X`；flag 1 恢复（rank 数不变、同机器同编译器）；flag 2 从 snapshot 恢复（可变 rank 数）。
- 内建后处理：RestartFlag 3（FOF/SUBFIND）、4（功率谱）、5（格式转换）、7/8（并合树）、9（I/O 测试），无需外部工具；G2-galaxy 附 IDL 脚本 `plot_energy.pro` 做能量检查。无官方 Python 后处理包随源码分发（未核实第三方生态）。

### 1.9 MPI 运行与资源估算（来源：02_running.md、main.cc、examples 的 job.sh）

- 纯 MPI + 节点内共享内存混合通信：同节点 rank 间直接访存；多节点时每节点**至少 2 个 rank**（1 个被留作通信 ghost rank，不参与计算）；每节点 rank 数 >64 时需 `NUMBER_OF_MPI_LISTENERS_PER_NODE=X`。
- rank 数不要求 2 的幂（2 的幂略高效）。可单 rank 串行跑（仍需链接 MPI）。
- 资源参照：DM-L50-N128 官方 job.sh 为 1 节点 × 40 rank、24h；G2-galaxy 为 16 rank、1h。内存按 `MaxMemSize`（MB/rank）× 每节点 rank 数 ≤ 节点内存估算；下限由 `memory.txt` 的 "Largest Allocation Without Generic" 反推。
- I/O：大分区上用 RestartFlag 9 测带宽以设定 `MaxFilesWithConcurrentIO`。

---

## 二、Arepo

> **对用户前提的更正（有证据）**：Arepo 自 2019 年起已有**公开版源码**，GPLv3，主仓库 [gitlab.mpcdf.mpg.de/vrs/arepo](https://gitlab.mpcdf.mpg.de/vrs/arepo)（页面明确标注 "Arepo public version ... GNU General Public License v3.0 or later"），GitHub 镜像 [dnelson86/arepo](https://github.com/dnelson86/arepo)。论文：Weinberger, Springel & Pakmor 2020, ApJS 248, 32（[arXiv:1909.04667](https://arxiv.org/abs/1909.04667)）。**需要申请的是开发版（developer version）**；公开版文档亦说明其与开发版有功能差异（userguide 有 "Differences to the development Version" 一节）。
> 本次调研基于公开文档（[Arepo userguide](https://arepo-code.org/wp-content/userguide/index.html)）；下文标注「文档」的结论均来自该 userguide。

### 2.1 获取方式与许可

- 公开版：`git clone` gitlab.mpcdf.mpg.de/vrs/arepo（公开），GPLv3。（来源：GitLab 页面 + arXiv:1909.04667）
- 开发版：需联系作者（Volker Springel 等）申请；公开版文档建议问题通过邮件咨询（[getting-started](https://arepo-code.org/getting-started)："contact us via email"）。

### 2.2 用户功能（来源：userguide [index](https://arepo-code.org/wp-content/userguide/index.html)、[simtypes](https://arepo-code.org/wp-content/userguide/simtypes.html)、running.html）

- **移动网格流体**：非结构 Voronoi 网格，准拉格朗日随流体运动，有限体积求解；理想 MHD（`MHD`）；网格可加/减单元（refinement/derefinement）。
- **引力**：TreePM（`PMGRID`）；牛顿或共动宇宙学背景（参数 `ComovingIntegrationOn`）；外势（NFW/等温球/Hernquist）。
- **宇宙学算例类型**：cosmological volume（gravity-only 或含气）、zoom（`PLACEHIGHRESREGION`+`PM_ZOOM_OPTIMIZED`）、星系并合（`galaxy_merger_star_formation_3d`）、孤立星系、1D/2D 测试（shocktube、gresho、yee、noh 等）、1D 球对称（`ONEDIMS_SPHERICAL`，仅串行）。
- **冷却/恒星形成**：`COOLING`+`USE_SFR`（Springel & Hernquist 2003 模型），运行期开关 `CoolingOn`/`StarformationOn`。
- **并行**：**公开版纯 MPI**（文档原文 "relies exclusively on MPI for its parallelization"，已在 >10000 MPI task 规模测试）。用户提到的 "MPI-OpenMP 混合并行" 在公开版文档中**未见**，标注「未核实/公开版不支持」。
- **配置系统**：与 GADGET-4 同构——`Config.sh`（编译期，生成 `arepoconfig.h`）+ `param.txt`（运行期）；`SYSTYPE`/`Makefile.systype`；`make` 会先跑 `check.py` 校验编译宏拼写。
- **examples**：`examples/` 子目录，`sh test.sh` 批量跑验证算例；单个算例流程（文档实测）：`cp -r examples/<x> run/...` → `python create.py`（生成 IC，部分例子自动下载 MUSIC/N-GenIC 等第三方 IC 工具）→ `make CONFIG=... BUILD_DIR=... EXEC=...` → `mpiexec -np 8 ./Arepo param.txt` → `python check.py` 校验。孤立星系 IC 直接随仓库提供。

### 2.3 编译依赖、运行命令、restart、输出（来源：running.html、parameterfile.html）

- 依赖：MPI ≥ 2.0、GSL（必需）；FFTW3（仅 `PMGRID`）；HDF5（`HAVE_HDF5`，格式 3 需要）；hwloc（`IMPOSE_PINNING`）。C 编译器 ≥ C11 + GNU Make + Python。
- 运行：`mpirun -np 32 ./Arepo param.txt`；可执行名 `Arepo`。
- restart：flag 1 从 restart 文件恢复（rank 数必须相同）；flag 2 从 snapshot 恢复（`./Arepo param.txt 2 7`，不保证二进制一致，不推荐除非不得已）；`touch stop` 优雅中断；`ResubmitOn`/`ResubmitCommand` 支持自动重提交。
- 后处理 flag：3（FOF/Subfind）、6（snapshot 格式转换）、14（输出 Voronoi 网格）、17（流体梯度）、18（引力势）。编号不连续是为与开发版保持一致。
- 参数文件：类别与 GADGET-4 高度一致（InitCondFile、ICFormat/SnapFormat、OutputDir、OutputListOn、TimeBegin/TimeMax、ComovingIntegrationOn、Omega0/OmegaLambda/OmegaBaryon/HubbleParam、单位制、ErrTol*、MaxSizeTimestep、CourantFac、软化 SofteningComovingTypeX 等），另有移动网格专属：`PeriodicBoundariesOn`、网格正则化（`CellMaxAngleFactor`/`CellShapingFactor`/`CellShapingSpeed`）、细化（`RefinementCriterion`/`TargetGasMassFactor`/`MaxVolumeDiff` 等）。
- **输出格式与 Gadget 兼容**：SnapFormat 1/2 即 GADGET 二进制格式，3 = HDF5（事实标准）；FOF/Subfind 目录格式与 Gadget 系列一致（文档明言格式 "identical to the ones in GADGET"）。
- 诊断输出：stdout + `balance.txt`、`cpu.txt`、`domain.txt`、`energy.txt`、`info.txt`、`memory.txt`、`sfr.txt`、`timebins.txt`、`timings.txt`。

### 2.4 验证限制声明

- 本调研完成时本地尚无 Arepo 源码（公开版镜像克隆随后进行）；标注「文档」的结论全部来自公开 userguide 与公开发布论文。
- 公开版不含开发版的高级物理模块（如完整辐射、宇宙线、SMBH 反馈等 IllustrisTNG 物理），具体差异见 userguide "Differences to the development Version"（本次未逐条抓取，标注「未核实」）。
- "MPI-OpenMP 混合"：公开版文档明确纯 MPI；开发版是否有 OpenMP 未核实。

---

## 三、来源汇总

- 本地源码核实：`sources/Gadget4`（GrGadget/Gadget4 @ d0e3eee）——`src/main/main.cc`、`meson.build`、`Template-Config.sh`、`documentation/*.md`、`examples/*/{Config.sh,param.txt,job.sh}`、`make-examples.sh`、git 历史。
- [GADGET-4 官网](https://wwwmpa.mpa-garching.mpg.de/gadget4/)（官方仓库地址、IC 包）
- [arXiv:2301.11854](https://arxiv.org/abs/2301.11854)（GrGadget 论文）
- [arXiv:2010.03567](https://arxiv.org/abs/2010.03567)（GADGET-4 官方论文）
- [Arepo userguide](https://arepo-code.org/wp-content/userguide/index.html)（running/simtypes/parameterfile 等页）
- [gitlab.mpcdf.mpg.de/vrs/arepo](https://gitlab.mpcdf.mpg.de/vrs/arepo)、[arXiv:1909.04667](https://arxiv.org/abs/1909.04667)（Arepo 公开发布与许可）
- [github.com/dnelson86/arepo](https://github.com/dnelson86/arepo)（公开版镜像）
