# MCP 执行层与 Agent Skills 技术选型调研

调研日期：2026-09-10。目标系统：AI Agent 通过 MCP 执行科学软件 CLI（含 Slurm 作业管理），MCP server 运行在集群登录节点，Python 优先、依赖最小、工具少而通用。

## 1. DesktopCommanderMCP

来源：[GitHub README](https://github.com/wonderwhy-er/DesktopCommanderMCP)、[LICENSE (MIT)](https://raw.githubusercontent.com/wonderwhy-er/DesktopCommanderMCP/main/LICENSE)

- 技术栈：TypeScript/Node.js，通过 `npx @wonderwhy-er/desktop-commander` 分发，面向 Claude Desktop 等桌面客户端，stdio 传输。License：MIT。
- 工具清单（约 20 个）：
  - 终端/进程：`start_process`、`interact_with_process`（向运行中进程发输入）、`read_process_output`、`force_terminate`、`list_sessions`、`list_processes`、`kill_process`。
  - 文件系统：`read_file`（支持 URL、PDF、Excel，行/页分页，支持负偏移 tail）、`read_multiple_files`、`write_file`（rewrite/append）、`create_directory`、`list_directory`（递归，默认 depth=2）、`move_file`、`start_search`/`get_more_search_results`/`stop_search`（流式搜索会话）、`get_file_info`。
  - 编辑：`edit_block`（SEARCH/REPLACE 块，带模糊匹配回退）。
  - 配置与分析：`get_config`/`set_config_value`、`get_recent_tool_calls`、`get_usage_stats`。
- 进程管理：长时间命令超时后转后台，返回 PID/会话 ID，之后用 `read_output` 轮询、`force_terminate` 终止；支持交互式会话（SSH、REPL）。
- 截断/分页策略：进程输出 offset/length 分页；`fileReadLineLimit`（默认 1000 行）、`fileWriteLineLimit`（默认 50 行，强制小块写入）；目录递归列举有溢出保护；tool 历史上限 1000 条、单条输出截断 4 KiB。
- 安全限制（README 自称"不是沙箱"）：`blockedCommands` 命令黑名单、`allowedDirectories` 仅约束文件操作（终端命令不受限）、符号链接穿越防护；完整隔离需 Docker。其 SECURITY 说明承认黑名单可被绕过。
- 判断：
  - 值得借鉴：进程会话模型（启动→后台→轮询输出→终止）、输出分页与行数上限、审计日志、负偏移读文件。
  - 不适合直接复用：Node.js 运行时与项目 Python 优先矛盾；面向桌面客户端，含大量无关功能（Excel/PDF/DOCX、UI 预览、遥测）；在集群登录节点引入 Node + npx 自动更新是额外运维与安全负担；MIT 许可允许抄设计，但代码为 TS 无法直接嵌入。

## 2. CLIO Kit（IoWarp）

来源：[GitHub README](https://github.com/iowarp/clio-kit)、[slurm server README](https://github.com/iowarp/clio-kit/tree/main/clio-kit-mcp-servers/slurm)。PyPI：`clio-kit` 当前 2.10.6，Python ≥3.10，BSD-3-Clause。

- 22+ 个独立 MCP server（hdf5、slurm、pandas、parquet、plot、lmod、spack、arxiv…），`clio-kit mcp-server <name>` 以 stdio 启动，各 server 有独立 uv.lock 环境。
- Slurm server（契约 v3.0.0）默认 `user` profile 只暴露 5 个意图导向工具，而非一对一映射 Slurm CLI：
  - `slurm_submit`（单作业/数组，返回调度器原生 job ID）
  - `slurm_list`（按 user/state/partition 过滤）
  - `slurm_describe`（状态 + 调度详情 + 有界输出）
  - `slurm_cluster`（分区与队列状态，节点详情可选）
  - `slurm_cancel`（要求 `confirm_job_id` 精确匹配才执行，破坏性操作防呆）
  - 原有 13 个细粒度操作保留在 `--profile legacy`，`--profile admin` 全部开放；未知 profile 拒绝启动（fail closed）。另有 resource `slurm://cluster-info` 与 prompt `submit_job_workflow`。
- HDF5 server：27 个工具，如 `open_file`、`analyze_dataset_structure`、`read_partial_dataset`、`list_attributes`，带缓存/流式。
- 判断：
  - 值得借鉴：Slurm 工具的「意图导向 + 少而封闭 schema + 破坏性操作显式确认」设计，粒度合理，是本文推荐工具划分的主要参考。
  - 复用取舍：单个 server（如 slurm）理论上可通过 `uv tool install clio-kit` 单独跑，但会拖入整个发行版的启动器与锁定环境机制；其 `slurm_submit` 封装了 sbatch 脚本生成，与我们希望「脚本内容由 Agent 自己写、工具保持通用」的方向冲突。建议自研等价工具，不引依赖；HDF5/pandas 等数据 server 可作为后期按需挂接的可选项（独立进程、BSD 许可、即插即用，耦合度低）。

## 3. FastMCP

来源：[FastMCP 文档](https://gofastmcp.com/getting-started/welcome)、[quickstart](https://gofastmcp.com/getting-started/quickstart)、PyPI。

- 版本（PyPI，2026-09 查询）：`fastmcp` 4.0.3（要求 Python ≥3.10）；官方 SDK `mcp` 当前 2.2.0（本环境已装 `mcp` 1.27.0，其中已包含并入官方的 `mcp.server.fastmcp` 高层 API）。
- 与官方 SDK 关系：FastMCP 原创的高层 Python API 于 2024 年被并入官方 MCP Python SDK（`mcp.server.fastmcp`）；此后 FastMCP 由 Prefect 作为独立项目继续演进。注意 4.x 依赖链变为 `fastmcp → fastmcp-slim → mcp-types`，不再直接依赖 `mcp` 包（已按 PyPI 依赖元数据核实）。
- stdio server 最小写法：

  ```python
  from fastmcp import FastMCP

  mcp = FastMCP("My MCP Server")

  @mcp.tool
  def greet(name: str) -> str:
      return f"Hello, {name}!"

  if __name__ == "__main__":
      mcp.run()  # 默认 stdio；mcp.run(transport="http") 走 HTTP
  ```

- tool 注册：装饰器 `@mcp.tool`（4.x 文档中为无括号形式；带参数形式如 `@mcp.tool(app=True)`），从类型标注和 docstring 自动生成 schema 与校验；也可用 `fastmcp run server.py:mcp` CLI 启动（CLI 不执行 `__main__` 块）。
- 判断：用 FastMCP 自研是合理选择——API 极简、stdio 开箱即用、纯 Python。本实现采用官方 `mcp` 包内置的 `mcp.server.fastmcp`，不额外引入独立 fastmcp 发行版，依赖最少。

## 4. Agent Skills 规范

来源：[agentskills.io/specification](https://agentskills.io/specification)

- 目录约定：skill 是一个目录，最少包含 `SKILL.md`；可选 `scripts/`（可执行代码，需自包含并处理好错误）、`references/`（按需加载的文档，建议每文件聚焦一个主题）、`assets/`（模板、图片、数据文件）。
- `SKILL.md` = YAML frontmatter + Markdown 正文。frontmatter 字段：
  - `name`（必填）：≤64 字符，仅小写字母/数字/连字符，不能以连字符开头结尾、不能有连续连字符，且必须与父目录同名。
  - `description`（必填）：≤1024 字符，写清「做什么 + 何时用」，含触发关键词。
  - 可选：`license`、`compatibility`（≤500 字符，环境要求）、`metadata`（任意 string→string 映射）、`allowed-tools`（实验性，空格分隔的预批准工具，如 `Bash(git:*) Read`）。
- 渐进式披露（progressive disclosure）三层：① 启动时只加载所有 skill 的 name+description（约 100 token）；② skill 被激活时加载整个 SKILL.md 正文（建议 <5000 token、<500 行）；③ scripts/references/assets 仅在需要时读取。正文引用其他文件用相对路径、保持一层深度，避免深层嵌套引用链。
- 发现/加载机制：客户端启动扫描 skill 目录读取 frontmatter；校验可用参考实现 `skills-ref validate ./my-skill`。
- 对本项目的含义：Slurm/sbatch 用法、各科学软件的 CLI 手册精华、轮询脚本都应做成 skills 而非 MCP 工具——MCP 工具集保持小且稳定，领域知识走 SKILL.md 渐进披露。

## 5. Slurm CLI 程序解析要点

来源：[sbatch](https://slurm.schedmd.com/sbatch.html)、[squeue](https://slurm.schedmd.com/squeue.html)、[sacct](https://slurm.schedmd.com/sacct.html)、[scancel](https://slurm.schedmd.com/scancel.html) man page。

- `sbatch --parsable`：只输出 `jobID[;cluster]`（分号分隔）；错误仍走 stderr；退出码 0 成功、非 0 失败（man page 明确 "sbatch will return 0 on success or error code on failure"）。默认 stdout/stderr 写到 `slurm-%j.out`。
- `squeue`：
  - `-o/--format`（`%i %T %M %R` 等占位符）或 `-O/--Format`（全字段名，如 `JobID,State,TimeUsed,Reason`）；`-h/--noheader` 去表头；`-t/--states`、`-u/--user`、`--me`、`-j/--jobs` 过滤；`--json`/`--yaml` 可整体结构化输出。
  - 状态码（紧凑/扩展）：PD/PENDING、R/RUNNING、CG/COMPLETING、CD/COMPLETED、F/FAILED、CA/CANCELLED、TO/TIMEOUT、OOM/OUT_OF_MEMORY 等。
  - 注意：作业结束后很快从 squeue 消失，终态必须查 sacct。
- `sacct -j <jobid>`：
  - 程序解析首选 `-P/--parsable2`（`|` 分隔、无尾 `|`；`-p` 有尾随 `|`）+ `--format=JobID,JobName,State,ExitCode,Elapsed,Start,End,...` + `-n/--noheader`；`--delimiter` 可换分隔符；`--json` 亦可用。
  - `-X/--allocations` 只显示作业本身、不列出各个 step 行（否则每作业多行，需自行过滤 `.batch`/`.extern`）。
  - `ExitCode` 格式为 `exit:signal`（如 `0:0`、`1:0`、`0:9`）。
  - 默认时间窗口陷阱：不带 `-j`/`-s` 时 starttime 默认当天 0 点；带 `-j` 时从 Epoch 0 起。
- `scancel`：
  - 默认不发 `--signal` 时依次为 SIGCONT→SIGTERM→（slurm.conf `KillWait` 后）SIGKILL，给作业清理机会；`--signal=KILL` 只杀 step 不取消作业本体。
  - `-Q/--quiet`：作业已结束时不再报错（适合做幂等取消）。
  - 过滤式批量取消（`--state --user --partition` 等）建议加 `--ctld`，一次 RPC 完成，减轻 slurmctld 压力。
  - man page 未列出具体退出码数值，仅语义上 0=成功/非 0=失败（如 invalid job id）——数值细节**未核实**。
- 性能红线（squeue/sacct/scancel man page 均强调）：这些是发往 slurmctld/slurmdbd 的 RPC，禁止在循环里高频轮询；Agent 的轮询 skill 应内置退避间隔（如 ≥30s）并优先用 `sacct -j` 定点查询而非全队列扫描。

## 6. 结论与建议

**自研轻量 MCP 执行层，不复用 DesktopCommanderMCP / CLIO Kit 组件。** 理由：

1. 服务端必须在集群登录节点以用户身份运行：DesktopCommanderMCP 需要 Node.js/npx 且带自动更新与遥测，登录节点通常无外网、不宜引入；CLIO Kit 的 uv 锁定环境启动器对「只要 5 个工具」是过重依赖。两者许可（MIT / BSD-3）虽兼容，但语言（TS）与耦合面（桌面 UI、22 server 发行版）使直接嵌入得不偿失。
2. 工具数量要少而通用：DesktopCommanderMCP ~20 个工具中大半（Excel/PDF/搜索会话/编辑块）对本场景是噪声；CLIO Slurm 的 5 工具划分恰好证明「少量意图导向工具」可行，直接借鉴其划分即可。
3. Python 优先 + 依赖最小：FastMCP（或官方 `mcp` 包内置的 `mcp.server.fastmcp`）一个依赖即可写出全部工具；DesktopCommanderMCP 为 TypeScript 排除。
4. 可借鉴清单：DesktopCommanderMCP 的后台进程会话 + 输出分页 + 行数截断 + 审计日志；CLIO Slurm 的工具命名、`confirm_job_id` 防呆取消、有界输出；Agent Skills 的渐进式披露组织 Slurm/科学软件知识。

**Slurm 是否做专用包装 —— 取舍建议：默认不包装。** 用通用执行工具 + Skill 知识（sbatch `--parsable`、squeue `--format`/`--json`、sacct `-j -X -P --format=...`、scancel `-Q`）即可覆盖提交/查询/取消；SKILL.md 提供作业脚本模板与轮询脚本（scripts/，内置 ≥30s 退避）。若后续观测到 Agent 频繁拼错 sbatch 脚本或误取消作业，再按 CLIO 的 5 工具契约（含 `confirm_job_id`）追加 `slurm_submit/describe/cancel` 三个专用工具——该演进路径已被 CLIO v3 验证。

未核实项：scancel/squeue/sacct 的具体退出码数值（man page 未记载，仅 0/非 0 语义）；CLIO Slurm server 内部是否基于 FastMCP 实现（未读其源码）。
