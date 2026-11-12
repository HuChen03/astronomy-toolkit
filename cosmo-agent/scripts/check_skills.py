#!/usr/bin/env python3
"""Validate the client-side Skill contract that lives in this repository.

A client discovers a Skill from the SKILL.md frontmatter alone (name + description),
loads the body only when a task matches, and reads references/assets/scripts last.
Everything that must hold for that to work is checked here: frontmatter parses,
the name matches the directory and the naming rules, the description is usable for
matching, and every local path the body points at actually exists.

Usage: check_skills.py [skills_dir ...]
"""
import argparse
import re
import sys
from pathlib import Path

import yaml

NAME_RE = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')
MAX_NAME = 64
MAX_DESCRIPTION = 1024
REFERENCE_RE = re.compile(
    r'`([A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:md|py|sh|txt|param|conf|yaml|yml|json|slurm))`')
# Only these prefixes are part of the progressive-disclosure contract: the agent is told to
# read them next, so a missing file is a broken Skill. Everything else the body mentions is
# resolved against the skill directory and the repository root, but may legitimately be a
# runtime artefact the agent creates or a path inside the upstream software source tree.
SKILL_LOCAL_PREFIXES = ('references/', 'assets/', 'scripts/')


def split_frontmatter(text, path):
    if not text.startswith('---'):
        raise ValueError('missing YAML frontmatter (file must start with ---)')
    end = text.find('\n---', 3)
    if end < 0:
        raise ValueError('unterminated YAML frontmatter')
    try:
        meta = yaml.safe_load(text[3:end])
    except yaml.YAMLError as exc:
        raise ValueError(f'invalid YAML frontmatter: {exc}') from exc
    if not isinstance(meta, dict):
        raise ValueError('frontmatter must be a mapping')
    return meta, text[end + 4:]


def check_skill(directory, repo_root):
    problems = []
    warnings = []
    manifest = directory / 'SKILL.md'
    if not manifest.is_file():
        return [f'{directory.name}: SKILL.md missing'], []
    meta, body = split_frontmatter(manifest.read_text(), manifest)

    name = meta.get('name')
    if not isinstance(name, str) or not name:
        problems.append('frontmatter has no name (clients match on it)')
    else:
        if name != directory.name:
            problems.append(f"name '{name}' does not match directory '{directory.name}'")
        if not NAME_RE.match(name):
            problems.append(f"name '{name}' must be lowercase alphanumeric with single hyphens")
        if len(name) > MAX_NAME:
            problems.append(f'name exceeds {MAX_NAME} characters')

    description = meta.get('description')
    if not isinstance(description, str) or len(description.strip()) < 20:
        problems.append('description is missing or too short to match a task against')
    elif len(description) > MAX_DESCRIPTION:
        problems.append(f'description exceeds {MAX_DESCRIPTION} characters')

    for reference in sorted(set(REFERENCE_RE.findall(body))):
        if (directory / reference).exists():
            continue
        if (repo_root / reference).exists():
            warnings.append(f'resolved at the repository root, not inside the skill: {reference}')
            continue
        if reference.startswith(SKILL_LOCAL_PREFIXES):
            problems.append(f'skill-local reference missing everywhere: {reference}')
        else:
            warnings.append(f'unresolved path (runtime artefact or upstream source?): {reference}')
    return problems, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('skills', nargs='*', type=Path,
                        default=[Path(__file__).resolve().parents[1] / 'skills'])
    parser.add_argument('--strict', action='store_true',
                        help='treat unresolved non-skill-local paths as failures')
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    directories = []
    for root in args.skills:
        directories += [p for p in sorted(root.iterdir()) if (p / 'SKILL.md').is_file()]
    failures = warnings_total = 0
    for directory in directories:
        problems, warnings = check_skill(directory, repo_root)
        if args.strict:
            problems, warnings = problems + warnings, []
        status = 'PASS' if not problems else 'FAIL'
        print(f'[{status}] {directory.name}')
        for problem in problems:
            failures += 1
            print(f'       - {problem}')
        for warning in warnings:
            warnings_total += 1
            print(f'       ~ {warning}')
    print(f'{len(directories)} skills checked, {failures} problem(s), {warnings_total} warning(s)')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
