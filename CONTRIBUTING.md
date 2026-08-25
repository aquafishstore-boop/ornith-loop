# Contributing to ornith-loop

Thanks for helping improve the inference-time learning loop.

## Dev setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m ornith_loop status
```

You need a local Ollama instance and a tool-capable model (`ORNITH_MODEL`).

## Guidelines

- Keep the sandbox path-jailed; do not weaken network / path guardrails without discussion.
- Prefer small, reviewable PRs (one concern each).
- Do not commit `sandbox/`, `runs/`, `exports/`, `skillbank.db`, `.env`, or host-specific paths.
- Systemd units must stay templated (`__ORNITH_LOOP_ROOT__`), not hard-coded to a username.
- Match existing Python style (stdlib + `httpx`, no heavy framework).

## Useful tests (manual)

```bash
python -m ornith_loop once -v
python -m ornith_loop status
python -m ornith_loop export
```

## Ideas

- Stronger verifiers (pytest fixtures, property checks)
- Skill retrieval beyond tag overlap
- Alternate tool backends (Docker / bubblewrap)
- Curriculum strategies and difficulty schedules
