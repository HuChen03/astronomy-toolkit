# GADGET-4 编译选项（Config.sh）速查

权威清单：`sources/Gadget4/Template-Config.sh`（每个选项有注释）与
`sources/Gadget4/documentation/04_config-options.md`（逐一解释）。本文件只列决策要点。

## 规则

- Config.sh 是编译期配置：改任何一个宏都要重新编译，二进制与算例绑定（官方建议每个模拟独立目录+独立二进制）。
- 编译时 check.py 会校验选项拼写（未在 Template-Config.sh 中出现的名字报错；豁免名单 `defines_extra`）。

## 按任务选择（实证出处见 docs/research_gadget4_arepo.md §1.3）

| 任务 | 必需宏 |
|---|---|
| 纯 DM 宇宙学盒子 | `PERIODIC` `SELFGRAVITY` `PMGRID=<n>` `TREEPM_NOTIMESPLIT` `ASMTH=2.0` `NTYPES=2` `NSOFTCLASSES=1` |
| 在线生成 IC | 加 `NGENIC=<grid>` `NGENIC_2LPT` `CREATE_GRID` |
| FOF 在线群寻找 | 加 `FOF` |
| 功率谱输出 | 加 `POWERSPEC_ON_OUTPUT` |
| Zoom | `PLACEHIGHRESREGION` `PM_ZOOM_OPTIMIZED` `HRPMGRID=<n>` |
| SPH 气体 | NTYPES 含 type-0；压强 SPH 变体 `PRESSURE_ENTROPY_SPH` |
| 冷却+恒星形成 | `COOLING` `STARFORMATION` |
| SUBFIND | `SUBFIND` |
| 光锥 | `LIGHTCONE` `LIGHTCONE_PARTICLES`/`LIGHTCONE_MASSMAPS` |
| 并合树 | `MERGERTREE` |
| 相对论 PM（本 fork） | `GEVOLUTION_PM`（+`GEVOLUTION_GR`）——文档未记录，依据 arXiv:2301.11854，**未官方核实** |

## 现成参照（examples/*/Config.sh）

`DM-L50-N128`（DM 盒子+FOF+功率谱+在线 IC）、`DM-Zoom-Aq-C-5`（zoom+SUBFIND）、
`CollidingGalaxiesSFR`（冷却+SF）、`SantaBarbara-PSPH-64`（压强 SPH）、
`G2-galaxy`/`G2-gassphere`/`G2-cluster`/`G2-lcdm-gas`（非宇宙学/含气）。
新算例从最接近的 example 复制 Config.sh 修改。

## 精度与 ID

`POSITIONS_IN_32BIT`/`64BIT`/`128BIT`、`DOUBLEPRECISION=1|2`、`DOUBLEPRECISION_FFTW`、
`IDS_32BIT`/`48BIT`/`64BIT`（fork 新增；本地已补文档，见 building.md「已做修改」）。
