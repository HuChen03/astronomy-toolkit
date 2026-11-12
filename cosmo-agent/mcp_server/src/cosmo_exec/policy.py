"""Server-side command policy for exec_run/exec_start.

``allowed_roots`` constrains *where* a command runs, never *what* it runs: one
``exec_run`` with ``rm -rf /`` still takes the host down. This module is the
second gate, evaluated before anything is spawned:

* **deny patterns** — catastrophic command shapes (delete the filesystem root
  or a system directory, format a disk, escalate privileges, pipe a download
  into a shell, ...). The built-in table is on by default and can only be
  weakened *explicitly*: ``exec.disabled_deny_patterns`` drops individual rules
  by name, ``exec.builtin_deny_patterns: false`` drops all of them, and
  ``exec.deny_patterns`` *adds* site-specific regexes on top. An empty
  ``deny_patterns`` therefore never silently switches the guard off.
* **allow_commands** — optional deny-by-default mode: only the listed
  executable names (``argv[0]`` basename) may run. Setting it also refuses
  ``shell=true``, because a command string cannot be allowlisted.
* **allow_shell** — ``exec.allow_shell: false`` refuses ``shell=true`` outright.

Matching is textual and deliberately conservative. It stops accidents and
naive agent drift; it is *not* a sandbox, since an interpreter can always build
the same string at runtime (``python3 -c "import shutil; shutil.rmtree('/')"``
is not caught). Real containment is running this server as a low-privilege
user, in a container, against filesystems that user cannot destroy.
"""
from __future__ import annotations

import re
import os
import shutil
from pathlib import Path

# Executables whose name must match exactly (argv[0] basename allowlist).
SHELL_NAMES = {"sh", "bash", "dash", "zsh", "ksh", "ash", "busybox"}
JOB_ENV = {"OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "CUDA_VISIBLE_DEVICES"}
HTTP_TOKEN_VAR = "COSMO_EXEC_HTTP_TOKEN"

# Words a destructive command can hide behind: `sudo nice xargs rm ...`.
_WRAPPERS = (
    r"sudo|doas|command|exec|nohup|setsid|nice|ionice|time|stdbuf|timeout"
    r"|xargs|env|watch|parallel"
)
# A command position is the start of the text, a shell separator, or a
# loop/conditional body. The trailing group then skips wrapper words plus their
# simple arguments (flags, numbers, NAME=VALUE), so the checks below anchor on
# the real executable and not on a word inside a quoted document lookup:
# `rg -n 'rm -rf /' docs/` starts with `rg`, which is not a wrapper to skip.
_LEAD = (
    r"(?:(?:" + _WRAPPERS + r")\b|[A-Za-z_]\w*=\S*|-\S+|\d+[a-z]*)\s+"
)
_COMMAND_POS = (
    r"(?:^|[;&|]\s*|\b(?:then|do|else)\s+)"
    r"(?:" + _LEAD + r")*"
)
# Paths whose recursive deletion, reformatting or blanket chmod is a host-level
# accident rather than a simulation step.
_SYSTEM_DIRS = r"usr|etc|var|home|root|opt|bin|sbin|lib|lib64|boot|dev|proc|sys"
_ROOT_TARGET = (
    r"(?:"
    r"/(?:\*)?(?=\s|$|[;&|])"
    r"|/(?:" + _SYSTEM_DIRS + r")(?:/|\s|\*|$)"
    r"|(?:~|\$(?:HOME|\{HOME\}))/\*?(?=\s|$|[;&|])"
    r")"
)

# (name, regex) — `name` is reported to the caller and to the audit log.
DEFAULT_DENY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("delete-filesystem-root-or-system-dir",
     _COMMAND_POS + r"rm\b[^\n;&|]*?\s+" + _ROOT_TARGET),
    ("delete-via-find",
     _COMMAND_POS + r"find\s+/(?:\s|$)[^\n;&|]*-(?:delete|exec\s+rm)\b"),
    ("format-filesystem",
     _COMMAND_POS + r"(?:mkfs(?:\.[a-z0-9]+)?|wipefs|mkswap|fdisk|sfdisk|parted)\b"),
    ("write-raw-disk",
     r"(?:>\s*/dev/(?:sd|nvme|hd|vd|mmcblk|loop|disk)\w*"
     r"|\bdd\b[^\n;&|]*\bof=\s*/dev/)"),
    ("loosen-permissions",
     _COMMAND_POS + r"(?:chmod|chown|chgrp)\b[^\n;&|]*?\s+" + _ROOT_TARGET),
    ("overwrite-system-config",
     r">\s*/etc/(?:passwd|shadow|group|sudoers|fstab|hosts)\b"),
    ("power-management",
     _COMMAND_POS + r"(?:shutdown|reboot|halt|poweroff)\b|" + _COMMAND_POS + r"init\s+[06]\b"),
    ("fork-bomb", r":\s*\(\s*\)\s*\{"),
    ("kill-everything", r"\b(?:killall5|kill\s+-9\s+-1|kill\s+-1\s+-9)\b"),
    ("privilege-escalation", _COMMAND_POS + r"(?:sudo|doas|su)\b"),
    ("pipe-download-into-shell",
     r"\b(?:curl|wget)\b[^\n;&|]*\|\s*(?:sudo\s+)?(?:ba|da|z|k)?sh\b"),
)


def command_texts(argv: list[str] | None, command: str | None, shell: bool) -> list[str]:
    """Texts the deny patterns are matched against.

    Args are joined by spaces (quoting is not reconstructed), and the script of
    a shell invocation is inspected separately so that command-position rules
    also apply to `bash -c "rm -rf /"`.
    """
    if shell:
        return [command or ""]
    if not argv:
        return []
    texts = [" ".join(argv)]
    if Path(argv[0]).name in SHELL_NAMES:
        for index, arg in enumerate(argv[1:], start=1):
            if arg == "-c" or ("c" in arg[1:] and arg.startswith("-")):
                if index + 1 < len(argv):
                    texts.append(argv[index + 1])
                break
    return [text for text in texts if text]


class ExecPolicy:
    """Compiled deny patterns plus optional allowlist/shell switch."""

    def __init__(self, patterns=(), allow_commands=(), allow_shell: bool = True, allow_env=()):
        self.patterns = tuple(patterns)
        self.allow_commands = tuple(allow_commands)
        self.allow_shell = allow_shell and not self.allow_commands
        self.allow_env = JOB_ENV | set(allow_env)
        self.trusted_path = os.pathsep.join(
            directory for directory in os.get_exec_path() if Path(directory).is_absolute()
        )
        self.executables: dict[str, set[Path]] = {}
        for command in self.allow_commands:
            resolved = shutil.which(command, path=self.trusted_path) if "/" not in command or Path(command).is_absolute() else None
            if resolved:
                self.executables.setdefault(Path(command).name, set()).add(Path(resolved).resolve())
        self._compiled = [
            (name, re.compile(regex, re.IGNORECASE)) for name, regex in self.patterns
        ]

    @classmethod
    def default(cls) -> "ExecPolicy":
        return cls(patterns=DEFAULT_DENY_PATTERNS)

    @classmethod
    def from_manifest(cls, section: dict | None, *, allow_commands=None,
                      deny_patterns=None, allow_shell=None, builtin=None,
                      disabled=None) -> "ExecPolicy":
        """Build the policy from the manifest `exec:` section plus CLI overrides.

        The built-in table stays on unless `builtin_deny_patterns: false` says
        otherwise; `deny_patterns` only ever adds rules. CLI overrides win over
        the manifest.
        """
        section = section or {}
        if builtin is None:
            builtin = section.get("builtin_deny_patterns", True)
        if disabled is None:
            disabled = section.get("disabled_deny_patterns") or ()
        extra = deny_patterns if deny_patterns is not None else (
            section.get("deny_patterns") or []
        )

        skip = set(disabled)
        known = {name for name, _ in DEFAULT_DENY_PATTERNS}
        unknown = sorted(skip - known)
        if unknown:
            raise ValueError(
                f"exec.disabled_deny_patterns has unknown rule name(s) {unknown}; "
                f"known rules: {sorted(known)}"
            )
        patterns = [
            (name, regex) for name, regex in DEFAULT_DENY_PATTERNS if name not in skip
        ] if builtin else []
        patterns += [(f"custom-{i + 1}", regex) for i, regex in enumerate(extra)]

        if allow_commands is None:
            allow_commands = section.get("allow_commands") or ()
        if allow_shell is None:
            allow_shell = section.get("allow_shell", True)
        return cls(patterns=tuple(patterns), allow_commands=tuple(allow_commands),
                   allow_shell=bool(allow_shell), allow_env=section.get("allow_env") or ())

    def describe(self) -> dict:
        return {
            "allow_shell": self.allow_shell,
            "allow_commands": list(self.allow_commands),
            "deny_patterns": [name for name, _ in self.patterns],
        }

    def check(self, argv: list[str] | None = None, command: str | None = None,
              shell: bool = False) -> None:
        """Raise PermissionError if this invocation is not allowed."""
        if shell and not self.allow_shell:
            reason = (
                "shell=true is disabled by the server policy "
                "(exec.allow_shell: false or an exec.allow_commands allowlist)"
            )
            raise PermissionError(reason)

        if self.allow_commands:
            name = Path(argv[0]).name if argv else None
            if name not in {Path(item).name for item in self.allow_commands}:
                raise PermissionError(
                    f"executable {name!r} is not in the server allowlist "
                    f"({list(self.allow_commands)}); ask the operator to extend "
                    "exec.allow_commands"
                )

        for text in command_texts(argv, command, shell):
            for name, pattern in self._compiled:
                match = pattern.search(text)
                if match:
                    raise PermissionError(
                        f"command rejected by the server policy rule {name!r} "
                        f"(matched {match.group(0).strip()!r}). If the command is "
                        "legitimate, ask the operator to drop that rule via "
                        "exec.disabled_deny_patterns (or builtin_deny_patterns: false) "
                        "in the environment manifest."
                    )

    def bind(self, argv: list[str]) -> list[str]:
        if not self.allow_commands:
            return argv
        executable = Path(argv[0])
        approved = self.executables.get(executable.name, set())
        if executable.is_absolute() and executable.resolve() in approved:
            return [str(executable.resolve()), *argv[1:]]
        if "/" not in argv[0] and len(approved) == 1:
            return [str(next(iter(approved))), *argv[1:]]
        raise PermissionError(f"executable {argv[0]!r} does not resolve to one approved path")

    def environment(self, additions: dict[str, str] | None) -> dict[str, str]:
        additions = additions or {}
        env = os.environ.copy()
        env.pop(HTTP_TOKEN_VAR, None)
        if HTTP_TOKEN_VAR in additions:
            raise PermissionError(f"environment overrides are prohibited for {HTTP_TOKEN_VAR}")
        if self.allow_commands:
            forbidden = set(additions) - self.allow_env
            forbidden.update(key for key in additions if key.upper().startswith(("LD_", "DYLD_", "PYTHON"))
                             or key.upper() in {"PATH", "BASH_ENV", "ENV", HTTP_TOKEN_VAR})
            if forbidden:
                raise PermissionError(f"environment overrides are prohibited for {', '.join(sorted(forbidden))}")
            env["PATH"] = self.trusted_path
        env.update(additions)
        return env
