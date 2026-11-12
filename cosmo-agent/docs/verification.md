# 验证结果与未验证项

验证日期：2026-09-10 ~ 2026-09-13；2026-09-16 补充执行层的安全边界（命令策略 / 受保护路径 / 审计）。环境：单机 128 核（无真实 Slurm 集群）。
分级：**文档核实** / **模拟测试通过** / **真实软件运行通过** / **真实集群验证通过**。

## 执行层（cosmo-exec MCP）

| 项目 | 状态 | 证据 |
|---|---|---|
| 11 个工具注册与调用 | 真实运行通过 | tests/smoke_client.py 15/15（真实 MCP 客户端 over stdio） |
| 文件读/写/列、分页 | 真实运行通过 | 同上 |
| 错误参数/缺失输入/非零退出码回传 | 真实运行通过 | 同上（`false`、`cat 不存在文件`） |
| 超长输出截断（头+尾保留，全文落日志） | 真实运行通过 | 同上（300KB 输出） |
| 前台超时杀进程 | 真实运行通过 | 同上（sleep 30, timeout=2） |
| 后台进程增量输出、停止 | 真实运行通过 | 同上 |
| allowed_roots 服务端强制 | 真实运行通过 | 同上（/etc/passwd 被拒） |
| 执行账本跨会话持久 | 真实运行通过 | run_list 读到此前会话记录 |
| `exec_output` 分流分页（stdout/stderr 各自独立游标） | 真实运行通过 | test_regressions.py::test_exec_output_pages_streams_independently；子 Agent 实跑核对 offset 0→200→400→600 与 total_bytes 自洽 |
| `env_info` 暴露 `slurm_mock_backend` / `slurm_mock_available` | 真实运行通过 | test_regressions.py::test_env_info_exposes_slurm_mock_backend；实跑返回 mock 路径且 available=true |
| 命令策略：内置拒绝表拦截灾难命令 | 真实运行通过 | 真机会话（沙箱外 stdio MCP）：`rm -rf /` → 规则 `delete-filesystem-root-or-system-dir`、`sudo ls` → `privilege-escalation`，两者均被拒并写审计；同会话 `echo` / `mpirun` 正常放行。单元层 tests/test_policy.py 13/13 |
| 命令策略：包装穿透与 `bash -c` 脚本二次扫描 | 模拟测试通过 | test_policy.py：`sudo nice xargs rm -rf /`、`env FOO=1 rm -rf /`、`sh -c 'ls; rm -rf /usr'`、`bash -c 'rm -rf /'`、`find / -delete`、`mkfs`、`dd of=/dev/…`、`curl … \| sh`、fork bomb 均被拒；`rm -rf runs/…`、`rm -rf ~/scratch`、`chmod +x`、`rg -n 'rm -rf /' docs` 正常放行 |
| 命令策略：白名单模式与 shell 开关 | 模拟测试通过 | test_policy.py：`exec.allow_commands` 非空时 `mpirun` 与 `shell=true` 均被拒（白名单自动禁用 shell）；`exec.allow_shell: false` 时只接受 argv 数组 |
| 命令策略：拒绝发生在建 process/建 run 目录之前 | 模拟测试通过 | test_policy.py::test_manager_refuses_denied_command_without_spawning：拒绝后 ledger 无 run 目录，仅 1 条 `exec_denied` 审计；`start_background` 同样在起 supervisor 前拦截 |
| 命令策略：空配置不会静默关闭守卫 | 模拟测试通过 | test_policy.py::test_empty_deny_patterns_does_not_disable_the_builtin_table 与 shipped-manifest 回归。**此缺陷曾在真机复现**（清单 `deny_patterns: []` 被实现成“无规则”，`rm -rf /` 真的执行了），修复后语义为：内置表默认启用，只能由 `builtin_deny_patterns: false` 或 `disabled_deny_patterns: [名字]` 显式削弱，`deny_patterns` 仅追加 |
| 受保护路径：`file_write` 拒写服务端自身文件 | 真实运行通过 | 真机会话：`sources/guard-check.txt`、`environments/local.yaml`、`mcp_server/src/cosmo_exec/server.py` 均被拒并记 `file_write_denied`；`runs/guard-check/ok.txt` 正常写入。自动保护范围＝cosmo_exec 包 + 环境清单 + `<state_dir>/audit.jsonl`，站点用 `paths.protected` 扩展 |
| 审计日志 `<state_dir>/audit.jsonl` | 真实运行通过 | 上述写入/拒绝按行落盘（ts、pid、event、path/argv、reason），JSON Lines |
| 新保护不误伤既有流程 | 真实运行通过 | 修复后 smoke_client.py 15/15、test_regressions.py 15/15、e2e_gadget4.py（见下）；`file_write` 到 `runs/`、`exec_start` mpirun、mock-Slurm 提交均照常 |
| 客户端原生挂载（`codex mcp add cosmo-exec`） | **未在会话内验证** | 配置已写入 `~/.local/share/codex/config.toml`；MCP 仅在客户端启动时加载，已运行的会话与子 Agent 看不到，需重开会话 |
| mcp 1.27 stdio 偶发响应丢失 | **已知问题** | e2e 日志中 exec_output 首次调用 30s 无响应、重试即成功；客户端须用超时+重试（见 mcp_server/client_helpers.py） |
| mock-Slurm 后端（sbatch/squeue/sacct/scancel） | 模拟测试通过 | e2e_gadget4.py：sbatch --parsable → job_id → sacct COMPLETED；**不等于真实集群** |
| 真实 Slurm 集群 | **未验证**（本机无 Slurm） | 待办 |

## 软件

| 软件 | 编译 | 真实运行 | 说明 |
|---|---|---|---|
| 2LPTIC | 通过（FFTW 2.1.5 自编译，-fno-pie/-no-pie） | **通过**：32³ 粒子/50 Mpc/h/z=49，输出 2 文件 32768 粒子，`IC's generated.`；与直接 CLI 参照输出逐字节一致（经 MCP 复跑对比） | runs/twolptic/small, via-mcp |
| GADGET-4 (GrGadget) | 通过（meson，最小配置：去 FOF/POWERSPEC；fork 源码 8 处修补，见 modifications.md） | **通过**：DM-L50-N128 短程（a=0.015625→0.02，128³，8 rank），3 个 snapshot，能量/日志正常 | runs/gadget4/dml50-mcp |
| Arepo（公开版） | 通过（新增 CosmoLinux SYSTYPE；Makefile AREPOVTK 段加守卫） | **通过**：isolated_galaxy_collisionless_3d（IC 随仓库），10 个 snapshot，正常收尾 | runs/arepo/isogal/run |
| HBT+（v1.18.1.MPI-G4，HBTi8） | 通过（make，HDF5 openmpi 变体） | **通过**：经 MCP 在 pilot-32 上以 `SnapshotFormat gadget4_hdf` + `GroupFileFormat gadget4_hdf` 直读 GADGET-4 HDF5 快照与 `fof_tab_*.hdf5` 目录，5 个快照全部输出 SubSnap/SrcSnap 并通过 check_hbt_output.py | runs/acceptance/pilot-32/hbt/output |

## 端到端（经真实 MCP 客户端）

| 链路 | 状态 |
|---|---|
| 读 Skill 模板 → file_write 参数 → exec_run/exec_start → 日志 → 输出检查（Gadget4） | 通过（e2e_gadget4.py ALL PASS） |
| 错误参数文件被软件拒绝并回报（Gadget4 缺 OutputDir） | 通过（软件退出码为 0 但日志含 "I miss a value"，证明不能只看退出码） |
| mock-Slurm 提交/查询/终态/job_id 挂账 | 通过（2LPTIC 作业） |
| Arepo + 2LPTIC 经 MCP | 运行中/结果见 /tmp/e2e_a2.out |
| Skill 三层验证（发现层/结构层/功能层） | 通过：`codex debug prompt-input` 确认 6/6 注入且渐进式披露生效；`scripts/check_skills.py` 0 problem；`e2e_skill.py` ALL PASS |
| 子 Agent 只凭 Skill 实跑 3 条任务（文档检索 / 2LPTIC 端到端 / 后台进程与账本） | 通过（覆盖 11 个工具中的 10 个），并据此修复 10 项 Skill/工具缺陷。详见 `docs/skill-verification.md` |

## 未验证项（明确列出）

1. **真实 Slurm 集群**：所有 Slurm 流程仅经 mock 后端验证；`sbatch/squeue/sacct` 真实行为（排队、PD 态、终态延迟、作业数组）未验证。
2. **HBT+ 非空 merger tree**：pilot-32 已跑通「读 GADGET-4 快照 + FoF 目录 → 追踪 → 写 SubSnap/SrcSnap」全链路，但其 FoF 目录为空（原因见下「环境与物理约束」），故未在该算例上产出非空树。`scripts/export_hbt_tree.py` 的非空树导出已在 `runs/acceptance/historical-tree/`（5 快照 / 1190 节点 / 760 连续边 / 1 次并合，validation passed）验证。非空端到端随 128³ 验收实验进行。
   注：无需 RestartFlag 5 转 format 1、也无需 toolbox FoF——HBT 的 G4 分支原生读 GADGET-4 HDF5。
3. **GrGadget：FOF 配置已可编译，POWERSPEC/GR 仍未验证**。含 FOF 的配置（`NTYPES=2` + `FOF` + `FOF_LINKLENGTH` + `GADGET2_HEADER`）已编译并运行成功（`sources/Gadget4/build-cosmo-dm128`，见 `runs/acceptance/dm128-200mpc-prepared/build.log` 的 `[145/145] Linking target Gadget4`）。`POWERSPEC_ON_OUTPUT` 与 GR 功能（`GEVOLUTION_PM`/`GEVOLUTION_GR`）未编译未验证，文档缺失（仅论文）。
4. **Gadget4 长程到 z=0**：短程只验证到 a=0.02。128³ / 200 Mpc / 50 快照的验收实验正在运行（`runs/acceptance/dm128-200mpc-prepared`），完成后更新本节。
   2026-09-15 22:49 UTC 该次执行在 `TimeLimitCPU` 检查点处停下：1200 个 sync point、
   a=0.2856（z=2.50）、累计 dln a = 2.659 / 3.912（**68%**）、29/50 快照，已写出 16 份 restart。
   这是 20 h 预算（85% → 17 h）的预期行为，不是崩溃。管线已改为自动续跑；
   单次预算内的实测速率约 51 s/步（早期 88 s/步，后期活跃粒子变少更快）。总时长预计 25–35 h。
5. **Arepo 含气流体/MHD**：只验证了无碰撞孤立星系。
6. **HBTReader（python2 时代代码）在 python3 的兼容性**：未实测。
7. 跨节点 MPI（多节点 ghost rank 约束）未验证（单机环境）。

## 环境与物理约束（运行前必读）

| 约束 | 现象 | 处理 |
|---|---|---|
| `/dev/shm` 上限 16 GB | GADGET-4 启动即 `Terminate: At least one node has insufficient memory`，并打印 `we have N MPI ranks and at most 16381.5 MB of *shared* memory available` | GADGET-4 要求 `N_rank × MaxMemSize ≤ /dev/shm 可用量`（`src/system/system.cc:report_free_size_in_tmpfs` 用 `statvfs("/dev/shm")`，再经 `mymalloc.cc:check_maxmemsize_setting` 校验）。本机不可 remount，故按 16 GB 预算配 rank 数：8×1800 / 16×900 / 32×~500 MB。128³ 验收实验用 16×900 MB |
| FoF 最小群大小 32 个粒子 | 32³ pilot 的 5 个快照 FoF 目录全为空，日志 `FOF: Total number of FOF groups with at least 32 particles: 0` | 这是分辨率而非配置问题：pilot 粒子质量 6.5e12 Msun/h，z=0 最大结构不足 32 个粒子。FoF 日志中 `Marked=N ... which are linked` 非 0，说明连接过程正常，只是全部低于阈值。128³ 粒子质量小 64 倍，正常出群 |
| MPI 到共享内存/网络 | 沙箱内 `socket()` 被拒、`opal_ifinit: socket() failed`；MCP server 与 mpirun 必须运行在沙箱外 | MCP 服务与 MPI 作业需在非受限环境执行 |
| 节点负载影响启动 | 高负载时 MCP HTTP server 启动可超 10 s，客户端原 `range(100)×0.1s` 预算会误报 "did not start" | `mcp_server/client_helpers.py` 启动等待放宽到 60 s |
| `TimeLimitCPU` 是检查点，不是失败 | 128³ 验收跑到 17 h（= 85% × 72000 s）时日志出现 `reaching time-limit. stopping.` + `RESTART: Writing restart files.`，**exit code 0**，此刻只有 29/50 快照 | 这是 GADGET-4 的设计行为（`run.cc:298`）。`e2e_pipeline.py` 现在会自动带 restart 标志 `1` 续跑（`main.cc:227` 的 `argv[2]` → `RST_RESUME`）直到 `TimeMax`；`scripts/finish_acceptance.py` 只认输出校验结论 `outputs_validated`，不再把退出码 0 当成功 |
