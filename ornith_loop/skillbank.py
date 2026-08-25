"""SQLite skill bank + curriculum difficulty."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Lesson:
    id: int
    tags: list[str]
    difficulty: int
    passed: bool
    summary: str
    failure_mode: str
    what_worked: str
    created_at: str


class SkillBank:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tags TEXT NOT NULL,
                    difficulty INTEGER NOT NULL,
                    passed INTEGER NOT NULL,
                    summary TEXT NOT NULL,
                    failure_mode TEXT NOT NULL DEFAULT '',
                    what_worked TEXT NOT NULL DEFAULT '',
                    task_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    passed INTEGER NOT NULL,
                    difficulty INTEGER NOT NULL,
                    tags TEXT NOT NULL,
                    score_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS curriculum (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            row = conn.execute("SELECT value FROM curriculum WHERE key='difficulty'").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO curriculum(key, value) VALUES('difficulty', ?)",
                    ("1",),
                )

    def get_difficulty(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM curriculum WHERE key='difficulty'").fetchone()
            return int(row["value"]) if row else 1

    def set_difficulty(self, level: int) -> None:
        level = max(1, min(10, int(level)))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO curriculum(key, value) VALUES('difficulty', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(level),),
            )

    def record_run(
        self,
        run_id: str,
        *,
        passed: bool,
        difficulty: int,
        tags: list[str],
        score: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs(run_id, passed, difficulty, tags, score_json, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (run_id, int(passed), difficulty, json.dumps(tags), json.dumps(score), _now()),
            )

    def add_lesson(
        self,
        *,
        tags: list[str],
        difficulty: int,
        passed: bool,
        summary: str,
        failure_mode: str = "",
        what_worked: str = "",
        task: dict[str, Any] | None = None,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO lessons(tags, difficulty, passed, summary, failure_mode, what_worked, task_json, created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    json.dumps(tags),
                    difficulty,
                    int(passed),
                    summary,
                    failure_mode,
                    what_worked,
                    json.dumps(task or {}),
                    _now(),
                ),
            )
            return int(cur.lastrowid)

    def recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT run_id, passed, difficulty, tags, score_json, created_at "
                "FROM runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "run_id": r["run_id"],
                    "passed": bool(r["passed"]),
                    "difficulty": r["difficulty"],
                    "tags": json.loads(r["tags"]),
                    "score": json.loads(r["score_json"]),
                    "created_at": r["created_at"],
                }
            )
        return out

    def pass_rate(self, last_n: int = 20) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT passed FROM runs ORDER BY id DESC LIMIT ?",
                (last_n,),
            ).fetchall()
        if not rows:
            return {"n": 0, "passed": 0, "rate": 0.0}
        passed = sum(1 for r in rows if r["passed"])
        n = len(rows)
        return {"n": n, "passed": passed, "rate": passed / n}

    def maybe_bump_curriculum(self, window: int = 5) -> int:
        """Raise difficulty if recent pass rate is high; lower if failing."""
        stats = self.pass_rate(window)
        level = self.get_difficulty()
        if stats["n"] < window:
            return level
        if stats["rate"] >= 0.8 and level < 10:
            level += 1
            self.set_difficulty(level)
            log.info("curriculum bump -> %d (pass_rate=%.0f%%)", level, 100 * stats["rate"])
        elif stats["rate"] <= 0.2 and level > 1:
            level -= 1
            self.set_difficulty(level)
            log.info("curriculum drop -> %d (pass_rate=%.0f%%)", level, 100 * stats["rate"])
        return level

    def gap_tags(self) -> list[str]:
        """Tags that appear more in failures than passes."""
        with self._connect() as conn:
            rows = conn.execute("SELECT tags, passed FROM lessons").fetchall()
        fail: dict[str, int] = {}
        ok: dict[str, int] = {}
        for r in rows:
            tags = json.loads(r["tags"])
            bucket = ok if r["passed"] else fail
            for t in tags:
                bucket[t] = bucket.get(t, 0) + 1
        scored = []
        for t, n in fail.items():
            scored.append((n - ok.get(t, 0), t))
        scored.sort(reverse=True)
        return [t for _, t in scored[:8]]

    def search(self, query_tags: list[str], query_text: str = "", top_k: int = 5) -> list[Lesson]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, tags, difficulty, passed, summary, failure_mode, what_worked, created_at "
                "FROM lessons ORDER BY id DESC LIMIT 200"
            ).fetchall()
        qtags = {t.lower() for t in query_tags}
        qwords = set(re.findall(r"[a-z0-9_]+", (query_text or "").lower()))
        scored: list[tuple[float, Lesson]] = []
        for r in rows:
            tags = [str(t) for t in json.loads(r["tags"])]
            lesson = Lesson(
                id=r["id"],
                tags=tags,
                difficulty=r["difficulty"],
                passed=bool(r["passed"]),
                summary=r["summary"],
                failure_mode=r["failure_mode"] or "",
                what_worked=r["what_worked"] or "",
                created_at=r["created_at"],
            )
            score = 0.0
            for t in tags:
                if t.lower() in qtags:
                    score += 3.0
            text = f"{lesson.summary} {lesson.failure_mode} {lesson.what_worked}".lower()
            for w in qwords:
                if len(w) > 2 and w in text:
                    score += 0.5
            # slight preference for failures (gaps) when querying for generation
            if not lesson.passed:
                score += 0.25
            if score > 0:
                scored.append((score, lesson))
        scored.sort(key=lambda x: (-x[0], -x[1].id))
        if not scored:
            # fallback: most recent
            recent = [
                Lesson(
                    id=r["id"],
                    tags=[str(t) for t in json.loads(r["tags"])],
                    difficulty=r["difficulty"],
                    passed=bool(r["passed"]),
                    summary=r["summary"],
                    failure_mode=r["failure_mode"] or "",
                    what_worked=r["what_worked"] or "",
                    created_at=r["created_at"],
                )
                for r in rows[:top_k]
            ]
            return recent
        return [L for _, L in scored[:top_k]]

    def format_for_prompt(self, lessons: list[Lesson]) -> str:
        if not lessons:
            return "(no prior lessons yet)"
        parts = []
        for L in lessons:
            status = "PASS" if L.passed else "FAIL"
            parts.append(
                f"- [{status}] d={L.difficulty} tags={','.join(L.tags)}\n"
                f"  summary: {L.summary}\n"
                f"  worked: {L.what_worked or '-'}\n"
                f"  failure: {L.failure_mode or '-'}"
            )
        return "\n".join(parts)
