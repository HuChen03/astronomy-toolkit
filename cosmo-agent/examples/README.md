# 最小示例（examples/）

两个端到端脚本即最小示例（经真实 MCP 客户端驱动真实软件）：

1. `mcp_server/tests/e2e_gadget4.py`
   读 skills/gadget4 模板 → file_write 参数到服务端 → 错误参数被拒（软件日志判定）
   → exec_start 跑 GADGET-4 短程算例（128³，a→0.02，约 10 分钟）→ 输出检查
   → mock-Slurm 提交 2LPTIC 作业并追踪终态。
2. `mcp_server/tests/e2e_arepo_2lptic.py`
   Arepo 孤立星系算例（IC 随源码）+ 2LPTIC 经 MCP 复跑并与直接 CLI 输出逐字节对比。

更快的纯执行层验证：`mcp_server/tests/smoke_client.py`（约 40 秒，15 项检查）。

手工最小命令序列（在服务端机器上直接验证软件，不经 MCP）：

```bash
# 2LPTIC（秒级）
cd runs/twolptic/manual && mkdir -p output
python3 skills/twolptic/scripts/make_grid_glass.py glass.dat 1.0
cp skills/twolptic/assets/2LPT-small.param 2LPT.param
mpirun -np 2 sources/2lptic/2LPTic 2LPT.param   # 看到 "IC's generated." 即成功
python3 skills/twolptic/scripts/check_2lptic_output.py output ics 2
```
