"""Loop stages: task generation, scaffold, rollout, verify, learn."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from .ollama_client import OllamaClient
from .sandbox import TOOL_SCHEMAS, Sandbox
from .skillbank import SkillBank

log = logging.getLogger(__name__)

TASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "goal": {"type": "string"},
        "files": {"type": "array", "items": {"type": "string"}},
        "verify": {"type": "string"},
        "difficulty": {"type": "integer"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "hints": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "goal", "files", "verify", "difficulty", "tags"],
}

LESSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "what_worked": {"type": "string"},
        "failure_mode": {"type": "string"},
    },
    "required": ["summary"],
}


def generate_task(
    client: OllamaClient,
    bank: SkillBank,
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    difficulty = bank.get_difficulty()
    gaps = bank.gap_tags()
    recent = bank.recent_runs(8)
    lessons = bank.search(gaps or ["python", "cli"], "coding task gaps", top_k=top_k)
    lesson_block = bank.format_for_prompt(lessons)
    recent_block = json.dumps(recent, indent=2) if recent else "[]"

    system = (
        "You invent short, objectively verifiable coding tasks for a sandbox agent. "
        "Tasks must be solvable with Python and bash only, no network, no packages to install. "
        "Always use `python3` (never bare `python`) in verify commands and examples. "
        "Prefer self-contained scripts and a clear verify command "
        "(e.g. `python3 -c '...'` asserts, or `python3 script.py` with exit code). "
        "If the task needs input files, the verify command must create them or the agent must create them. "
        "Difficulty 1=trivial, 10=hard. Match the requested difficulty."
    )
    user = f"""Create ONE coding task as JSON.

Target difficulty: {difficulty}
Skill-bank gaps (focus practice here if sensible): {gaps or ["basics"]}
Recent run scores:
{recent_block}

Related lessons from skill bank:
{lesson_block}

Requirements:
- `verify` must be a shell command that exits 0 on success, non-zero on failure
- Keep scope small enough for ~20 tool steps
- Do not require internet or pip install
- files: list of paths the agent should create or edit
"""
    resp = client.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        format=TASK_SCHEMA,
        temperature=0.7,
        think=False,
    )
    raw = client.message_content(resp)
    task = client.extract_json(raw)
    # normalize
    task["difficulty"] = int(task.get("difficulty") or difficulty)
    task["tags"] = [str(t) for t in (task.get("tags") or [])]
    task["files"] = [str(f) for f in (task.get("files") or [])]
    task["hints"] = [str(h) for h in (task.get("hints") or [])]
    if not task.get("verify"):
        raise ValueError("task missing verify command")
    return task


def build_scaffold(client: OllamaClient, task: dict[str, Any], lessons_block: str) -> str:
    system = (
        "You write a short solution scaffold (markdown) for a coding agent. "
        "List steps, allowed tools (list/read/write/run), constraints, and success criteria. "
        "Do not write the full solution code."
    )
    user = f"""Task JSON:
{json.dumps(task, indent=2)}

Relevant lessons:
{lessons_block}

Emit a concise scaffold.md body (no fences)."""
    resp = client.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
        think=False,
    )
    return client.message_content(resp)


def rollout(
    client: OllamaClient,
    sandbox: Sandbox,
    task: dict[str, Any],
    scaffold: str,
    *,
    max_steps: int,
    lessons_block: str,
    log_path: Path | None = None,
) -> dict[str, Any]:
    system = (
        "You are a coding agent solving a sandbox task. "
        "Use only the provided tools: list, read, write, run. "
        "No network. Prefer small iterative edits. "
        "When the task is complete, stop calling tools and reply with DONE and a brief summary."
    )
    user = f"""## Task
{json.dumps(task, indent=2)}

## Scaffold
{scaffold}

## Lessons
{lessons_block}

Start by listing the workspace, then implement and self-check with run before finishing.
"""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    transcript: list[dict[str, Any]] = []
    done = False
    steps = 0

    def _append_log(line: str) -> None:
        if log_path:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    for step in range(1, max_steps + 1):
        steps = step
        resp = client.chat(messages, tools=TOOL_SCHEMAS, temperature=0.2, think=False)
        msg = resp.get("message") or {}
        content = (msg.get("content") or "").strip()
        tool_calls = client.message_tool_calls(resp)
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        entry = {"step": step, "content": content, "tool_calls": []}
        _append_log(f"=== step {step} ===")
        if content:
            _append_log(content)

        if not tool_calls:
            if "DONE" in content.upper() or step == max_steps:
                done = "DONE" in content.upper()
                transcript.append(entry)
                break
            # nudge once
            messages.append(
                {
                    "role": "user",
                    "content": "Continue with tools, or reply DONE if finished.",
                }
            )
            transcript.append(entry)
            continue

        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"raw": args}
            result = sandbox.dispatch(name, args if isinstance(args, dict) else {})
            entry["tool_calls"].append({"name": name, "arguments": args, "result": result[:2000]})
            _append_log(f"$ {name} {json.dumps(args)[:500]}")
            _append_log(result[:2000])
            # Ollama tool message format
            messages.append(
                {
                    "role": "tool",
                    "tool_name": name,
                    "content": result[:12000],
                }
            )
        transcript.append(entry)

        if content and "DONE" in content.upper() and not tool_calls:
            done = True
            break

    return {"steps": steps, "done_flag": done, "transcript": transcript}


def verify(sandbox: Sandbox, task: dict[str, Any], timeout: int) -> dict[str, Any]:
    cmd = task["verify"]
    t0 = time.monotonic()
    result = sandbox.run(cmd, timeout=timeout)
    elapsed = time.monotonic() - t0
    passed = False
    # parse exit_code=N from sandbox.run output
    for line in result.splitlines():
        if line.startswith("exit_code="):
            try:
                passed = int(line.split("=", 1)[1]) == 0
            except ValueError:
                passed = False
            break
    return {
        "passed": passed,
        "verify_command": cmd,
        "elapsed_sec": round(elapsed, 3),
        "output": result[:8000],
    }


def learn(
    client: OllamaClient,
    bank: SkillBank,
    task: dict[str, Any],
    score: dict[str, Any],
    rollout_summary: str,
) -> dict[str, Any]:
    system = (
        "You distill a short lesson from a coding attempt for future agents. "
        "Be concrete: patterns that worked or specific failure modes."
    )
    user = f"""Task: {json.dumps(task)}
Score: {json.dumps(score)}
Rollout notes: {rollout_summary[:4000]}

Return JSON with summary, what_worked, failure_mode."""
    resp = client.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        format=LESSON_SCHEMA,
        temperature=0.3,
        think=False,
    )
    lesson = client.extract_json(client.message_content(resp))
    lid = bank.add_lesson(
        tags=task.get("tags") or [],
        difficulty=int(task.get("difficulty") or 1),
        passed=bool(score.get("passed")),
        summary=str(lesson.get("summary") or ""),
        failure_mode=str(lesson.get("failure_mode") or ""),
        what_worked=str(lesson.get("what_worked") or ""),
        task=task,
    )
    bank.maybe_bump_curriculum()
    lesson["id"] = lid
    return lesson
