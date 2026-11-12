---
name: cosmo-doc-search
description: 通过 cosmo-exec MCP 执行 grep/rg 检索本机部署的宇宙学软件文档，为 GADGET-4、Arepo、2LPTIC、HBT 的参数选择、编译、输入输出对接和错误诊断提供依据。
---

# 检索文档后使用科学软件

## 文档位置

先调用 `env_info`，读取其 `documentation` 清单。路径均在 MCP 服务端。
客户端安装的 Skill 是导航；不要把客户端路径直接传给服务端文件工具。

项目内的导航入口是 `docs/documentation-index.yaml`。优先查询对应版本的上游文档；
`skills/<software>/references/` 是本地经验补充。文档不能解释分支行为时再检索源码。
GADGET 使用 GrGadget fork；GADGET 的 HDF5 输出须配 HBT 的 G4 reader。

## 检索与执行

通过通用 `exec_run` 调用原生命令，不新增按科学功能划分的 MCP 工具。例如：

```json
{"argv":["rg","-n","-i","-e","OutputListOn","-e","OutputListFilename","-e","TimeMax","sources/Gadget4/documentation"],"cwd":"<服务端项目根目录>"}
```

没有 rg 时用 `grep -R -n -i -E`。退出码 1 表示无匹配，不是程序故障。
多关键词一律用 `-e` 分开写：`rg -n -i "a|b"` 这种写法在模式以 `-` 开头或含空格时会失效。
用 `sed -n '120,165p' <命中文件>` 读取上下文；命中很多时缩小到具体文件、参数名或错误原文。
不要将整个源码目录及构建产物一次性读入上下文。

运行前查清：编译宏是否启用、运行参数单位、输入格式及 ID 位宽、成功标志、续跑条件。
对每个关键决定，把问题、检索命令、命中文件/行号、采用的值及理由写入 **`cosmo-exec` 约定的运行目录**
下的 `documentation-evidence.md`（即 `<data_dir>/<软件>/<任务名>-<日期>/documentation-evidence.md`，
服务端路径），不要另创一套位置。区分上游文档、源码推断、本地实测；模板默认值不是用户要求。

`docs/documentation-index.yaml` 的 `queries` 只是常见入口，**不是可查内容的边界**——列表里没有的
参数（如内存/时限/单位类）直接对 `source/` 跑 `rg`。该索引同时给出 `version`，用于判断
「上游文档」到底对应哪份代码；GADGET 用的是 GrGadget fork，fork 特有行为以源码和
项目根 `modifications.md` 为准，不要默认上游文档说到就适用。

随后通过 MCP 写参数并运行原生 CLI。检查日志及实际输出，不能仅凭退出码判成功。
错误发生后以日志原文检索对应软件文档/源码，修复后从可恢复阶段继续。

## 完整纯暗物质管线

2LPTIC → GADGET-4（外部 IC、FoF）→ HBT-G4（从首帧顺序处理）→ 并合树导出。
Arepo 是另一种演化引擎，按任务选择，不串接在 GADGET 后演化同一次模拟。
统一盒长、宇宙学、单位和 ID；`Mpc` 与 `Mpc/h` 必须显式区分。
检查 50 个输出时刻及全部分片；HBT 的 TrackId 是复合数据集字段。
同一 TrackId 的时序轨迹不自动证明并合连接已验证，须核查该版本的 sink 字段语义。
