"""Configuration for the Ornith learning loop."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_root() -> Path:
    env = os.environ.get("ORNITH_LOOP_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    root: Path
    ollama_host: str = "http://127.0.0.1:11434"
    model: str = "ornith"
    max_rollout_steps: int = 20
    step_timeout_sec: int = 30
    verify_timeout_sec: int = 60
    keep_alive: str = "5m"
    skill_top_k: int = 5
    unload_after_cycle: bool = True

    @property
    def sandbox_root(self) -> Path:
        return self.root / "sandbox"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    @property
    def db_path(self) -> Path:
        return self.root / "skillbank.db"

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    def ensure_dirs(self) -> None:
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    root = _default_root()
    return Config(
        root=root,
        ollama_host=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
        model=os.environ.get("ORNITH_MODEL", "ornith"),
        max_rollout_steps=int(os.environ.get("ORNITH_MAX_STEPS", "20")),
        step_timeout_sec=int(os.environ.get("ORNITH_STEP_TIMEOUT", "30")),
        verify_timeout_sec=int(os.environ.get("ORNITH_VERIFY_TIMEOUT", "60")),
        keep_alive=os.environ.get("ORNITH_KEEP_ALIVE", "5m"),
        skill_top_k=int(os.environ.get("ORNITH_SKILL_TOP_K", "5")),
        unload_after_cycle=os.environ.get("ORNITH_UNLOAD", "1") not in ("0", "false", "False"),
    )
