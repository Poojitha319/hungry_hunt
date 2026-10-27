# Contributing

Thanks for looking. This is a single-user job-search agent, but the pipeline, adapters and rules are general and
contributions are welcome, especially new hiring-system adapters and better drop rules.

## Setup

```bash
make install        # uv sync --extra dev (falls back to pip), installs the pre-commit hook
cp .env.example .env
make migrate        # SQLite by default
make check          # ruff, mypy, pytest
cd frontend && npm ci && npm test
```

## Ground rules

- **Tests first.** Every drop rule is a pure function in `src/hungry_hunt/scoring/rules.py` with a table-driven test.
  Every adapter has a fixture under `tests/fixtures/` captured from the real API. No test touches the network: the
  `public_dns` fixture in `tests/conftest.py` pins DNS, and `respx` mocks HTTP.
- **Behaviour changes bump a version.** Rules → `RULES_VERSION`; scoring rubric → `SCORING_VERSION`. Both are part of
  the assessment key, so a bump re-evaluates every open job on the next run.
- **No new runtime dependency without a reason** in the pull request. `uv.lock` must be refreshed (`make lock`).
- **Schema changes go through Alembic.** `alembic revision --autogenerate -m "..."`, then check the migration by hand.
- **Lean code.** No comments that restate the code; one-line module docstrings; no helper that is called once.
- Pre-commit runs ruff, ruff-format and mypy. CI runs the same plus the frontend checks.

## Adding a hiring system

1. Create `src/hungry_hunt/adapters/<name>.py` with `BOARD`, `parse(...) -> list[Posting]` and either
   `HOSTS`/`PARAMS` (single JSON endpoint) or `async def board(client, slug, limits)` (paged).
2. Register it in `src/hungry_hunt/adapters/registry.py` (`SUPPORTED`, `BOARD_URL`, `JSON_BOARDS` or `PAGED_BOARDS`,
   and `DESCRIPTIONS` if descriptions need a second call).
3. Teach discovery how to recognise its URLs in `src/hungry_hunt/discovery/discover.py` (`URL_PATTERNS`).
4. Add a fixture and a test under `tests/adapters/`.

## Pull requests

Keep them small and single-purpose. Describe the behaviour change in the first line, the reason in the body.
