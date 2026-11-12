# cosmo-agent：让 Agent 使用四个宇宙学软件的系统

目标软件：**GADGET-4（GrGadget 分支）**、**Arepo（公开版）**、**HBT+**、**2LPTIC**。

## 架构

```
Agent 客户端
  │  读取 Skills（客户端侧，渐进式披露：frontmatter → SKILL.md → references/assets/scripts）
  │  MCP (stdio, 可经 ssh 包装到登录节点)
  ▼
cosmo-exec MCP server（运行在软件所在机器）
  │  11 个通用工具：file_read/file_write/file_list、exec_run/exec_start/exec_output/exec_stop、
│  （file_write 受 paths.protected 约束；exec_* 受服务端命令策略约束，拒绝与写入都记审计）
  │  run_list/run_get/run_attach_slurm、env_info
  ▼
原生 CLI：Gadget4 / Arepo / HBT / 2LPTic / mpirun / sbatch、squeue、sacct、scancel（Slurm）
```

设计原则（对应任务书）：

- **不为科学功能拆独立 MCP tool**，科学知识全部在 Skill；MCP 只做通用执行。
- **不重写软件 CLI**；Agent 经 MCP 调用原生 CLI 与原生 Slurm 命令。
- 访问边界（`allowed_roots`）、**命令策略**（灾难性命令拒绝表／可选白名单／shell 开关）、**受保护路径**（`file_write` 不写服务端自身代码与清单）、超时上限、输出截断都在**服务端强制**，Skill 只承载约定。
- 服务端留痕：每次执行一个 run 目录；`file_write` 与策略拒绝按行追加到 `<state_dir>/audit.jsonl`。
- 每次运行独立目录，保存配置/命令/版本/记录；执行账本（state_dir/runs/）跨 MCP 会话持久，断开后凭 run_id/slurm_job_id 继续追踪。
- 三类 ID 分离：MCP `run_id` ≠ 本地 `pid` ≠ Slurm `job_id`。

技术选型：自研轻量执行层（Python + 官方 `mcp` SDK 内置 FastMCP，stdio）。对比与依据见
`docs/research_mcp_skills.md`（DesktopCommanderMCP 为 Node/桌面导向、CLIO Kit 依赖过重，均只借鉴设计不复用代码）。

## 目录

| 路径 | 内容 |
|---|---|
| `mcp_server/` | cosmo-exec MCP 服务（src/cosmo_exec/：server/config/policy/processes/ledger/worker）、mock_slurm 模拟调度后端、tests/（冒烟+端到端+回归+策略） |
| `skills/` | cosmo-exec（共享执行约定）+ gadget4 / arepo / hbtplus / twolptic 四个软件 Skill |
| `scripts/` | 实验准备（`prepare_experiment.py`）、验收驱动（`run_acceptance.sh`）、Skill 校验（`check_skills.py`）、无原生挂载时的 MCP 桥接（`mcp_cli.py`） |
| `environments/local.yaml` | 从 `cosmo-agent/` 启动时使用的环境清单示例 |
| `patches/` | [原生软件版本与本地构建补丁](patches/README.md) |
| `sources/`、`runs/` | 本地准备的第三方源码、构建产物和运行目录 |
| `docs/` | 调研报告（三份，附来源）、安装与客户端配置、验证结果、Skill 验证（`skill-verification.md`） |

## 快速开始

见 [安装与客户端配置](docs/install_and_client.md)。从 `cosmo-agent/` 运行：

```bash
uv sync --project mcp_server --locked
uv run --project mcp_server --locked python mcp_server/tests/test_policy.py
uv run --project mcp_server --locked python mcp_server/tests/smoke_client.py
```

原生端到端测试需要先准备对应模拟软件、MPI 和测试输入。原环境的运行记录见 [验证文档](docs/verification.md)。
