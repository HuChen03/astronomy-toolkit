#!/usr/bin/env python3
"""Follow the twolptic Skill literally, end to end, through MCP.

The other e2e tests read templates from the repository by absolute path, which skips the
client-side Skill contract. This one reads the Skill from its *installed* client location
(the Codex skill root), then does exactly what SKILL.md says: parse the frontmatter, follow
the body, read the assets/scripts it points at, upload them to the server side, and run
2LPTIC there through cosmo-exec.

Usage: e2e_skill.py [--transport http|stdio] [--port N] [--skill-dir PATH]
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'mcp_server'))
from client_helpers import mcp_session, mcp_call

CODEX_HOME = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
INSTALLED = CODEX_HOME / 'skills' / 'twolptic'
REPO_SKILL = ROOT / 'skills' / 'twolptic'
BINARY = ROOT / 'sources' / '2lptic' / '2LPTic'
RUN = ROOT / 'runs' / 'skill-e2e' / 'twolptic'
FAIL = []


def check(name, ok, detail=''):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)
    if not ok:
        FAIL.append(name)


def split_frontmatter(text):
    end = text.find('\n---', 3)
    if not text.startswith('---') or end < 0:
        raise ValueError('SKILL.md has no frontmatter')
    return yaml.safe_load(text[3:end]), text[end + 4:]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transport', choices=['stdio', 'http'], default='http')
    parser.add_argument('--port', type=int, default=8790)
    parser.add_argument('--skill-dir', type=Path, default=None)
    args = parser.parse_args()

    skill = args.skill_dir or (INSTALLED if INSTALLED.is_dir() else REPO_SKILL)
    check('Skill 从客户端已安装位置读取（而非仓库路径）',
          args.skill_dir is not None or skill == INSTALLED, str(skill))
    if not (skill / 'SKILL.md').is_file():
        check('SKILL.md 存在', False, str(skill))
        return 1

    # --- 第 1 步：客户端只凭 frontmatter 就能判断该不该加载 ---
    meta, body = split_frontmatter((skill / 'SKILL.md').read_text())
    check('frontmatter 提供 name/description', meta.get('name') == 'twolptic' and bool(meta.get('description')))

    # --- 第 2 步：正文指向的 assets/scripts 必须真的存在 ---
    param_tpl = skill / 'assets' / '2LPT-small.param'
    glass_script = skill / 'scripts' / 'make_grid_glass.py'
    checker = skill / 'scripts' / 'check_2lptic_output.py'
    check('正文指向的 assets/scripts 齐备',
          all(p.is_file() for p in (param_tpl, glass_script, checker)))
    if FAIL:
        return 1

    # --- 第 3 步：照 cosmo-exec 约定，改写模板并 file_write 到服务端独立运行目录 ---
    param = param_tpl.read_text()
    assert 'OutputDir       ./output' in param

    async with mcp_session(ROOT / 'environments' / 'local.yaml',
                           transport=args.transport, port=args.port, state=ROOT / 'runs') as session:
        env = await mcp_call(session, 'env_info')
        check('env_info 可用（客户端可自检环境）', bool(env.get('allowed_roots')), env.get('hostname', ''))

        await mcp_call(session, 'file_write', {'path': str(RUN / '2LPT.param'), 'content': param})
        await mcp_call(session, 'file_write',
                       {'path': str(RUN / 'scripts/make_grid_glass.py'), 'content': glass_script.read_text()})
        await mcp_call(session, 'file_write',
                       {'path': str(RUN / 'scripts/check_2lptic_output.py'), 'content': checker.read_text()})

        async def sh(argv, timeout=300):
            result = await mcp_call(session, 'exec_run',
                                    {'argv': list(map(str, argv)), 'cwd': str(RUN), 'timeout': timeout},
                                    timeout=timeout + 30)
            return result

        await sh(['mkdir', '-p', 'output'])
        # 第 4 步：生成 glass（Skill 的 scripts/）
        glass = await sh([sys.executable, 'scripts/make_grid_glass.py', 'glass.dat'])
        check('glass 生成成功', glass['exit_code'] == 0, glass['stdout'].strip()[:60])

        # 第 5 步：mpirun -np N ./2LPTic <param>，N 需 >= 且整除 NumFilesWrittenInParallel
        run = await sh(['mpirun', '--allow-run-as-root', '-np', '2', str(BINARY), '2LPT.param'])
        # 成功判定必须看软件自己的标志，不能只看退出码
        check("2LPTIC 打印 \"IC's generated.\"",
              "IC's generated." in run['stdout'] + run['stderr'], f"exit={run['exit_code']}")

        # 第 6 步：用 Skill 自带检查脚本验证输出
        verify = await sh([sys.executable, 'scripts/check_2lptic_output.py', 'output', 'ics', '2'])
        check('Skill 自带输出检查通过', verify['exit_code'] == 0, verify['stdout'].strip().splitlines()[-1][:70]
              if verify['stdout'].strip() else verify['stderr'].strip()[:70])

    print(f"{'ALL PASS' if not FAIL else 'FAILURES: ' + ', '.join(FAIL)}", flush=True)
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
