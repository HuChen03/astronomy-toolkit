# 安装、启动与客户端配置

## 1. 服务端（软件所在的机器：集群登录节点或工作站）

```bash
cd cosmo-agent
uv sync --project mcp_server --locked
# 原生工作流中的 HDF5 处理脚本和回归测试使用 --extra simulation。
```

配置环境清单（复制并按站点修改）：

```bash
cp environments/local.yaml environments/site.yaml
# 必填：paths.allowed_roots（服务端强制的文件访问边界）、paths.state_dir
# 建议填：software.* 的二进制路径与 commit、slurm.partitions、mpi.*
```

启动（stdio，由 MCP 客户端拉起；也可手动测试）：

```bash
uv run --project mcp_server --locked cosmo-exec-mcp --env environments/site.yaml
# 等价环境变量：COSMO_ENV_MANIFEST / COSMO_EXEC_STATE_DIR / COSMO_EXEC_ALLOWED_ROOTS（冒号分隔）
```

清单里的相对路径以服务进程的工作目录为基准。随附示例从 `cosmo-agent/` 启动，远程客户端配置可改用服务器绝对路径。原生软件的版本与补丁见 [patches/README.md](../patches/README.md)。

### 1.1 exec 策略、受保护路径与审计（服务端强制）

三者都是**服务端**配置，客户端无法绕过；改完重启服务生效。

```yaml
# environments/<site>.yaml
paths:
  allowed_roots: [...]        # 约束「在哪里跑」
  protected:                  # file_write 拒绝写入的路径；服务端代码/清单/审计日志已自动保护
    - <root>/environments
    - <root>/mcp_server
    - <root>/sources
exec:
  allow_shell: true               # false = 完全禁止 shell=true（只能传 argv 数组）
  builtin_deny_patterns: true     # 内置拒绝表；唯一能整表关掉它的开关
  disabled_deny_patterns: []      # 按名字停掉某几条内置规则（名字见 env_info.exec_policy.deny_patterns）
  deny_patterns: []               # 在内置表之上【追加】自定义正则；空列表不会关掉内置表
  allow_commands: []              # 支持绝对路径，命令名按服务端 PATH 解析，禁用 shell=true
  allow_env: []                   # 白名单模式下允许追加的作业环境变量名
```

- **命令策略**（`mcp_server/src/cosmo_exec/policy.py`）：`exec_run`/`exec_start` 在创建任何进程之前过一遍
  拒绝表——删根／删系统目录、`mkfs`、`dd of=/dev/…`、提权、`curl|sh`、fork bomb 等。它能穿透
  `sudo nice xargs rm -rf /` 这类包装，也会单独扫描 `bash -c "…"` 里的脚本；命中即报
  `PermissionError` 并写审计，**不会**留下 run 目录（拒绝发生在建目录之前）。
- **不是沙箱**：文本匹配拦不住运行期拼字符串（`python3 -c "import shutil; shutil.rmtree('/')"`）。
  真正的隔离靠低权限账号／容器与文件系统权限；`exec_run` 继承服务账号的全部 OS 权限。
- **受保护路径**：`file_write` 在 `allowed_roots` 之外再查一遍，命中报 `PermissionError` 并记
  `file_write_denied` 审计；`file_read`/`file_list` 不受影响（读源码用于排障仍然可以）。
- **审计**：文件写入与策略拒绝按行追加到 `<state_dir>/audit.jsonl`（JSON Lines，含时间戳／pid／事件）；
  `env_info` 返回 `audit_log`、`exec_policy`、`protected_paths` 便于核对。
- **运行账本**：客户端环境变量只记录变量名，值统一显示为 `[redacted]`。在白名单模式下可传入线程数等
  作业参数，`PATH`、加载器和 Python 启动相关变量由服务端控制。原始元数据和审计日志由运维账号直接读取。
- **停止状态**：`exec_stop` 的 `signal_sent` 表示已发出信号，`stopped` 表示进程组已退出。
  等待超时后可继续用 `run_get` 或 `run_list` 查询。Slurm 任务仍以调度器状态为准。
- **误报怎么放行**：内置规则的名字会出现在报错与 `env_info.exec_policy.deny_patterns` 里，让用户在清单
  `exec.disabled_deny_patterns` 里点名停掉那一条即可（不是放宽整表）；整表关闭只能靠显式的
  `builtin_deny_patterns: false`。
- **CLI 覆盖**（便于写进 systemd/supervisor）：`--deny-pattern REGEX`（追加）、
  `--disable-deny-pattern NAME`、`--no-builtin-deny-patterns`、`--allow-command NAME`、`--no-shell`、
  `--protected-path PATH`。

## 2. 客户端配置

HTTP 绑定非回环地址时，服务进程需要从部署环境读取 `COSMO_EXEC_HTTP_TOKEN`，
客户端需发送 `Authorization: Bearer …`。经反向代理发布时使用 HTTPS。共享一个执行服务的客户端共享
同一 OS 权限及账本。跨信任边界使用独立服务实例、低权限账号与文件系统隔离。

支持 MCP 的 Agent 客户端（Claude Code / Desktop、Kimi Code 等）注册：

```json
{
  "mcpServers": {
    "cosmo-exec": {
      "command": "ssh",
      "args": ["<login-node>", "/path/to/cosmo-agent/mcp_server/.venv/bin/python3",
               "-m", "cosmo_exec.server", "--env", "/path/to/cosmo-agent/environments/mysite.yaml"]
    }
  }
}
```

若 Agent 就在服务端机器上，去掉 ssh 包装，command 直接是 python3。
**路径语义**：MCP 工具收到的一切路径都是服务端路径；客户端本地路径不可直接用。

### 2.1 本机 Codex CLI 注册

```bash
codex mcp add cosmo-exec -- uv --directory "$PWD" run --project mcp_server --locked \
  cosmo-exec-mcp --env environments/site.yaml
codex mcp list        # 应显示 cosmo-exec / enabled
```

从 `cosmo-agent/` 运行这条命令，`$PWD` 会记录为服务工作目录。
**注册只在客户端启动时读取**：注册后已运行的会话（含它派生的子 Agent）看不到新工具，
必须重开会话才挂载。

### 2.2 无原生挂载时的 shell 桥接 `scripts/mcp_cli.py`

Agent 客户端尚未挂载 MCP（或需要脚本化调用/CI）时，用桥接以**同一套工具、同一套参数与返回值**
访问同一个 MCP 服务，避免为此重写一套 API：

```bash
python3 scripts/mcp_cli.py --list-tools                       # 11 个工具
python3 scripts/mcp_cli.py env_info
python3 scripts/mcp_cli.py file_list path=runs
python3 scripts/mcp_cli.py exec_run '{"argv":["rg","-n","OutputListOn","sources/Gadget4/documentation"],"cwd":"."}'
# 附着到已在运行的 HTTP 服务（不新起进程、不占用端口）
python3 scripts/mcp_cli.py --url http://127.0.0.1:8787/mcp env_info
# 连接需要认证的服务，令牌取自当前进程环境。
python3 scripts/mcp_cli.py --url https://mcp.example.org/mcp --token-env COSMO_EXEC_HTTP_TOKEN env_info
```

参数给 JSON 对象、`key=value` 对，或 `-`（从 stdin 读 JSON）；非合法 JSON 的值按字符串处理。
默认 stdio 模式会自动拉起一个服务端进程；`--url` 附着到已有实例，适合长跑服务共享。

### 2.3 经反向代理 / 隧道访问 HTTP 传输（Host 头与 421）

FastMCP 的 DNS-rebinding 保护**在绑定回环地址时自动开启**，只放行
`127.0.0.1:*` / `localhost:*` / `[::1]:*`。代理、隧道、跳板转发时保留的是**客户端看到的 Host**
（例如 `mcp.example.org`），因此一律被拒：

```
POST /mcp  ->  421 Invalid Host header      （Content-Type 缺失则是 400，协议层校验，另算）
```

两种解法（只需改 cosmo-agent 服务端启动参数，不必改隧道/nginx）：

```bash
# 1) 点名前端域名：仍保留 Host/Origin 校验，只额外放行这些名字
python3 -m cosmo_exec.server --env environments/local.yaml \
  --transport streamable-http --host 127.0.0.1 --port 8080 \
  --allowed-host mcp.example.org        # 可重复；不带端口号即允许任意端口

# 2) 关掉 Host/Origin 校验：仅用于私网/可信网络内的服务
python3 -m cosmo_exec.server --env environments/local.yaml \
  --transport streamable-http --host 127.0.0.1 --port 8080 --no-dns-rebinding-protection
```

要点：

- **不给这两个开关 = 行为与以前完全一致**（回环绑定自动保护），改动是纯 opt-in。
- 裸主机名会自动同时放行 `host` 与 `host:*`；要精确匹配端口写 `host:8080`。
- 也可用 `--allowed-origin`（浏览器客户端）；或环境变量
  `COSMO_EXEC_ALLOWED_HOSTS="a.example,b.example:8080"`（逗号分隔），便于写进 systemd/supervisor 配置。
- `--no-dns-rebinding-protection` 与 `--allowed-host/--allowed-origin` 互斥，同时给会直接报错退出。
- **关掉 DNS 保护不等于关掉协议校验**：POST 仍必须带 `Content-Type: application/json`（否则 400）。
- 关掉保护后服务端不再校验 Host，**任何能连到该端口的人都能调用全部工具**（含 `exec_run`）。
  只在私网/隧道后面这样部署，不要把端口直接暴露到公网。

## 3. Skills 的发现与加载

Skills 在**客户端**：把 `cosmo-agent/skills/` 加入客户端的 skill 目录（各客户端机制不同：
Claude Code 用 `.claude/skills/` 或 `--add-dir`；规范见 https://agentskills.io/specification）。
客户端启动时只读各 SKILL.md 的 frontmatter（name+description）；任务匹配时加载正文；
references/assets/scripts 由 Agent 按需读取。

Codex CLI 扫描的是文件系统，没有 `codex skills` 子命令：**Skill 必须出现在
`$CODEX_HOME/skills/<name>/SKILL.md`**（`CODEX_HOME` 默认 `~/.local/share/codex`）。用符号链接安装
（本机已执行，改动仓库即生效，撤销用 `rm`）：

```bash
cd cosmo-agent
for s in arepo cosmo-doc-search cosmo-exec gadget4 hbtplus twolptic; do
  ln -sfn "$PWD/skills/$s" "$CODEX_HOME/skills/$s"
done
ls -l "$CODEX_HOME/skills/"          # 6 个软链指向本仓库
```

两条自检（都不调用模型）：

```bash
# 1) 发现层：Skill 是否真的进了本会话的提示词（应列出 6 个 cosmo-* 名字）
codex debug prompt-input | sed 's/\\n/\n/g' | grep -oE '^- [a-z0-9-]+:' | sort -u

# 2) 结构层：frontmatter/name/路径引用是否合规
python3 scripts/check_skills.py            # 期望 "6 skills checked, 0 problem(s)"
```

要点：

- **加载时机**：客户端启动时只读 frontmatter（`name` + `description`）做匹配，命中任务才加载正文。
  因此**新装/改动 Skill 后必须重开会话**（含它派生的子 Agent）才可见。
- **`name` 必须等于目录名**（小写连字符），`description` 写清「何时用」——匹配质量全靠它。
- `$CODEX_HOME/skills/.system/` 是内置 Skill 根（imagegen、openai-docs 等），不要往里放本项目内容。
- 其它客户端路径不同：Claude Code 用 `~/.claude/skills/`（或项目 `.claude/skills/`、`--add-dir`）；
  规范见 https://agentskills.io/specification。SKILL.md 本身是跨客户端通用的。

**Skill 文件到达远端的机制**：Agent 用 `file_read` 读客户端侧模板/脚本 → 改写 →
`file_write` 写到服务端运行目录后执行。assets/ 中的参数模板、作业脚本从不直接在服务端出现。

## 4. 无 Slurm 环境的流程测试

环境清单 `slurm.mock_backend` 指向 `mcp_server/mock_slurm/bin`（sbatch/squeue/sacct/scancel/sinfo
的模拟实现，作业立即本地后台执行）。用法见 `skills/cosmo-exec/references/slurm-workflow.md` §7。
**该后端仅验证 Agent 的提交/查询/取消流程，不代表真实集群。**

## 5. 扩展一个新软件

1. 在 `skills/` 新建目录（目录名=SKILL.md 的 name 字段，小写连字符）。
2. SKILL.md 写适用任务、功能导航表、标准流程、执行约定；详细内容拆到 references/。
3. assets/ 放带来源注释的参数模板与作业脚本；scripts/ 放输出检查脚本。
4. 在环境清单 `software:` 下登记路径、commit、构建状态。

## 6. 故障排查

| 症状 | 排查 |
|---|---|
| 工具报 "outside allowed_roots" | 路径越界：把运行目录放到清单 allowed_roots 之下，或加根 |
| `exec_run` 报 "rejected by the server policy rule ..." | 命中命令拒绝表（原因见括号内的匹配片段）。确认命令合理后请用户调 `exec.deny_patterns`，或改用 argv 形式；不要改写命令绕过 |
| `file_write` 报 "inside the protected path ..." | 目标在 `paths.protected`（或服务端代码／清单／审计日志）里：运行产出写到 `runs/` 等运行目录，或请用户调整 protected |
| exec_run 超时但任务没完 | 超时上限 3600s；长任务用 exec_start 或 Slurm |
| mpirun 拒绝 root 运行 | 加 `--allow-run-as-root` 或设 `OMPI_ALLOW_RUN_AS_ROOT(_CONFIRM)=1` |
| Slurm 提交后 squeue 查不到 | 正常：结束即消失；用 `sacct -j <id> -X -P -n --format=...` 查终态 |
| MCP 断开后找不到作业 | `run_list` 找回 run 记录（含 slurm_job_id），或看 `state_dir/runs/` |
| HTTP 传输经代理/隧道后一律 421 `Invalid Host header` | 见 §2.3：加 `--allowed-host <前端域名>`（裸名字自动含任意端口），或 `--no-dns-rebinding-protection` |
| 脚本化客户端调用偶发无响应 | mcp 1.27 stdio 已知问题：响应对丢失、服务端空闲。脚本必须用超时+重试包装（`mcp_server/client_helpers.py` 的 `mcp_call`） |
| Gadget4 缺参数报错 "I miss a value" | 该 fork 必填参数比官方多（如 SamplingCorrection），见 gadget4 Skill |
| Gadget4 启动即 `insufficient memory`（提到 `*shared* memory`） | `/dev/shm` 太小：需 `N_rank × MaxMemSize ≤ /dev/shm 可用量`（本机 16 GB）。按预算配 rank 数（8×1800 / 16×900），或申请扩容 `/dev/shm` |
| FoF 目录全空、日志 `FOF groups with at least 32 particles: 0` | 分辨率不足：FoF 最小群大小为 32 个粒子（默认 `FOF_GROUP_MIN_SIZE`）。看同日志的 `Marked=N ... linked` 是否非 0 来区分「连接失败」与「群太小被丢弃」 |
