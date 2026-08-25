#!/usr/bin/env python3
"""CLI for the Ornith inference-time learning loop."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from ornith_loop.config import load_config
from ornith_loop.loop import run_once
from ornith_loop.skillbank import SkillBank


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_once(_: argparse.Namespace) -> int:
    cfg = load_config()
    result = run_once(cfg)
    print(json.dumps(result, indent=2))
    return 0 if result.get("passed") else 1


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config()
    results = []
    passed = 0
    for i in range(args.n):
        logging.info("=== batch %d/%d ===", i + 1, args.n)
        r = run_once(cfg)
        results.append(r)
        if r.get("passed"):
            passed += 1
    summary = {"n": args.n, "passed": passed, "rate": passed / args.n if args.n else 0, "runs": results}
    print(json.dumps(summary, indent=2))
    return 0 if passed == args.n else 1


def cmd_status(_: argparse.Namespace) -> int:
    cfg = load_config()
    bank = SkillBank(cfg.db_path)
    stats = bank.pass_rate(20)
    recent = bank.recent_runs(10)
    out = {
        "difficulty": bank.get_difficulty(),
        "pass_rate_last_20": stats,
        "gap_tags": bank.gap_tags(),
        "recent_runs": recent,
        "db": str(cfg.db_path),
        "runs_dir": str(cfg.runs_dir),
    }
    print(json.dumps(out, indent=2))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    cfg = load_config()
    cfg.ensure_dirs()
    out_path = Path(args.output) if args.output else cfg.exports_dir / "dataset.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out_path.open("w", encoding="utf-8") as fout:
        for run_dir in sorted(cfg.runs_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            task_p = run_dir / "task.json"
            scaffold_p = run_dir / "scaffold.md"
            score_p = run_dir / "score.json"
            rollout_p = run_dir / "rollout.json"
            if not (task_p.exists() and score_p.exists()):
                continue
            task = json.loads(task_p.read_text(encoding="utf-8"))
            score = json.loads(score_p.read_text(encoding="utf-8"))
            scaffold = scaffold_p.read_text(encoding="utf-8") if scaffold_p.exists() else ""
            rollout = json.loads(rollout_p.read_text(encoding="utf-8")) if rollout_p.exists() else {}
            # Collect final file contents from sandbox if present
            sandbox_dir = cfg.sandbox_root / run_dir.name
            solution_files: dict[str, str] = {}
            if sandbox_dir.exists():
                for f in sandbox_dir.rglob("*"):
                    if f.is_file() and f.stat().st_size < 100_000:
                        try:
                            solution_files[f.relative_to(sandbox_dir).as_posix()] = f.read_text(
                                encoding="utf-8"
                            )
                        except (UnicodeDecodeError, OSError):
                            continue
            record = {
                "run_id": run_dir.name,
                "task": task,
                "scaffold": scaffold,
                "solution_files": solution_files,
                "rollout_steps": rollout.get("steps"),
                "reward": 1.0 if score.get("passed") else 0.0,
                "score": score,
            }
            fout.write(json.dumps(record, ensure_ascii=False) + "\n")
            n += 1
    print(json.dumps({"exported": n, "path": str(out_path)}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ornith-loop", description="Ornith inference-time learning loop")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def _add_verbose(p: argparse.ArgumentParser) -> None:
        p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    p_once = sub.add_parser("once", help="Run a single learning cycle")
    _add_verbose(p_once)
    p_once.set_defaults(func=cmd_once)

    p_run = sub.add_parser("run", help="Run N cycles")
    p_run.add_argument("--n", type=int, default=10, help="Number of cycles")
    _add_verbose(p_run)
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="Show pass rate and recent runs")
    _add_verbose(p_status)
    p_status.set_defaults(func=cmd_status)

    p_export = sub.add_parser("export", help="Export JSONL dataset for later fine-tune")
    p_export.add_argument("-o", "--output", help="Output JSONL path")
    _add_verbose(p_export)
    p_export.set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    _setup_logging(bool(getattr(args, "verbose", False)))
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
