# GrGadget fork vs 官方 GADGET-4 差异（已核实）

来源：本地 `sources/Gadget4` git 历史与代码（2026-09-10）；官方版对照：arXiv:2010.03567、http://gitlab.mpcdf.mpg.de/vrs/gadget4。

- fork 基点：官方 master @ 8935b95（2020-11-15）；此后 ~176 个 commit 来自 Eduardo Quintana Miranda。
- 分支 master / units / fix-lightcones / gevolution-pm 内容已全部合入 master（`git log master..<branch>` 为空）。master HEAD = d0e3eee。

## 差异清单

1. **相对论 PM 求解器（核心）**：`GEVOLUTION_PM` / `GEVOLUTION_GR` 编译宏；用 libgevolution 的相对论 PM（Poisson 规范度规扰动）替换官方 PM 长程力；粒子携带相对论动量；`NEWTONIAN_DRIFT` 可恢复牛顿漂移。代码：`gadget/include/gadget/addons/gevolution-pm.hpp`、`latfield_handler.hpp`、`src/pm/pm.h`。论文：arXiv:2301.11854。
2. **meson 构建**：新增 `meson.build`（项目名 OpenGadget4，C++17），源码重构为 gadget/、half/、md5/、vectorclass/ 等库；官方 GNU Make 路径保留但**已损坏**（见 building.md）。
3. **新增依赖**：Boost（mpi/serialization/unit_test_framework）、chealpix、LATfield2、gevolution-1.2（meson 无条件链接）。
4. **单位调整**：units 分支（物理常数更新、meson `config_file` 选项、hwloc 可选化）已并入 master。
5. **修复**：snapshot header 构造 bug（d0e3eee）。

## 使用注意

- fork 的 README/documentation **未记录** GR 选项；GR 用法以论文和源码为准（标注「推测」的内容不可当作官方行为）。
- 官方 example 的参数文件/Config.sh 在 fork 中仍然可用（DM-L50-N128 等 8 个例子均在）。
- 与官方版结果的可比性：纯牛顿配置下应与官方一致（未实测对比，「未核实」）。
- 不要把 MP-Gadget（另一套代码）或官方 gadget4 的构建/排错经验直接套用本 fork。
