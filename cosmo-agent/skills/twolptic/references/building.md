# 2LPTIC 编译指南（Ubuntu 22.04 实测，2026-09-10）

来源：官方 `2LPTic.tar.gz` 内 Makefile + 本仓库实测。

## 依赖

- MPI（OpenMPI 4.1 实测）
- **FFTW 2.1.5**（MPI + double；FFTW3 不兼容——API 完全不同）
- GSL
- Numerical Recipes 例程随源码附带（nrsrc/）

## FFTW 2.1.5 安装（实测命令）

```bash
wget https://www.fftw.org/fftw-2.1.5.tar.gz
tar xzf fftw-2.1.5.tar.gz && cd fftw-2.1.5
CC=mpicc CFLAGS=-O3 ./configure --enable-mpi --enable-type-prefix --prefix=$PWD/install
make -j && make install
# 产物: install/lib/libdfftw_mpi.a 等（--enable-type-prefix 产生 d 前缀）
```

## 2LPTIC 编译

官方 Makefile 写死了作者本机路径，全部用 make 变量覆盖（不改文件）：

```bash
cd sources/2lptic
make CC=mpicc MPICHLIB= \
  OPTIMIZE="-O3 -Wall -fno-pie" \
  FFTW_INCL=-I<fftw2>/install/include \
  FFTW_LIBS="-L<fftw2>/install/lib -no-pie" \
  GSL_LIBS=-L/usr/lib/x86_64-linux-gnu GSL_INCL=-I/usr/include
# 产物: ./2LPTic
```

要点：
- 老 Numerical Recipes 目标文件与 FFTW2 静态库不是 PIC，**必须 `-fno-pie` 编译 + `-no-pie` 链接**（否则 `relocation R_X86_64_32 ... can not be used when making a PIE object`）。
- 默认开 `NO64BITID`（32 位 ID）；要 64 位 ID 需去掉该宏（大粒子数时）。

## 验证

编译后 `mpirun -np 1 ./2LPTic`（无参数）应报参数文件错误而非崩溃，即二进制可用。
