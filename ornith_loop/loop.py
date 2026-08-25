"""Single-cycle orchestration."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .ollama_client import OllamaClient
from .sandbox import Sandbox
from .skillbank import SkillBank
from . import stages

log = logging.getLogger(__name__)


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_once(cfg: Config) -> dict[str, Any]:
    cfg.ensure_dirs()
    run_id = _run_id()
    artifact_dir = cfg.runs_dir / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    bank = SkillBank(cfg.db_path)
    client = OllamaClient(cfg.ollama_host, cfg.model, keep_alive=cfg.keep_alive)
    sandbox = Sandbox(cfg.sandbox_root, run_id, step_timeout=cfg.step_timeout_sec)

    result: dict[str, Any] = {"run_id": run_id, "artifact_dir": str(artifact_dir)}
    try:
        log.info("[%s] task generation", run_id)
        task = stages.generate_task(client, bank, top_k=cfg.skill_top_k)
        (artifact_dir / "task.json").write_text(json.dumps(task, indent=2), encoding="utf-8")

        lessons = bank.search(task.get("tags") or [], task.get("goal") or "", top_k=cfg.skill_top_k)
        lessons_block = bank.format_for_prompt(lessons)

        log.info("[%s] scaffold", run_id)
        scaffold = stages.build_scaffold(client, task, lessons_block)
        (artifact_dir / "scaffold.md").write_text(scaffold, encoding="utf-8")

        log_path = artifact_dir / "rollout.log"
        log_path.write_text("", encoding="utf-8")
        log.info("[%s] rollout (max_steps=%d)", run_id, cfg.max_rollout_steps)
        roll = stages.rollout(
            client,
            sandbox,
            task,
            scaffold,
            max_steps=cfg.max_rollout_steps,
            lessons_block=lessons_block,
            log_path=log_path,
        )
        (artifact_dir / "rollout.json").write_text(json.dumps(roll, indent=2), encoding="utf-8")

        log.info("[%s] verify", run_id)
        score = stages.verify(sandbox, task, cfg.verify_timeout_sec)
        score["steps"] = roll["steps"]
        score["done_flag"] = roll["done_flag"]
        (artifact_dir / "score.json").write_text(json.dumps(score, indent=2), encoding="utf-8")

        summary = (roll.get("transcript") or [{}])[-1].get("content") or ""
        if not summary and roll.get("transcript"):
            summary = json.dumps(roll["transcript"][-1])[:2000]
        lesson = stages.learn(client, bank, task, score, summary)
        (artifact_dir / "lesson.json").write_text(json.dumps(lesson, indent=2), encoding="utf-8")

        bank.record_run(
            run_id,
            passed=bool(score["passed"]),
            difficulty=int(task.get("difficulty") or 1),
            tags=task.get("tags") or [],
            score=score,
        )

        result.update(
            {
                "passed": score["passed"],
                "difficulty": task.get("difficulty"),
                "title": task.get("title"),
                "tags": task.get("tags"),
                "steps": roll["steps"],
                "lesson_id": lesson.get("id"),
                "curriculum": bank.get_difficulty(),
            }
        )
        log.info(
            "[%s] %s difficulty=%s steps=%s curriculum=%s",
            run_id,
            "PASS" if score["passed"] else "FAIL",
            task.get("difficulty"),
            roll["steps"],
            bank.get_difficulty(),
        )
        return result
    finally:
        if cfg.unload_after_cycle:
            client.unload()
        client.close()
        # keep sandbox for inspection; optional cleanup via env later
