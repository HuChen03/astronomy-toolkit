# 四个软件的功能覆盖表

> 依据：docs/research_gadget4_arepo.md、docs/research_hbtplus_2lptic.md（每条含来源）。
> 「覆盖」指 Skill 中有对应文档/模板/脚本；不等于每项都做过真实运行（验证状态见 docs/verification.md）。

## GADGET-4（GrGadget fork @ d0e3eee）

| 功能 | 入口/选项 | Skill 覆盖 |
|---|---|---|
| 纯引力 N-body（周期/非周期、共动） | Config `SELFGRAVITY`+`PERIODIC`；param `ComovingIntegrationOn` | SKILL + config-options.md + assets/param-DM-L50-N128.txt |
| TreePM / FMM | `PMGRID=` / `FMM` | config-options.md |
| SPH 流体（含压强 SPH） | NTYPES 含 type0 / `PRESSURE_ENTROPY_SPH` | config-options.md |
| 冷却+恒星形成反馈 | `COOLING`+`STARFORMATION` | config-options.md + parameters.md |
| Zoom 模拟 | `PLACEHIGHRESREGION` `PM_ZOOM_OPTIMIZED` | config-options.md |
| 内建 IC 生成（N-GenIC/2LPT） | `NGENIC` `NGENIC_2LPT` `CREATE_GRID` / RestartFlag 6 | running.md + parameters.md（N-GenIC 段） |
| FOF / SUBFIND | `FOF` / `SUBFIND` / RestartFlag 3 | running.md；注：FOF 编译在本 fork 未完全修复 |
| 功率谱 | `POWERSPEC_ON_OUTPUT` / RestartFlag 4 | running.md |
| 光锥 | `LIGHTCONE*` | config-options.md |
| 并合树 | `MERGERTREE` / RestartFlag 7/8/10/11 | running.md |
| snapshot 格式转换 | RestartFlag 5 | running.md（HBT+ 对接路径） |
| I/O 带宽测试 | RestartFlag 9 | running.md |
| restart/续跑 | flag 1/2、stop 文件、85% TimeLimitCPU | running.md |
| **相对论 PM（fork 特有）** | `GEVOLUTION_PM`/`GEVOLUTION_GR` | gr-fork.md（标注未官方核实） |
| 构建 | meson（fork 唯一可用路径） | building.md（含全部实测修复） |

## Arepo（公开版 @ d924fb3）

| 功能 | 入口/选项 | Skill 覆盖 |
|---|---|---|
| 移动网格流体（Voronoi）+MHD | 默认 / `MHD` | SKILL + parameters.md（网格正则化/细化参数） |
| TreePM 引力 | `PMGRID` | parameters.md |
| 宇宙学盒子 / zoom / 孤立星系 | examples + `PLACEHIGHRESREGION` | SKILL + assets/param-cosmo-box.txt / param-isolated-galaxy.txt |
| 冷却+恒星形成 | `COOLING`+`USE_SFR`；运行期 CoolingOn/StarformationOn | parameters.md |
| 1D/2D 测试（shocktube/gresho/noh…） | examples | SKILL（test.sh） |
| FOF/Subfind 后处理 | RestartFlag 3 | running.md |
| snapshot 转换 / Voronoi 网格输出 / 梯度 / 势 | flag 6/14/17/18 | running.md |
| restart + 自动重提交 | flag 1/2、stop 文件、ResubmitOn/ResubmitCommand | running.md + assets/job.slurm |

## HBT+（Kambrian/HBTplus @ 6f87ace，v1.16.2.MPI）

| 功能 | 入口/选项 | Skill 覆盖 |
|---|---|---|
| subhalo 追踪识别 + merger tree | `mpirun -np N ./HBT conf [start] [end]` | SKILL + running.md |
| 快照格式 gadget / apostle(EAGLE) / 自定义 | `SnapshotFormat` | io-formats.md |
| FoF 目录 gadget2/3 int/long、hbt_group_hdf5、apostle | `GroupFileFormat` | io-formats.md |
| 自带串行 FoF（toolbox） | toolbox/ | io-formats.md |
| 断点续跑 | start 参数 + SrcSnap | running.md |
| 双精度/64 位 ID/DM-only 等变体 | make HBTdouble / HBTi8 / 宏 | building.md |
| 后处理读取 | toolbox/HBTReader.py | running.md |
| 输出检查 | scripts/check_hbt_output.py | 已提供 |

## 2LPTIC（官方 tar 包）

| 功能 | 入口/选项 | Skill 覆盖 |
|---|---|---|
| 2LPT IC 生成（Gadget format 1 输出） | `mpirun -np N ./2LPTic param` | SKILL + assets/2LPT-small.param |
| ZA（一阶）退化 | 宏 `ONLY_ZA` | SKILL |
| 解析谱 E&H / Efstathiou / 读表 | `WhichSpectrum` | references/parameters.md |
| 自动产生气体粒子 | 宏 `PRODUCEGAS` | SKILL |
| WDM 谱截断/热速度 | `WDM_*` | parameters.md |
| 网格起点 glass 生成 | scripts/make_grid_glass.py | 已提供（实测） |
| 输出检查 | scripts/check_2lptic_output.py | 已提供（实测） |

## 共用执行层（cosmo-exec Skill）

Slurm 提交/查询/取消/终态判定（原生 CLI）、运行目录规范、三类 ID 区分、
mock-Slurm 测试后端、轮询脚本 wait_slurm_job.sh（≥30s 退避）。
