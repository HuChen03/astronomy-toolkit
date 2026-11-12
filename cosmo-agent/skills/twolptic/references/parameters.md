# 2LPTIC 参数文件（28 项全部必填）

来源：官方示例包 `run2LPT.tar.gz` 中 `2lpt_Carmen.param`，及源码 `read_param.c`（tag 注册顺序）。
格式：每行 `关键字 值`（空白分隔），`%` 之后为注释。源码 `read_param.c` 用 `sscanf("%s%s%s")`
取第一列匹配 tag，所以**关键字必须在最前面**；写成「值 关键字」会得到 `Tag not allowed`。
错误路径是 `errorFlag` → `MPI_Finalize(); exit(0)`，**退出码仍是 0**，只能靠 stdout 判断。

| 参数 | 含义/单位 |
|---|---|
| `Nmesh` | FFT 网格尺寸，须 ≥ Nsample |
| `Nsample` | 每维粒子数（总粒子数 = Nsample³）；决定 Nyquist 频率 k_Nyq=2π/Box·Nsample/2 |
| `Box` | 周期盒子边长（单位由 UnitLength 决定，通常 Mpc/h） |
| `FileBase` | 输出文件名前缀 |
| `OutputDir` | 输出目录（须已存在） |
| `GlassFile` | glass 文件路径（Gadget format 1，只用位置） |
| `GlassTileFac` | glass 平铺次数/维；1 粒子 glass 时 = Nsample |
| `Omega` | Ω_m(z=0) |
| `OmegaLambda` | Ω_Λ |
| `OmegaBaryon` | Ω_b |
| `OmegaDM_2ndSpecies` | 第二 DM 组分（0=无） |
| `HubbleParam` | 小 h |
| `Redshift` | 起始红移 |
| `Sigma8` | 功率谱归一化 |
| `SphereMode` | 1=只用 \|k\|<k_Nyq 球内模；0=立方体 |
| `WhichSpectrum` | 1=Eisenstein&Hu 解析谱；2=读表（FileWithInputSpectrum）；其他=Efstathiou 参数化 |
| `FileWithInputSpectrum` | 表格式功率谱文件（仅 WhichSpectrum=2 时读取，其他情况给占位路径即可） |
| `InputSpectrum_UnitLength_in_cm` | 输入谱的长度单位（cm/h），仅 WhichSpectrum=2 |
| `ShapeGamma` | Efstathiou 谱的形状参数 Γ（仅 WhichSpectrum 非 1/2 时用） |
| `PrimordialIndex` | 原初谱指数 n_s |
| `Seed` | 随机种子 |
| `NumFilesWrittenInParallel` | 输出并发度（写盘进程组数）；**要求 mpirun 的 N ≥ 它**，无整除要求（`save.c:18`）。它不等于输出文件数——文件数由 `NumPart > 0` 的 task 数决定 |
| `UnitLength_in_cm` | 输出长度单位（cm/h），3.085678e24 = Mpc/h |
| `UnitMass_in_g` | 输出质量单位，1.989e43 = 1e10 Msun/h |
| `UnitVelocity_in_cm_per_s` | 输出速度单位，1e5 = 1 km/s |
| `WDM_On` | 1=启用 WDM 小尺度功率谱截断 |
| `WDM_Vtherm_On` | 1=给 WDM 粒子加热速度 |
| `WDM_PartMass_in_kev` | WDM 粒子质量（keV） |

模板：`assets/2LPT-small.param`（64³ 网格、32³ 粒子、50 Mpc/h、Eisenstein&Hu 谱、z=49——单机秒级完成的最小算例）。
