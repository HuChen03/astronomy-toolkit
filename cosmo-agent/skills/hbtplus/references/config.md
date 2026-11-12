# HBT+ 配置文件（.conf）

来源：`sources/HBTplus/src/config_parser.h`（默认值）、`config_parser.cpp`、`configs/Example.conf`。
格式：纯文本键值对，`#` 或 `[` 之后是注释；大小写敏感；**未识别的键直接报错退出**。

## 必选（7 个，缺一不可，缺了报 "entry N missing"）

| 参数 | 含义 |
|---|---|
| `SnapshotPath` | 快照目录 |
| `HaloPath` | FoF group 文件目录 |
| `SubhaloPath` | 输出目录（程序自建） |
| `SnapshotFileBase` | 快照文件名前缀 |
| `MaxSnapshotIndex` | 最大快照编号 |
| `BoxSize` | 盒子尺寸（与快照 header 做一致性检查） |
| `SofteningHalo` | DM 软化长度 |

## 可选（默认值来自 config_parser.h:82-115）

| 参数 | 默认 | 含义 |
|---|---|---|
| `SnapshotFormat` | `gadget` | gadget / apostle / mysnapshot |
| `GroupFileFormat` | `gadget3_int` | gadget3_int/long、gadget2_int/long、hbt_group_hdf5、apostle_particle_index |
| `MaxConcurrentIO` | 10 | 并行 IO 线程上限 |
| `MinSnapshotIndex` | 0 | 起始快照 |
| `MinNumPartOfSub` | 20 | subhalo 最少束缚粒子数（低于则 orphan） |
| `MassInMsunh` | 1e10 | 质量单位 Msun/h |
| `LengthInMpch` | 1 | 长度单位 Mpc/h |
| `VelInKmS` | 1 | 速度单位 km/s |
| `PeriodicBoundaryOn` | true | |
| `SnapshotHasIdBlock` | true | 快照是否含 ID 块 |
| `SnapshotIdUnsigned` | false | |
| `ParticleIdNeedHash` | true | 性能 |
| `SaveSubParticleProperties` | false | 保存每粒子位置/速度 |
| `MergeTrappedSubhalos` | true | |
| `SnapshotIdList` | 空 | 显式快照编号列表（此时 MaxSnapshotIndex=列表长度-1） |
| `MajorProgenitorMassRatio` | 0.8 | |
| `BoundMassPrecision` | 0.995 | |
| `SourceSubRelaxFactor` | 3.0 | |
| `SubCoreSizeFactor` / `SubCoreSizeMin` | 0.25 / 20 | coresize 计算 |
| `TreeAllocFactor` | 0.8 | |
| `TreeNodeOpenAngle` / `TreeMinNumOfCells` | 0.45 / 10 | |
| `MaxSampleSizeOfPotentialEstimate` | 1000 | 0=全粒子精确势能（慢） |
| `RefineMostboundParticle` | true | |

FoF 程序专用（toolbox FoF）：`FoFLinkParam`(0.2)、`FoFSizeMin`(20)、`FoFDarkMatterMassFraction`(1.0)。

`SubhaloPath/snapshotlist.txt`：为快照文件名不规则的模拟（EAGLE 等）提供逐快照文件名；用 `toolbox/CreateSnapshotList.py` 生成。

模板：`assets/Example.conf`（源码 configs/Example.conf 原样拷贝）。
