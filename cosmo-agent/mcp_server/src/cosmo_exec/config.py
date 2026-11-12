"""Server-side configuration: allowed roots, state directory, environment manifest.

Everything access- or resource-related is enforced here, on the server side.
Skills carry conventions only; they are not a security boundary.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .policy import ExecPolicy

ENV_MANIFEST_VAR = "COSMO_ENV_MANIFEST"
STATE_DIR_VAR = "COSMO_EXEC_STATE_DIR"
ALLOWED_ROOTS_VAR = "COSMO_EXEC_ALLOWED_ROOTS"


@dataclass
class Config:
    state_dir: Path
    allowed_roots: list[Path]
    manifest_path: Path | None = None
    manifest: dict = field(default_factory=dict)
    exec_policy: ExecPolicy = field(default_factory=ExecPolicy.default)
    protected_paths: list[Path] = field(default_factory=list)

    def __post_init__(self):
        self.state_dir = self.state_dir.expanduser().resolve()
        self.allowed_roots = [root.expanduser().resolve() for root in self.allowed_roots]
        # Server-owned files stay writable only by the operator: a client that
        # could rewrite them would be able to widen its own boundary.
        protected = [Path(__file__).resolve().parent, self.state_dir / 'audit.jsonl']
        if self.manifest_path:
            protected.append(Path(self.manifest_path).expanduser().resolve())
        protected.extend(path.expanduser().resolve() for path in self.protected_paths)
        self.protected_paths = protected

    def check_path(self, p: str | os.PathLike) -> Path:
        """Resolve p and require it to live under one of the allowed roots."""
        path = Path(p).expanduser().resolve()
        if not any(path == root or root in path.parents for root in self.allowed_roots):
            raise PermissionError(
                f"path {path} is outside allowed_roots "
                f"({[str(r) for r in self.allowed_roots]})"
            )
        return path

    def check_write_path(self, p: str | os.PathLike) -> Path:
        """check_path plus the protected-path guard used by file_write.

        protected_paths is the cosmo_exec package itself plus the environment
        manifest and audit log, extended by `paths.protected` in the manifest.
        """
        path = self.check_path(p)
        for root in self.protected_paths:
            if path == root or root in path.parents:
                raise PermissionError(
                    f"path {path} is inside the protected path {root}; file_write "
                    "refuses it. The operator can remove it from paths.protected "
                    "in the environment manifest if the write is legitimate."
                )
        return path


def load_config(
    manifest_path: str | None = None,
    state_dir: str | None = None,
    allowed_roots: list[str] | None = None,
    *,
    protected_paths: list[str] | None = None,
    deny_patterns: list[str] | None = None,
    allow_commands: list[str] | None = None,
    allow_shell: bool | None = None,
    builtin_deny_patterns: bool | None = None,
    disabled_deny_patterns: list[str] | None = None,
) -> Config:
    manifest_path = manifest_path or os.environ.get(ENV_MANIFEST_VAR)
    manifest: dict = {}
    mpath: Path | None = None
    if manifest_path:
        mpath = Path(manifest_path).expanduser().resolve()
        with open(mpath) as fh:
            manifest = yaml.safe_load(fh) or {}

    if state_dir is None:
        state_dir = os.environ.get(STATE_DIR_VAR)
    if state_dir is None:
        state_dir = (manifest.get("paths") or {}).get("state_dir")
    if state_dir is None:
        state_dir = str(Path.home() / ".cosmo-exec")
    sdir = Path(state_dir).expanduser().resolve()
    sdir.mkdir(parents=True, exist_ok=True)

    roots = allowed_roots
    if roots is None:
        env_roots = os.environ.get(ALLOWED_ROOTS_VAR)
        if env_roots:
            roots = [r for r in env_roots.split(os.pathsep) if r]
    if roots is None:
        roots = (manifest.get("paths") or {}).get("allowed_roots")
    if not roots:
        raise RuntimeError(
            "no allowed_roots configured: set COSMO_EXEC_ALLOWED_ROOTS, "
            "pass --allowed-root, or define paths.allowed_roots in the environment manifest"
        )
    if protected_paths is None:
        protected_paths = (manifest.get("paths") or {}).get("protected") or []

    policy = ExecPolicy.from_manifest(
        manifest.get("exec"),
        deny_patterns=deny_patterns,
        allow_commands=allow_commands,
        allow_shell=allow_shell,
        builtin=builtin_deny_patterns,
        disabled=disabled_deny_patterns,
    )
    return Config(
        state_dir=sdir,
        allowed_roots=[Path(root) for root in roots],
        manifest_path=mpath,
        manifest=manifest,
        exec_policy=policy,
        protected_paths=[Path(path) for path in protected_paths],
    )
