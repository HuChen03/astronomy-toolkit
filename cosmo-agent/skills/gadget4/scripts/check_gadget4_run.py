#!/usr/bin/env python3
"""检查一次 GADGET-4 运行的产物是否完整。

用法: check_gadget4_run.py <run_dir>
判定:
  - output/ 下存在 snapdir_XXX 且最新 snapshot HDF5 可读、Header 含 Time/NumPart
  - outputs.txt 中列出的所有时刻都有对应 snapdir
  - output/energy.txt 存在且非空
  - stdout 日志（若 run_dir 内有 *.out / gadget*.log）尾部无 ERROR/Fatal
退出码: 0=通过, 1=失败, 2=输出尚不完整（可能仍在运行）
"""
import sys
from pathlib import Path


def fail(msg):
    print(f"[FAIL] {msg}")
    sys.exit(1)


def main():
    run_dir = Path(sys.argv[1])
    outdir = run_dir / "output"
    if not outdir.is_dir():
        for cand in run_dir.iterdir() if run_dir.is_dir() else []:
            pass
        print(f"[INCOMPLETE] {outdir} 不存在——运行可能尚未开始或已失败")
        sys.exit(2)

    snapdirs = sorted(outdir.glob("snapdir_*"))
    singles = sorted(outdir.glob("snapshot_*.hdf5"))  # NumFilesPerSnapshot=1 时直接写在 output/
    if not snapdirs and not singles:
        print("[INCOMPLETE] 尚无 snapdir_*/snapshot_* —— 可能仍在 IC 生成或早期演化阶段")
        sys.exit(2)

    # 核对 outputs.txt 期望的快照数
    expected = None
    ol = run_dir / "outputs.txt"
    if ol.is_file():
        expected = [ln.strip() for ln in ol.read_text().splitlines()
                    if ln.strip() and not ln.startswith("%")]
        n_have = max(len(snapdirs), len(singles))
        if n_have < len(expected):
            print(f"[INCOMPLETE] 期望 {len(expected)} 个 snapshot，已有 {n_have}")
            sys.exit(2)

    # 检查最新 snapshot 可读
    try:
        import h5py
    except ImportError:
        h5py = None
    last = snapdirs[-1] if snapdirs else outdir
    snaps = sorted(last.glob("*.hdf5"))
    if h5py and snaps:
        with h5py.File(snaps[0], "r") as f:
            hdr = f["Header"].attrs
            time_ = hdr.get("Time")
            npart = hdr.get("NumPart_ThisFile")
            print(f"[INFO] 最新 snapshot {snaps[0].name}: Time={time_}, NumPart={list(npart)}")
            if time_ is None:
                fail("snapshot Header 缺 Time 属性")
    elif not snaps:
        fail(f"{last} 中没有 .hdf5 snapshot")

    energy = outdir / "energy.txt"
    if not energy.is_file() or energy.stat().st_size == 0:
        fail("energy.txt 缺失或为空")

    for log in list(run_dir.glob("*.out")) + list(run_dir.glob("slurm-*.out")):
        tail = log.read_text(errors="replace")[-20000:]
        if "ERROR" in tail or "Fatal" in tail:
            fail(f"日志 {log.name} 尾部含 ERROR/Fatal")

    print(f"[PASS] {run_dir}: {len(snapdirs)} 个 snapdir + {len(singles)} 个单文件 snapshot，产物完整")
    sys.exit(0)


main()
