# HBT+ 运行、续跑与输出检查

来源：`sources/HBTplus/src/config_parser.cpp:161-183`、`HBTjob_mpi.slurm`、wiki。

## 运行

```
mpirun -np N ./HBT <param.conf> [snapshot_start] [snapshot_end]
```

- 只给 param：`MinSnapshotIndex`→`MaxSnapshotIndex` 全序列。
- 只给 start：只处理该快照。
- start+end：闭区间。
- MPI 版必须 mpirun；OpenMP 在 MPI 版默认关（需改 Makefile.inc 取消 OMPFLAG 注释重编译）。

## Slurm

模板 `assets/HBTjob_mpi.slurm`（源码自带），核心行：
`mpirun -np $SLURM_NTASKS ./HBTi8 configs/${SLURM_JOB_NAME}.conf $snapstart $snapend`

## 续跑

- 从 snapshot K 续跑：`./HBT conf K <MaxSnapshotIndex>`，前提是 `SubhaloPath/SrcSnap_{K-1}.hdf5` 等此前输出仍在。
- 断点续跑不需要额外开关——HBT+ 每处理完一个快照即落盘，崩溃后从上次的下一个快照续。

## 成功判定

- 每个快照处理完输出 `SubSnap_NNN.hdf5`（+ SrcSnap_NNN.hdf5）。
- stdout 无 ERROR/断言失败（HDF5 断言失败是 hdf5-1.12.0 已知 bug 的信号）。
- `scripts/check_hbt_output.py <SubhaloPath> <snap_index>`：验证 SubSnap HDF5 含 Subhalos 数据集与 TrackId 字段。
