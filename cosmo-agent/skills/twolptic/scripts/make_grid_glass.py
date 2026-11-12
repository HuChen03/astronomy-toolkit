#!/usr/bin/env python3
"""生成 2LPTIC 用的「网格起点」glass 文件（Gadget format 1，仅 POS 块）。

原理：2LPTIC 把 glass 在三个方向各平铺 GlassTileFac 次。用 1 粒子 glass
+ GlassTileFac=Nsample 即得到规则网格起点（等价于 N-GenIC 的 grid 起点；
源码注释：CORRECT_CIC 仅对真正 glass 起点需要，网格起点不用开）。

用法: make_grid_glass.py <输出文件> [boxsize=1.0]
粒子位置放在 cell 中心 (0.5,0.5,0.5)*boxsize，类型 1（DM）。
"""
import struct
import sys

path = sys.argv[1]
box = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0

# Gadget format-1 header（256 字节）
npart = [0, 1, 0, 0, 0, 0]
mass = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0]
hdr = struct.pack("<6i6d2d2i6i2i4d2i6i2i",  # 见下：手工对齐到 256
                  *npart, *mass, 0.0, 0.0, 0, 0, *npart, 0, 1,
                  box, 0.0, 0.0, 1.0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
assert len(hdr) <= 256
hdr = hdr.ljust(256, b"\0")

pos = struct.pack("<3f", 0.5 * box, 0.5 * box, 0.5 * box)

with open(path, "wb") as f:
    f.write(struct.pack("<i", 256))
    f.write(hdr)
    f.write(struct.pack("<i", 256))
    f.write(struct.pack("<i", 12))
    f.write(pos)
    f.write(struct.pack("<i", 12))
print(f"written {path}: 1-particle grid glass, box={box}")
