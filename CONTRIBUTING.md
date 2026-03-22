# Contributing to Tracecraft

Tracecraft is designed for parallel development by both humans and AI agents.

## Getting started

```bash
git clone https://github.com/Arrmlet/tracecraft
cd tracecraft
pip install -e "sdk/[dev]"
```

## Blueprint-driven development

The `plans/` directory contains construction blueprints where each step is self-contained. A fresh contributor can pick up any step whose dependencies are met and execute it independently.

```bash
cat plans/tracecraft-blueprint-v2.md
```

Each step includes:
- Context brief (what you need to know)
- Dependencies (what must be done first)
- Files to create/modify
- Verification commands
- Exit criteria

## Working in parallel

Multiple contributors can work on independent steps simultaneously using git worktrees:

```bash
git worktree add ../tracecraft-s1a -b step/s1a
git worktree add ../tracecraft-s1b -b step/s1b
```

Commit format: `tracecraft: [step-id] description`

## Running tests

```bash
cd sdk && pytest tests/ -v
cd server && pytest tests/ -v
```

## Code style

- Python: ruff (configured in pyproject.toml)
- Type hints required on public functions
- Tests required for new features
