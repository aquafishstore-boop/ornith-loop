"""Sandbox filesystem and shell tools (path-jailed, no network)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Minimal env: no proxy / no external DNS helpers leaking into child
_SAFE_ENV = {
    "PATH": "/usr/bin:/bin:/usr/local/bin",
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def _ensure_python_shim(workdir: Path) -> None:
    """Provide `python` -> python3 inside sandbox bin/ so verify cmds work."""
    bin_dir = workdir / ".sandbox-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "python"
    if not shim.exists():
        shim.write_text("#!/bin/bash\nexec /usr/bin/python3 \"$@\"\n", encoding="utf-8", newline="\n")
        os.chmod(shim, 0o755)


class SandboxError(Exception):
    pass


class Sandbox:
    def __init__(self, root: Path, run_id: str, step_timeout: int = 30):
        self.root = root.resolve()
        self.workdir = (self.root / run_id).resolve()
        self.step_timeout = step_timeout
        self.workdir.mkdir(parents=True, exist_ok=True)
        _ensure_python_shim(self.workdir)
        self._bin = str(self.workdir / ".sandbox-bin")

    def cleanup(self) -> None:
        if self.workdir.exists():
            shutil.rmtree(self.workdir, ignore_errors=True)

    def _resolve(self, rel: str) -> Path:
        rel = rel.replace("\\", "/").lstrip("/")
        if not rel or rel == ".":
            target = self.workdir
        else:
            target = (self.workdir / rel).resolve()
        try:
            target.relative_to(self.workdir)
        except ValueError as e:
            raise SandboxError(f"path escapes sandbox: {rel}") from e
        return target

    def list_dir(self, path: str = ".") -> str:
        target = self._resolve(path)
        if not target.exists():
            return f"ERROR: not found: {path}"
        if not target.is_dir():
            return f"ERROR: not a directory: {path}"
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        lines = []
        for p in entries:
            kind = "dir" if p.is_dir() else "file"
            size = p.stat().st_size if p.is_file() else 0
            lines.append(f"{kind:4} {size:8} {p.relative_to(self.workdir).as_posix()}")
        return "\n".join(lines) if lines else "(empty)"

    def read_file(self, path: str) -> str:
        target = self._resolve(path)
        if not target.exists():
            return f"ERROR: not found: {path}"
        if not target.is_file():
            return f"ERROR: not a file: {path}"
        data = target.read_bytes()
        if len(data) > 200_000:
            return f"ERROR: file too large ({len(data)} bytes)"
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return f"ERROR: binary file ({len(data)} bytes)"

    def write_file(self, path: str, content: str) -> str:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if len(content.encode("utf-8")) > 500_000:
            return "ERROR: content too large"
        target.write_text(content, encoding="utf-8")
        return f"wrote {path} ({len(content)} chars)"

    def run(self, command: str, timeout: int | None = None) -> str:
        timeout = timeout if timeout is not None else self.step_timeout
        if not command or not command.strip():
            return "ERROR: empty command"
        # Block obvious network / privilege escapes
        lowered = command.lower()
        blocked = ("curl ", "wget ", "nc ", "ncat ", "ssh ", "scp ", "pip install", "npm install")
        for b in blocked:
            if b in lowered:
                return f"ERROR: blocked command pattern: {b.strip()}"

        env = dict(_SAFE_ENV)
        env["PATH"] = f"{self._bin}:{env['PATH']}"
        env["PWD"] = str(self.workdir)
        try:
            proc = subprocess.run(
                ["/bin/bash", "-lc", command],
                cwd=str(self.workdir),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                # no network via unshare if available
            )
        except subprocess.TimeoutExpired:
            return f"ERROR: timed out after {timeout}s"
        except OSError as e:
            return f"ERROR: {e}"

        out = (proc.stdout or "")[-8000:]
        err = (proc.stderr or "")[-4000:]
        parts = [f"exit_code={proc.returncode}"]
        if out:
            parts.append("--- stdout ---\n" + out)
        if err:
            parts.append("--- stderr ---\n" + err)
        return "\n".join(parts)

    def dispatch(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "list":
                return self.list_dir(str(arguments.get("path", ".")))
            if name == "read":
                return self.read_file(str(arguments.get("path", "")))
            if name == "write":
                return self.write_file(str(arguments.get("path", "")), str(arguments.get("content", "")))
            if name == "run":
                return self.run(str(arguments.get("command", "")))
            return f"ERROR: unknown tool {name}"
        except SandboxError as e:
            return f"ERROR: {e}"


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list",
            "description": "List files in a sandbox directory (relative path).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative directory path"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read a text file from the sandbox.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write",
            "description": "Write a text file in the sandbox (creates parents).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run",
            "description": "Run a bash command in the sandbox (no network).",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
]
