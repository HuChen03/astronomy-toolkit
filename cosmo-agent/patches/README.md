# 原生模拟软件

在执行主机准备对应源码和 MPI 依赖。随附环境清单中的 `software.*` 路径用于登记安装位置。下表记录了补丁对应的上游版本与构建参考。

| 软件 | 基线 | 构建参考 |
| --- | --- | --- |
| GADGET-4 | GrGadget/Gadget4 `d0e3eeec250b2265ee76a5c8fe13ca9003d5f14d` | [构建说明](../skills/gadget4/references/building.md) · [补丁](Gadget4.patch) · [许可](Gadget4.LICENSE) |
| Arepo | dnelson86/arepo `d924fb39f2933129614d9a36296099b8137b2cde` | [构建说明](../skills/arepo/references/building.md) · [补丁](arepo.patch) · [许可](arepo.LICENSE) |
| HBT+ | Kambrian/HBTplus `6f87ace`，GADGET-4 输入用 MPI-Hydro-G4 分支 `eada82e6db9223295e42e2f3d86c6694d69f13ec` | [构建说明](../skills/hbtplus/references/building.md) · [MPI 退出顺序补丁](HBTplus-g4.patch) |
| 2LPTIC | 上游 `2LPTic.tar.gz` | [构建说明](../skills/twolptic/references/building.md) |

从 `cosmo-agent/` 检出各基线到 `sources/` 后应用补丁。

```bash
root="$PWD"
git -C sources/Gadget4 apply "$root/patches/Gadget4.patch"
git -C sources/arepo apply "$root/patches/arepo.patch"
git -C sources/HBTplus-g4 apply --unidiff-zero "$root/patches/HBTplus-g4.patch"
```

GADGET-4 的 GNU Make 流程还需要 `git_version.sh` 指向 `buildsystem/git_version.sh`。Meson 流程使用的 LATfield2 与 gevolution 目录见 GADGET-4 构建说明。原始改动背景见 [modifications.md](../modifications.md)。
