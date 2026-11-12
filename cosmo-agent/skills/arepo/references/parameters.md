# Arepo 参数文件要点

来源：userguide parameterfile.html + examples/*/param.txt。格式与 GADGET-4 相同：「关键字 值」，每关键字恰好一次，`%`/`#` 注释。

## 与 GADGET-4 共有的核心类别

文件（`InitCondFile` `OutputDir` `SnapshotFileBase` `ICFormat` `SnapFormat`）、
输出（`OutputListOn` `OutputListFilename` `TimeBetSnapshot` `TimeOfFirstSnapshot`）、
CPU/内存（`TimeLimitCPU` `CpuTimeBetRestartFile` `MaxMemSize` MB/rank `FlushCpuTimeDiff`）、
时间（`TimeBegin` `TimeMax` `ComovingIntegrationOn`）、
宇宙学（`Omega0` `OmegaLambda` `OmegaBaryon` `HubbleParam` `BoxSize`）、
单位制（`UnitLength_in_cm` `UnitMass_in_g` `UnitVelocity_in_cm_per_s` `GravityConstantInternal`）、
力/时间步（`ErrTolTheta` `ErrTolIntAccuracy` `MaxSizeTimestep` `CourantFac`）、
软化（`SofteningComovingTypeX` `SofteningMaxPhysTypeX`）。

## Arepo/移动网格专属

- `PeriodicBoundariesOn`（0/1）
- 网格正则化：`CellMaxAngleFactor`、`CellShapingFactor`、`CellShapingSpeed`
- 细化/去细化：`RefinementCriterion`、`DerefinementCriterion`、`TargetGasMassFactor`、`MaxVolumeDiff`、`MaxNumNgbDeviation`
- 物理开关（运行期）：`CoolingOn`、`StarformationOn`
- 自动重提交：`ResubmitOn`、`ResubmitCommand`

## 模板

- `assets/param-cosmo-box.txt`：`examples/cosmo_box_gravity_only_3d/param.txt`（50 Mpc/h、32³、z=127→0；IC 由 MUSIC/N-GenIC 经 create.py 生成，见 param_music.txt/param_ngenic.txt）。
- `assets/param-isolated-galaxy.txt`：`examples/isolated_galaxy_collisionless_3d/param.txt`（**IC 随仓库提供**，最快真实算例）。
