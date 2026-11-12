# GADGET-4 参数文件要点（GrGadget fork 同官方）

来源：`sources/Gadget4/documentation/05_parameterfile.md` 与 `examples/*/param.txt` 实测。

## 格式规则（易错）

- 每行「**关键字 值**」；`%` 或 `#` 之后为注释。
- **每个关键字必须恰好出现一次**——缺失或重复都会在启动时报错退出。
- 完整模板以 `assets/param-DM-L50-N128.txt`（已逐行注释）为准；关键字全集见源码 `documentation/05_parameterfile.md`。

## 常用类别速查

| 类别 | 关键参数 | 说明/单位 |
|---|---|---|
| 文件 | `InitCondFile` `OutputDir` `SnapshotFileBase` `ICFormat` `SnapFormat` | SnapFormat 3=HDF5（推荐）；ICFormat 同理 |
| 输出节奏 | `OutputListOn` `OutputListFilename` / `TimeBetSnapshot` `TimeOfFirstSnapshot` | 共动时 TimeBetSnapshot 为 ln(a) 乘性间隔；OutputListOn=1 时从文件读时刻列表（每行一个 a） |
| 时间 | `TimeBegin` `TimeMax` `ComovingIntegrationOn` | 共动模式下为尺度因子 a |
| 宇宙学 | `Omega0` `OmegaLambda` `OmegaBaryon` `HubbleParam` `BoxSize` | BoxSize 单位 = UnitLength（通常 Mpc/h） |
| 单位制 | `UnitLength_in_cm` `UnitMass_in_g` `UnitVelocity_in_cm_per_s` `GravityConstantInternal` | 典型：Mpc/h、1e10 Msun/h、km/s；G=0 自动推导 |
| CPU/内存 | `TimeLimitCPU`（秒，85% 触发自动 checkpoint）`CpuTimeBetRestartFile` `MaxMemSize`（MB/rank） | |
| 力精度 | `TypeOfOpeningCriterion` `ErrTolTheta` `ErrTolThetaMax` `ErrTolForceAcc` | |
| 时间步 | `MaxSizeTimestep` `MinSizeTimestep` `ErrTolIntAccuracy` `CourantFac` | |
| 软化 | `SofteningComovingClassX` `SofteningMaxPhysClassX` `SofteningClassOfPartTypeX` | 单位 = UnitLength |
| SPH | `DesNumNgb` `MaxNumNgbDeviation` `InitGasTemp` `ArtBulkViscConst` | 纯 DM 算例也需给出占位值 |
| 冷却/SF | `TreecoolFile` `MaxSfrTimescale` `TempClouds` `TempSupernova` `FactorEVP` `FactorSN` `CritPhysDensity` `CritOverDensity` | 需编译 COOLING/STARFORMATION |
| N-GenIC | `NSample` `GridSize` `PowerSpectrumType`（0=Efstathiou 解析，1=Eisenstein&Hu，2=读表）`PowerSpectrumFile` `Sigma8` `PrimordialIndex` `ShapeGamma` `Seed` `SphereMode` `ReNormalizeInputSpectrum` `InputSpectrum_UnitLength_in_cm` | 需编译 `NGENIC=<n>`；Type 2 时 PowerSpectrumFile 必须存在 |
| FOF/光锥 | `DesLinkNgb`、`LightConeDefinitionFile` 等 | 需相应编译选项 |

## 修改参数时的硬约束

- 改 `NSample`/`GridSize` 必须与 Config.sh 的 `NGENIC=<n>`（网格上限）一致——NGENIC 是编译期网格大小上限。
- `NumFilesPerSnapshot` × I/O 并发不要超过文件系统能力；大分区先用 RestartFlag 9 测 I/O。
- restart 续跑（flag 1）时参数文件内容必须与上次一致（除 TimeLimitCPU 等少数项）；改了物理参数请用 flag 2 从 snapshot 重启。
