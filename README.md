# Ornith Learning Loop

Inference-time practice loop for [Ollama](https://ollama.com) coding models (default: `ornith`). **No weight training** — invents coding tasks, scaffolds them, rolls out a tool-using agent in a jail, verifies with exit codes, and stores lessons in a SQLite skill bank that conditions the next cycle.

```mermaid
flowchart LR
  hist[SkillBank] --> taskGen[TaskGeneration]
  taskGen --> scaffold[ScaffoldBuild]
  scaffold --> rollout[SolutionRollout]
  rollout --> verify[Verifier]
  verify --> store[UpdateSkillBank]
  store --> hist
```

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) running locally with a tool-capable model
- Linux/macOS recommended for the sandbox shell (Windows: use WSL)

## Quick start

```bash
git clone https://github.com/aquafishstore-boop/ornith-loop.git
cd ornith-loop
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# ensure Ollama is up and your model is pulled
ollama pull ornith          # or set ORNITH_MODEL to another tools model

./bin/ornith-loop once
./bin/ornith-loop status
./bin/ornith-loop export
```

Or without the wrapper: `python -m ornith_loop once`

## CLI

| Command | Description |
|---------|-------------|
| `ornith-loop once` | Single learning cycle |
| `ornith-loop run --n 10` | Batch of N cycles |
| `ornith-loop status` | Pass rate, curriculum difficulty, recent runs |
| `ornith-loop export` | JSONL of `(task, scaffold, solution, reward)` for later fine-tune |

## Layout (after first run)

```
ornith-loop/
  ornith_loop/           # Python package
  bin/ornith-loop        # CLI wrapper
  sandbox/<run_id>/      # ephemeral workdirs
  runs/<timestamp>/      # task.json, scaffold.md, rollout.log, score.json, lesson.json
  exports/               # JSONL exports
  skillbank.db           # durable lessons + curriculum
```

## Stages

1. **Task generation** — reads skill-bank gaps + recent scores → JSON task (`goal`, `files`, `verify`, `difficulty`, `tags`)
2. **Scaffold** — short harness (steps / tools / constraints)
3. **Rollout** — bounded agent loop (`list` / `read` / `write` / `run`) in the sandbox
4. **Verify** — runs the task’s `verify` command (pass/fail)
5. **Learn** — writes a lesson; bumps curriculum difficulty when recent pass rate is high

## Guardrails

- Paths jailed under `sandbox/<run_id>/`
- Tool runner uses a minimal env; blocks common network / install patterns
- Step count and wall-clock timeouts
- Model unloaded after each cycle by default so other Ollama clients are not starved of VRAM

## Configuration

| Variable | Default | Meaning |
|----------|---------|---------|
| `ORNITH_LOOP_ROOT` | repo root | data root (`sandbox/`, `runs/`, DB) |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama API |
| `ORNITH_MODEL` | `ornith` | model name |
| `ORNITH_MAX_STEPS` | `20` | rollout budget |
| `ORNITH_STEP_TIMEOUT` | `30` | seconds per shell tool call |
| `ORNITH_VERIFY_TIMEOUT` | `60` | seconds for verify command |
| `ORNITH_KEEP_ALIVE` | `5m` | keep-alive during a cycle |
| `ORNITH_SKILL_TOP_K` | `5` | lessons injected into prompts |
| `ORNITH_UNLOAD` | `1` | unload model after each cycle |

## Optional systemd timer

Units under `systemd/` are **templates**. Copy them and replace `__ORNITH_LOOP_ROOT__` with your install path (see `examples/install-user-timer.sh`). Default remains manual CLI so GPU time stays free for interactive chats.

```bash
./examples/install-user-timer.sh /path/to/ornith-loop
systemctl --user enable --now ornith-loop.timer
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Ideas welcome: better verifiers, multi-language tasks, richer skill retrieval, Windows-native sandbox.

## License

[MIT](LICENSE)
