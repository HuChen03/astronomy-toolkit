---
name: cosmo-exec
description: 通过 cosmo-exec MCP 服务器在远端（集群登录节点/工作站）执行科学软件 CLI 的通用约定。当需要读/写远端文件、运行命令、管理后台进程、提交或追踪 Slurm 作业时使用。所有宇宙学软件 skill（gadget4、arepo、hbtplus、twolptic）都遵循本文件的执行约定。
metadata:
  layer: execution
  mcp_server: cosmo-exec
---

# cosmo-exec 执行约定

## 心智模型

- MCP server **运行在软件所在的机器上**（集群登录节点或工作站）。所有路径都是**服务端路径**；客户端本地路径对服务端无意义，不要把本地路径传给它。
- 客户端安装的 Skill 是导航；服务端可检索文档的位置由 `env_info.documentation` 给出。
  本项目在服务端部署了一份 references/assets/scripts，可通过服务端 `file_read` 或原生 grep/rg 读取。
  如果只在客户端有文件，应使用客户端本地读取能力再以 `file_write` 上传，不能把客户端路径传给服务端 `file_read`。
- 三个不同的 ID，不要混淆：
  - `run_id`：MCP 服务端账本中的执行记录 ID（形如 `20260910-123000-ab12cd34`），用于查后台进程输出。
  - `pid`：run 记录 `meta.pid` 里的**supervisor 进程**（`worker.py`）的 OS 进程号——**不是**你那条命令自己的 pid。
    命令是它的子进程，与它同属一个进程组；记录里带 `supervisor: true`。要按 pid 查进程请整组查
    （`ps -o pid,pgid,args --ppid <pid>` 或按 pgid），只 `ps -p <pid>` 会看到 supervisor 而不是你的命令。
  - Slurm `job_id`：调度器分配的作业号（`sbatch --parsable` 输出），提交后用 `run_attach_slurm` 挂到提交命令的 run_id 上。

## 客户端接入（先确认你属于哪种）

**先看自己的工具清单里有没有 `env_info`**：

- **有** → MCP 已原生挂载，直接用，跳过本节。
- **没有** → 用项目自带的桥接，以**同一套工具名、参数与返回值**访问同一个服务端：

  ```bash
  python3 scripts/mcp_cli.py --list-tools                       # 列 11 个工具
  python3 scripts/mcp_cli.py --url http://127.0.0.1:8787/mcp env_info
  python3 scripts/mcp_cli.py --url http://127.0.0.1:8787/mcp exec_run \
      '{"argv":["rg","-n","OutputListOn","sources/Gadget4/documentation"],"cwd":"."}'
  ```

  参数给 JSON 对象或 `key=value` 对。默认 stdio 模式自起一个服务端进程（启动约 20 s）；
  `--url` 附着到已在运行的实例更快，长跑服务共享一个实例即可。**桥接只是传输层**——
  下面所有执行约定、判定标准完全照旧。
- 给客户端注册：`codex mcp add cosmo-exec -- <python> -m cosmo_exec.server --env <manifest>`；
  **注册只在客户端启动时读取**，已运行的会话（含它派生的子 Agent）看不到新挂载的工具，必须重开会话。
- HTTP 传输经反向代理/隧道访问时返回 `421 Invalid Host header`：代理保留的是前端 Host，而服务端
  默认只放行回环名。**让用户**在启动参数上加 `--allowed-host <前端域名>`（裸域名自动含任意端口）
  或 `--no-dns-rebinding-protection`（可信私网），详见 `docs/install_and_client.md` §2.3。
  不要试图用伪造/双 Host 头绕过——按 Host 路由的前端会先把你 404 掉。

**同机 vs 异机**：服务端与客户端在**同一台机器/同一文件系统**时，客户端 Skill 目录里的 `scripts/`、`assets/`
服务端可以直接 `file_read`/`exec_run` 读到（内容与仓库一致）；只有在**真·远端**（ssh 到登录节点）时，
才必须走「客户端读 → `file_write` 上传 → 服务端执行」。先看 `env_info.hostname` 是否就是本机。

## MCP 工具（共 11 个）

文件：`file_read`（分页，`next_offset`）、`file_write`（overwrite/append，单次 ≤4 MiB）、`file_list`。
执行：`exec_run`（前台，默认超时 300 s，上限 3600 s；优先 `argv` 数组；只有需要管道/重定向/`module load` 时才用 `shell=true`+`command`）、`exec_start`（后台）、`exec_output`（增量读）、`exec_stop`（默认 SIGTERM 进程组，可传 `sig` 换信号）。
账本：`run_list`、`run_get`、`run_attach_slurm`。
环境：`env_info`（主机、CPU/内存、Slurm/MPI 可用性与 `slurm_mock_backend`、allowed_roots、环境清单摘要）。

返回值约定：退出码、`stdout`/`stderr`（截断时带 `truncated: true` 和 `total_bytes`，全文永远在日志文件里，用 `file_read` 分页读）、`log_files` 路径。后台任务以 `run_id` 追踪。

**实测细节（踩过坑，按此使用）**

- `exec_run` / `exec_start` 的 `cwd` **必须已存在**且位于 `allowed_roots` 内，不会自动创建；
  默认 cwd 是 allowed_root 而不是你的运行目录 —— 用相对路径的软件（如 2LPTIC 的 `./output`）
  必须显式传 `cwd`，或先用 `exec_run mkdir -p`。
- `shell=true` 时账本里记的 `argv` 会被改写成 `["bash","-c",command]`，不再是原始命令行；
  `command.txt` 里要自己留一条真实命令。
- `exec_output` 的分页是**每条流独立**的：`offset` 只作用于 stdout；stderr 从 `stderr_offset` 起，
  不传则从 0 起（每次都会重放，重复比丢数据安全）。返回的 `{stream}_info` 里有
  `total_bytes` / `offset` / `next_offset` / `eof`；传越界 `offset` 会被**静默夹到文件末尾**，不报错。
- 被信号终止的进程，`exit_code` 是**负的信号号**（SIGTERM → `-15`），不是 143，也不代表"出错"。
- `status` 表示本地进程状态。可能值为 `running`、`stopping`、`exited`、`timed_out` 和 `unknown`。
  已提交的 Slurm 作业状态用 `squeue` 或 `sacct` 查询。
- `exec_stop` 最多等待约 10 秒。`signal_sent` 表示已发信号，`stopped` 表示确认进程组退出。
  等待超时或身份无法校验时，继续用 `run_get` 或调度器核对。
- `run_list` 默认 `limit=20`、上限 200，且账本**跨客户端共享**（同机多个 Agent 会互相把记录挤出前列）。
  找回旧作业时显式放大 `limit`，再按 `run_id`/`cwd` 过滤，不要只取默认页。

## 标准任务流程

1. `env_info` 确认环境（Slurm 是否可用、allowed_roots）。
2. 按 `cosmo-doc-search` 检索对应版本的服务端文档，记录关键参数的依据；读取已部署的模板，改写后 `file_write` 到独立运行目录。
3. **每次运行一个独立目录**：`<data_dir>/<软件>/<任务名>-<日期>/`，里面保存参数文件、作业脚本、`command.txt`（实际执行的命令）、程序版本/commit。
4. 短任务（几分钟内）直接 `exec_run`；长任务用 Slurm（见 `references/slurm-workflow.md`），无 Slurm 时用 `exec_start` 后台跑。
5. 判断成功**必须看软件自身输出/日志标志**，不能只看退出码（MPI 程序常在出错时也返回 0 或以 1 退出但部分输出已生成）。各软件 Skill 的 `scripts/` 提供检查脚本。

## Slurm 要点（详见 references/slurm-workflow.md）

- 提交：`sbatch --parsable job.sh` → 第一行即 job_id。提交响应丢失时：**先 `squeue --me -o '%i %j %T'` 和 `sacct -X -P -n --format=JobID,JobName,State` 核查是否已提交**，再决定是否重提，避免重复提交。
- 队列里查不到 ≠ 成功：结束后作业很快从 squeue 消失，终态必须 `sacct -j <id> -X -P -n --format=JobID,State,ExitCode`。
- 轮询间隔 ≥30 s（squeue/sacct 是 RPC，禁止高频轮询）。可用 `scripts/wait_slurm_job.sh`。
- 取消：`scancel <job_id>`（幂等用 `scancel -Q`）。
- MCP 断开后：`run_list` 找回提交记录（含 slurm_job_id），凭 job_id 继续用 sacct/日志追踪。
- 无真实 Slurm 的测试环境：环境清单里的 `slurm.mock_backend` 提供同名 CLI 的模拟实现（本地立即执行）。**通过模拟后端 ≠ 真实集群验证**。

## 访问与资源边界

- `allowed_roots` 限制文件接口和命令 cwd；任意 CLI 仍继承服务账号的操作系统权限，不是进程文件系统沙箱。
- **命令策略**：`exec_run`/`exec_start` 在建进程前过服务端拒绝表（删根/系统目录、`mkfs`、`dd of=/dev/…`、
  提权、`curl|sh` 等），命中直接 `PermissionError` 并写审计、不建 run 目录。**被拒时不要改写命令绕过**，
  先向用户说明，并询问是否在清单 `exec.disabled_deny_patterns` 里点名停掉那条规则。
- **受保护路径**：`file_write` 拒绝写服务端自身代码、环境清单、审计日志与清单里的 `paths.protected`
  （如 `environments/`、`mcp_server/`、`sources/`）；运行产出写到 `runs/` 等运行目录。
- **审计**：文件写入与策略拒绝记在 `<state_dir>/audit.jsonl`；`env_info` 返回 `audit_log`/`exec_policy`/`protected_paths`。
- 超时上限、输出截断上限由服务端落实；长时间计算一律走 Slurm，不要在登录节点用后台进程跑生产计算。

## 长任务与断连

本机长任务测试使用 HTTP MCP；stdio 保留为默认客户端入口，但本环境曾观测到长会话响应延迟。
不能把响应超时等同于命令未执行。`exec_start`、`exec_run`、`file_write` 不自动重试；先核对运行账本。
后台任务由独立 supervisor 写 `result.json`，新服务会话可恢复退出码；旧版无 supervisor 的记录仍可能只有未知退出状态。
stdout 与 stderr 分别保存分页偏移；`exec_output` 可传 `stderr_offset`，避免错过较短的错误日志。
