# Arepo 公开版编译

来源：sources/arepo（dnelson86/arepo @ d924fb3）Makefile、Template-Makefile.systype；arepo-code.org userguide。

## 流程（与 GADGET-4 官方同构）

1. 准备 Config.sh：从 `Template-Config.sh` 或目标 example 的 `Config.sh` 复制修改。
2. `Makefile.systype`：从 `Template-Makefile.systype` 复制并选定 `SYSTYPE`（也可用环境变量），库路径/编译器在对应 systype 段配置。
3. 编译（按算例编译，二进制与 Config 绑定）：

```bash
make CONFIG=<dir>/Config.sh BUILD_DIR=<dir>/build EXEC=<dir>/Arepo -j8
# make 会先运行 check.py 校验编译宏拼写（未登记宏报错；豁免见 defines_extra）
```

## 依赖（Ubuntu 22.04 包）

`libopenmpi-dev libgsl-dev libfftw3-dev libhdf5-openmpi-dev libhwloc-dev`，C 编译器 ≥ C11、GNU Make、Python3。

## 常见坑

- HDF5 需并行版（openmpi variant）且 include/lib 路径非默认：Ubuntu 上为 `/usr/include/hdf5/openmpi`、`/usr/lib/x86_64-linux-gnu/hdf5/openmpi`。
- 若无匹配 SYSTYPE，新增一段（仿照现有 Generic 段）比改模板更安全。
- 测试套件：`sh test.sh` 逐个编译+运行 examples 并跑 check.py（完整跑一遍耗时长，可单跑一个 example 的流程）。
