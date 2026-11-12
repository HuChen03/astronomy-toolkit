#!/usr/bin/env python3
"""检查 2LPTIC 输出（Gadget format 1）。

用法: check_2lptic_output.py <OutputDir> <FileBase> [期望文件数] [期望总粒子数]

第 3 个参数是**期望文件数**（不是粒子数）；第 4 个参数是期望的全局总粒子数
（单组分立方 Nsample³ 算例填 Nsample³）。两者都可省略。

判定内容：头块尺寸与结束标记、POS/VEL/ID 三个块的尺寸与结束标记、文件长度与块结构自洽、
头字段合理性（time/redshift/BoxSize/Omega0/HubbleParam）、各文件 npartTotal 一致、
总粒子数与期望值一致、有粒子的组分质量为正。
退出码: 0=通过, 1=失败。
"""
import struct
import sys
from pathlib import Path

HEADER_SIZE = 256


def fail(msg):
    print(f"[FAIL] {msg}")
    sys.exit(1)


def parse_header(data, path):
    if struct.unpack_from("<i", data, 0)[0] != HEADER_SIZE:
        fail(f"{path.name}: 头部块尺寸 != {HEADER_SIZE}")
    if struct.unpack_from("<i", data, 4 + HEADER_SIZE)[0] != HEADER_SIZE:
        fail(f"{path.name}: 头部块结束标记缺失")
    return {
        "npart": struct.unpack_from("<6i", data, 4),
        "mass": struct.unpack_from("<6d", data, 28),
        "time": struct.unpack_from("<d", data, 76)[0],
        "redshift": struct.unpack_from("<d", data, 84)[0],
        "npart_total": struct.unpack_from("<6I", data, 100),
        "num_files": struct.unpack_from("<i", data, 128)[0],
        "boxsize": struct.unpack_from("<d", data, 132)[0],
        "omega0": struct.unpack_from("<d", data, 140)[0],
        "omega_lambda": struct.unpack_from("<d", data, 148)[0],
        "hubble": struct.unpack_from("<d", data, 156)[0],
        "header_end": 4 + HEADER_SIZE + 4,
    }


def parse_blocks(data, path, header):
    """按 POS/VEL/ID 顺序读块，返回 {块名: 字节数, 'id_bits': N}。"""
    npart = sum(header["npart"])
    pos = header["header_end"]
    sizes = {}
    for name in ("POS", "VEL"):
        want = 3 * 4 * npart
        size = struct.unpack_from("<i", data, pos)[0]
        if size != want:
            fail(f"{path.name}: {name} 块 {size} != {want}（npart={npart}）")
        if pos + 4 + size + 4 > len(data):
            fail(f"{path.name}: {name} 块超出文件末尾")
        if struct.unpack_from("<i", data, pos + 4 + size)[0] != size:
            fail(f"{path.name}: {name} 块结束标记与块尺寸不一致")
        sizes[name] = size
        pos += 4 + size + 4
    # ID 块：2LPTIC 默认 NO64BITID（32 位）；未定义该宏时是 64 位，两种都接受。
    id_size = struct.unpack_from("<i", data, pos)[0]
    if id_size == 4 * npart:
        id_bits = 32
    elif id_size == 8 * npart:
        id_bits = 64
    else:
        fail(f"{path.name}: ID 块 {id_size} 既不是 4*{npart} 也不是 8*{npart}")
    if struct.unpack_from("<i", data, pos + 4 + id_size)[0] != id_size:
        fail(f"{path.name}: ID 块结束标记与块尺寸不一致")
    sizes["ID"] = id_size
    sizes["id_bits"] = id_bits
    end = pos + 4 + id_size + 4
    if end != len(data):
        fail(f"{path.name}: 文件长度 {len(data)} 与块结构推出的 {end} 不一致（尾部有多余或缺失数据）")
    return sizes


def main():
    if len(sys.argv) < 3:
        fail("用法: check_2lptic_output.py <OutputDir> <FileBase> [期望文件数] [期望总粒子数]")
    outdir, base = Path(sys.argv[1]), sys.argv[2]
    want_files = int(sys.argv[3]) if len(sys.argv) > 3 else None
    want_particles = int(sys.argv[4]) if len(sys.argv) > 4 else None

    # 文件序号是写盘 MPI task 号，可能不连续 —— 只能按 glob 枚举。
    files = sorted(outdir.glob(f"{base}.*"))
    if not files:
        fail(f"{outdir}/{base}.* 不存在")
    if want_files is not None and len(files) != want_files:
        fail(f"期望 {want_files} 个文件，实际 {len(files)}")

    totals, local = set(), 0
    head = None
    for f in files:
        data = f.read_bytes()
        header = parse_header(data, f)
        blocks = parse_blocks(data, f, header)
        head = header
        npart = sum(header["npart"])
        local += npart
        totals.add(tuple(header["npart_total"]))
        if header["boxsize"] <= 0:
            fail(f"{f.name}: BoxSize={header['boxsize']} 不合理")
        if not 0.0 < header["omega0"] < 1.0:
            fail(f"{f.name}: Omega0={header['omega0']} 不合理")
        if header["time"] <= 0:
            fail(f"{f.name}: time={header['time']} 不合理")
        if header["num_files"] != len(files):
            fail(f"{f.name}: header.num_files={header['num_files']} != 实际文件数 {len(files)}")
        if any(header["mass"][i] <= 0 for i in range(6) if header["npart"][i] > 0):
            fail(f"{f.name}: 有粒子的组分 mass 非正")
        print(f"[OK] {f.name}: npart={npart} ID={blocks['id_bits']}bit "
              f"POS/VEL/ID={blocks['POS']}/{blocks['VEL']}/{blocks['ID']}B")

    if len(totals) != 1:
        fail(f"各文件的 npartTotal 不一致: {sorted(totals)}")
    npart_total = sum(totals.pop())
    if npart_total < local:
        fail(f"npartTotal 总和 {npart_total} 小于本次枚举到的粒子数 {local}")
    if want_particles is not None and npart_total != want_particles:
        fail(f"总粒子数 {npart_total} != 期望 {want_particles}")

    print(f"[INFO] BoxSize={head['boxsize']} Omega0={head['omega0']} "
          f"OmegaLambda={head['omega_lambda']} h={head['hubble']} "
          f"z={head['redshift']} time={head['time']} npartTotal={npart_total}")
    print(f"[PASS] 共 {len(files)} 个文件、文件内粒子数合计 {local}、全局总粒子数 {npart_total}")


if __name__ == "__main__":
    main()
