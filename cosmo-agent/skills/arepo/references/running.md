# Arepo 运行与 restart

来源：Arepo userguide running.html（https://arepo-code.org/wp-content/userguide/running.html）。

## 命令行

```
mpirun -np N ./Arepo <param.txt> [RestartFlag] [SnapNum]
```

| RestartFlag | 动作 |
|---|---|
| 0（缺省） | 从 InitCondFile 开始 |
| 1 | 从 restart 文件恢复（**rank 数必须相同**） |
| 2 | 从 snapshot 恢复（`./Arepo param.txt 2 7`，可换 rank 数，官方不推荐除非不得已） |
| 3 | 后处理：FOF/Subfind |
| 6 | snapshot 格式转换 |
| 14 | 输出 Voronoi 网格 |
| 17 | 流体梯度 |
| 18 | 引力势 |

（编号不连续是为了与开发版保持一致。）

## 中断与重提交

- `touch stop`（OutputDir 下）→ 写 restart 后优雅退出。
- `ResubmitOn 1` + `ResubmitCommand <脚本>`：到 TimeLimitCPU 自动写 restart 并执行重提交命令。
- `TimeLimitCPU`（秒）、`CpuTimeBetRestartFile`（秒）、`FlushCpuTimeDiff`（秒）。

## 输出与诊断

- snapshot：`OutputDir/snapdir_XXX/snap_XXX.*.hdf5`（SnapFormat 3）；格式与 Gadget 兼容。
- 诊断文件：`balance.txt cpu.txt domain.txt energy.txt info.txt memory.txt sfr.txt timebins.txt timings.txt`。
- FOF/Subfind 群目录格式与 GADGET 系列一致（userguide 明言）。

## MPI

- 纯 MPI（公开版无 OpenMP）；>10000 MPI task 规模已测试（userguide）。
- root/容器：`mpirun --allow-run-as-root`。
