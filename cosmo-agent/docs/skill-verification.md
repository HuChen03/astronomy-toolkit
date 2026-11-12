# Skill 验证：子 Agent 只凭 Skill 能否正确使用工具

验证日期：2026-09-15。方法：派**独立子 Agent**（各自全新会话、自带 Skill 发现能力），
只给任务目标和访问 MCP 的方式，不提示工具用法，观察它能否按 Skill 正文正确完成任务，
并要求它报告「Skill 与实际不符/含糊/缺失之处」。

## 三层验证

| 层 | 验证内容 | 方法 | 结果 |
|---|---|---|---|
| 发现层 | 客户端能否看到 6 个 Skill | `codex debug prompt-input` 渲染模型可见输入 | 6/6 注入；渐进式披露生效（只注入 name+description+路径，约 7983 字符正文不进上下文） |
| 结构层 | SKILL.md 结构、frontmatter、被引用的 references/assets/scripts 是否存在 | `scripts/check_skills.py` | `6 skills checked, 0 problem(s)`，退出码 0 |
| 功能层 | 只凭 Skill 能否真的把工具用对 | 子 Agent 实跑（本节）+ `mcp_server/tests/e2e_skill.py` | 见下 |

发现层的结论对**子 Agent 同样成立**：子 Agent 会继承主会话启动时加载的 Skill 列表和工具配置。

## 子 Agent 实跑（2026-09-15）

三个子 Agent 并行，覆盖 11 个工具中的 10 个：

| 子 Agent 任务 | 覆盖的工具 | 结果 |
|---|---|---|
| A 文档检索：查 `MaxMemSize` / `TimeLimitCPU` 的单位与含义，并留证据文件 | `env_info`、`exec_run`(×13，rg/sed/ls/mkdir)、`file_write`、`file_list` | 通过。结论与上游文档 `sources/Gadget4/documentation/05_parameterfile.md:232,162` 原文一致：`MaxMemSize` = 每个 MPI process 的 MB 上限；`TimeLimitCPU` = 墙钟秒（`run.cc:298` 用 `CPUThisRun` 与 `0.85*TimeLimitCPU` 比较）。证据文件 `runs/subagent/docsearch/documentation-evidence.md`（7747 B） |
| B 2LPTIC 端到端：按 Skill 生成一组 IC 并判定成功 | `env_info`、`file_list`、`file_read`(经 exec_run cat)、`file_write`(×5)、`exec_run`(含 mpirun) | 通过。`mpirun --allow-run-as-root -np 2 2LPTic 2LPT.param` → stdout 含 `IC's generated.` → 检查脚本 PASS；产物 `runs/subagent/twolptic/output/ics.{0,1}`（各 459040 B）、`inputspec_ics.txt`(30826 B) |
| C 后台进程与账本：`exec_start`/`exec_output`/`exec_stop`/`run_list`/`run_get` | 同上 5 个 | 通过。增量读 `offset 0→200→400→600`、`next_offset` 与 `total_bytes` 自洽；`exec_stop` 后 `exit_code=-15`、`finished_at` 落地，`ps` 确认 supervisor/子进程全消失 |

子 Agent 具备按需提权的能力（沙箱内网络被禁，MCP 调用需 `sandbox_permissions: require_escalated`）；
这不影响 Skill 本身的可用性判断，但说明**客户端必须能访问 MCP 服务**。

## 本轮定位并修复的缺陷

子 Agent 的批评先被独立复核（读源码/实测），确认为真才修：

| 缺陷 | 证据 | 处理 |
|---|---|---|
| `twolptic` SKILL.md 称「mpirun 的 N 必须 ≥ 且整除 `NumFilesWrittenInParallel`」 | `save.c:18` 只检查 `NTask < NumFilesWrittenInParallel` → `FatalError(24131)`，**无整除要求**；上游报错措辞还是反的 | SKILL.md 与 `references/parameters.md` 均改正，并提示别按上游错误信息字面理解 |
| `twolptic` 称输出为 `FileBase.0 … .(NumFiles-1)` | `save.c:69` 是 `sprintf("%s/%s.%d", OutputDir, FileBase, ThisTask)`；只有 `NumPart>0` 的 task 写盘，序号可能不连续；`header.num_files` = 写盘 task 数（`save.c:136`） | SKILL.md 改为按 glob `FileBase.*` 枚举，并说明 `num_files` 语义 |
| `twolptic` 未提 root 运行 | 服务端进程是 root，裸 `mpirun` 必被 OpenMPI 拒绝；该信息只在环境清单 `mpi.notes` 里 | SKILL.md 明确要求 `--allow-run-as-root` |
| `twolptic` 未提 `OutputDir` 必须预先存在、相对路径依赖 cwd | `exec_run` 默认 cwd 是 allowed_root 而非运行目录 | 新增「运行注意（实测）」一节 |
| `check_2lptic_output.py` 只校验头块尺寸与第一个 POS 块 | 位移全为 0、缺 ID 块、头字段被写坏都能 PASS | 重写：校验头块与结束标记、POS/VEL/ID 三块尺寸与结束标记、文件长度与块结构自洽、头字段合理性、各文件 `npartTotal` 一致、可选总粒子数断言。已对 32³ 与 128³ 两个真实产物回归通过，负例正确 FAIL |
| `cosmo-exec` 未告诉 Agent「MCP 没原生挂载时怎么办」 | 子 Agent 若不看提示词会卡在第一步 | SKILL.md 新增「客户端接入（先确认你属于哪种）」，指向 `scripts/mcp_cli.py`；同时说明同机/异机两种拓扑下客户端路径能不能直接用 |
| `exec_start` 的 docstring 写 `run_id (MCP session process id)`；`meta.pid` 被描述成「命令的 pid」 | `processes.py` 记录的是 supervisor（`worker.py`）的 pid，命令是其子进程 | 修正 docstring 与 Skill：`pid` 是 supervisor，需按进程组查 |
| `exec_output` 只传 `offset` 时，该偏移被同时用于 stderr，增量续读 stdout 会**静默跳过等长 stderr 前缀** | `processes.py:read_output` 原实现 `stream_offset = ... else offset` | 改为 stderr 默认从 0 起（重复优于丢数据），并加回归测试 `test_exec_output_pages_streams_independently` |
| `env_info` 不暴露环境清单里的 `slurm.mock_backend`，Agent 无法自检有无 mock 后端 | 清单里有、`env_info` 没有 | 增加 `slurm_mock_backend` / `slurm_mock_available`，并加回归测试 |
| `docs/documentation-index.yaml` 的 `queries` 易被当成「可查内容的边界」，且无版本信息 | 子 Agent 指出查内存/时限类参数会漏 | 补 `version`（含 fork commit）与 `fork_notes`，注释说明 `queries` 只是入口 |
| `cosmo-doc-search` 的 `rg` 示例用 `"a|b"` 而非 `-e`；证据文件落盘位置与 `cosmo-exec` 的目录约定冲突 | 模式以 `-` 开头或含空格时失效；两处约定不一致 | 改用多个 `-e`；证据文件位置对齐到 `<data_dir>/<软件>/<任务名>-<日期>/documentation-evidence.md` |

`MaxMemSize` 的内存校验点在 `mymalloc.cc:check_maxmemsize_setting`（`/dev/shm` 容量取自
`system.cc:report_free_size_in_tmpfs`）——`docs/verification.md` 的表述正确，无需改动。

## HTTP 传输的 421：根因与修复（2026-09-16）

现象：经反向代理/隧道访问 `POST /mcp` 一律 `421 Invalid Host header`（不带 `Content-Type` 则 400）。

根因在 SDK，不在隧道：`mcp/server/fastmcp/server.py:178` ——

```python
if transport_security is None and host in ("127.0.0.1", "localhost", "::1"):
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"], ...)
```

即**绑定回环地址时自动开启** DNS-rebinding 保护，只放行回环名。代理/隧道转发时保留的是客户端
看到的 Host（如 `mcp.example.org`），于是被判为伪装请求。

修复（`mcp_server/src/cosmo_exec/server.py`）：新增 `build_transport_security()` 与三个启动开关，
**纯 opt-in，不给开关时行为与之前逐字节一致**：

| 开关 | 效果 |
|---|---|
| `--allowed-host HOST`（可重复）/ `COSMO_EXEC_ALLOWED_HOSTS` | 保留 Host/Origin 校验，额外放行这些前端名；裸域名自动含 `:*` |
| `--allowed-origin ORIGIN`（可重复） | 浏览器客户端场景 |
| `--no-dns-rebinding-protection` | 关掉 Host/Origin 校验（仅限可信私网）；与上面两者互斥 |

回归测试（`mcp_server/tests/test_regressions.py`）在**真实 HTTP 服务进程**上验证：

| 场景 | 期望 | 实测 |
|---|---|---|
| 无开关 + `Host: tunnel.example.com` | 421 | 421 ✓ |
| 无开关 + `Host: 127.0.0.1:8831` | 200 | 200 ✓ |
| `--allowed-host tunnel.example.com` + `Host: tunnel.example.com:443` | 200 | 200 ✓ |
| 同上 + `Host: evil.example.com` | 仍 421 | 421 ✓ |
| `--no-dns-rebinding-protection` + 无 `Content-Type` | 400（协议层校验仍在） | 400 ✓ |

端口绑定在沙箱内被禁，故这三个测试在沙箱内 `skipTest` 并提示需提权；提权后实跑全过。

## 回归结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 执行层冒烟 | `python3 mcp_server/tests/smoke_client.py` | 15 passed, 0 failed |
| 回归测试 | `python3 -m unittest mcp_server.tests.test_regressions` | 15 tests OK（含 4 个新增：3 个 HTTP Host 头 + 1 个策略对象） |
| Skill 结构 | `python3 scripts/check_skills.py` | 6 skills checked, 0 problem(s) |
| Skill 端到端 | `python3 mcp_server/tests/e2e_skill.py --transport http --port 8790` | ALL PASS（37 s，用的是新版检查脚本） |

## 仍未闭合

1. **客户端原生挂载未在会话内验证**：本机已执行 `codex mcp add cosmo-exec …`（写入
   `~/.local/share/codex/config.toml`），但 MCP 只在客户端启动时加载——**已运行的会话及其子 Agent
   看不到新工具**，需重开会话才能验证原生挂载路径。本轮子 Agent 测试走的是 shell 桥接。
2. **真实 Slurm**：仍无集群可验（见 `docs/verification.md`）。
3. `hbtplus` SKILL.md 引用的 `scripts/*.py` 位于仓库根而非 Skill 内（`check_skills.py` 会告警），
   语义正确但路径约定不统一，待统一。
