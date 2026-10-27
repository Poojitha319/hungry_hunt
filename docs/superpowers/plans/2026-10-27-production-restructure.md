# Production Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the flat `hunt/` prototype into a `src/hungry_hunt/` package with production tooling and a public-grade README, with zero behaviour change.

**Architecture:** Move modules with `git mv` so history survives, rewrite imports mechanically, then split the three oversized modules (`ats.py`, `__main__.py`, `web/api/app.py`) along the seams the design names. Tooling (logging, lint, types, CI, Docker, lockfile) lands after the tree is stable. README last, written against the final tree.

**Tech Stack:** Python 3.12, setuptools src layout, pydantic-settings, SQLAlchemy 2 + Alembic, FastAPI, httpx, google-genai, Jinja2; Vite/React 19/TypeScript frontend; ruff, mypy, pytest, uv, pre-commit, GitHub Actions, Docker.

**Spec:** `docs/superpowers/specs/2026-10-27-production-restructure-design.md`

## Global Constraints

- Never `git commit` or `git push`; the owner commits. "Commit" steps below mean "stop and verify `git status`".
- Behaviour frozen: every existing test keeps its assertions; only import paths change.
- Line length 120. No function docstrings; one-line module docstrings only.
- Package import name `hungry_hunt`; console script `hunt`; `python -m hungry_hunt` works.
- Secrets only via environment / `.env`; `.env` never tracked.
- The uncommitted working-tree changes in `hunt/digest.py`, `hunt/rules.py`, `hunt/templates/digest.html.j2`, `tests/test_digest.py`, `tests/test_rules.py` travel with the move.

## Review Focus

1. `alembic upgrade head` from a clean checkout must still find `hungry_hunt.db.models` (migrations/env.py import). Test: Task 1 step 6.
2. `scripts/run_local.sh` under launchd has no console script on PATH; it must call `.venv/bin/hunt` or `.venv/bin/python -m hungry_hunt`. Test: Task 8 step 5.
3. Jinja template must ship inside the wheel after moving to `delivery/templates`. Test: Task 1 step 7 (`pip install .` in a temp venv, render a digest).
4. `pool_pre_ping` must not be passed to SQLite engines in a way that breaks tests. Test: Task 6 step 4.
5. CI must fail on a formatting drift, not silently pass. Test: Task 7 step 6 (`ruff format --check` exit code).

---

### Task 1: src layout and mechanical move

**Files:**
- Create: `src/hungry_hunt/{__init__,__main__}.py`, subpackage `__init__.py` for `cli core db adapters discovery pipeline scoring delivery tracking api`
- Move (git mv): every `hunt/*.py` per the mapping table in the spec; `hunt/templates/` → `src/hungry_hunt/delivery/templates/`; `web/api/app.py` → `src/hungry_hunt/api/app.py`; `web/ui/` → `frontend/`
- Modify: `pyproject.toml` (src layout, `[project.scripts] hunt = "hungry_hunt.cli:main"`, package-data for templates), `migrations/env.py`, `tests/conftest.py`, all `tests/*.py` imports, `render.yaml`, `.github/workflows/*.yml`, `scripts/run_local.sh`, `.gitignore` (`frontend/node_modules/`, `frontend/dist/`)

**Interfaces:**
- Produces: import roots `hungry_hunt.config.Settings`, `hungry_hunt.db.engine.{make_engine,session_factory,Base}`, `hungry_hunt.db.models.*`, `hungry_hunt.core.{schemas,ports,http}`, `hungry_hunt.adapters.ats` (temporary, split in Task 2), `hungry_hunt.discovery.*`, `hungry_hunt.pipeline.{fetch,prune}`, `hungry_hunt.scoring.*`, `hungry_hunt.delivery.*`, `hungry_hunt.tracking.track`, `hungry_hunt.api.app:app`, `hungry_hunt.cli.main` (temporary alias of the old `main`).
- `hungry_hunt/db/__init__.py` re-exports `Base, make_engine, session_factory` so `from hungry_hunt.db import ...` works.

- [ ] Step 1: `git mv` files per the table; `hunt/ats.py` → `adapters/ats.py`, `hunt/__main__.py` → `cli/__init__.py` (holds `main` until Task 3), `hunt/db.py` → `db/engine.py`, `hunt/copydb.py` → `db/copy.py`.
- [ ] Step 2: rewrite imports with a sed map (`hunt.config`→`hungry_hunt.config`, `hunt.db`→`hungry_hunt.db`, `hunt.models`→`hungry_hunt.db.models`, `hunt.schemas`→`hungry_hunt.core.schemas`, `hunt.ports`→`hungry_hunt.core.ports`, `hunt.http`→`hungry_hunt.core.http`, `hunt.ats`→`hungry_hunt.adapters.ats`, `hunt.sitemaps`→`hungry_hunt.discovery.sitemaps`, `hunt.discover|seeds|sniff|funding`→`hungry_hunt.discovery.X`, `hunt.fetch|prune`→`hungry_hunt.pipeline.X`, `hunt.rules|gemini|assess|profile`→`hungry_hunt.scoring.X`, `hunt.digest|send|outreach`→`hungry_hunt.delivery.X`, `hunt.track`→`hungry_hunt.tracking.track`, `hunt.copydb`→`hungry_hunt.db.copy`, `hunt.__main__`→`hungry_hunt.cli`, `from hunt import a, b`→ one line per module). Also `monkeypatch.setattr("hunt....")` string targets in tests and `patch("hunt....")`.
- [ ] Step 3: `pyproject.toml`: `[tool.setuptools.packages.find] where = ["src"]`; `package-data = {"hungry_hunt.delivery" = ["templates/*.j2"]}`; scripts entry; `[tool.pytest.ini_options] pythonpath` not needed with editable install.
- [ ] Step 4: `pip install -e ".[dev]"`; `rm -rf hunt web/api web/__init__.py hungry_hunt.egg-info` (after confirming `git status` shows them as renamed).
- [ ] Step 5: Run `pytest -q`. Expected: 432 passed.
- [ ] Step 6: Run `alembic upgrade head` against a scratch `sqlite:///tmp.db` (`DATABASE_URL=sqlite:////tmp/x.db`). Expected: migrates to 0008 without ImportError.
- [ ] Step 7: In a temp venv, `pip install .` (non-editable), then `python -c "from hungry_hunt.delivery import digest; import importlib.resources as r; print(r.files('hungry_hunt.delivery').joinpath('templates/digest.html.j2').is_file())"`. Expected: `True`.
- [ ] Step 8: `python -m hungry_hunt --help` and `hunt --help` print the parser help.

### Task 2: Split adapters

**Files:**
- Create: `src/hungry_hunt/adapters/{html,greenhouse,lever,ashby,smartrecruiters,workable,workday,amazon,google,careers,registry}.py`
- Delete: `src/hungry_hunt/adapters/ats.py`
- Modify: callers of `adapters.ats` (`pipeline/fetch.py`, `discovery/discover.py`, `discovery/sniff.py`, `cli`), `tests/test_ats.py`, `tests/test_careers.py`, `tests/test_fetch.py`

**Interfaces:**
- `adapters/html.py`: `html_to_text(s) -> str`, `strip_chrome(page) -> str`, `html_posting(page, url) -> Posting | None`, regex constants `TAG, SPACE, CHROME_TAG, HIRING_CUES, ROLE, MAX_PAGE`.
- Each provider module exposes `parse(...) -> list[Posting]` (was `_greenhouse` etc.) and, where one exists, `async def board(client, slug, limits) -> list[Posting]` and `async def description(client, slug, external_id, limits=None) -> str`.
- `adapters/careers.py`: `jsonld_postings`, `job_links`, `careers_board` (was `_careers_board`), `_job_postings`, `_ldjson_blocks`, `_address`.
- `adapters/registry.py`: `SUPPORTED`, `BOARD_URL`, `API`, `PARSERS`, `PARAMS`, `board_url(ats, slug)`, `async list_jobs(client, ats, slug, limits=None)`, `class AtsSource`, plus the three `*_description` names re-exported for callers.
- `adapters/__init__.py` re-exports the public names the old `hunt.ats` exported so existing tests only change the import line.

- [ ] Step 1: Move code blocks by provider; keep every function body byte-identical.
- [ ] Step 2: Update `tests/test_ats.py` imports to `hungry_hunt.adapters` (public names) and provider modules for private ones.
- [ ] Step 3: `pytest -q tests/test_ats.py tests/test_careers.py tests/test_fetch.py tests/test_discover_sources.py`. Expected: all pass.
- [ ] Step 4: Full `pytest -q`. Expected: 432 passed.

### Task 3: Split CLI and lift the daily run

**Files:**
- Create: `src/hungry_hunt/cli/parser.py` (`build_parser() -> argparse.ArgumentParser`), `src/hungry_hunt/cli/commands.py` (one `cmd_<name>(args, settings) -> int` per subcommand), `src/hungry_hunt/pipeline/run.py` (`run_daily(settings, now=None) -> RunSummary` with the fetch→track→assess→send→prune sequence and the per-stage failure handling that today lives in `main`), `src/hungry_hunt/cli/__init__.py` (`main(argv=None) -> int` dispatches), `src/hungry_hunt/__main__.py` (`raise SystemExit(main())`).
- Modify: `tests/test_cli.py` (imports `build_parser`, `main` from `hungry_hunt.cli`).

**Interfaces:**
- Consumes Task 1 roots.
- Produces: `hungry_hunt.cli.main`, `hungry_hunt.pipeline.run.run_daily`, `RunSummary` dataclass (`fetch: Coverage | None, assess_scored: int, sent: bool, errors: list[str]`).

- [ ] Step 1: Add `tests/test_cli.py::test_run_daily_continues_after_fetch_failure`: monkeypatch `pipeline.fetch.fetch_all` to raise, assert `run_daily` still calls assess and returns `errors == ["fetch: boom"]`.
- [ ] Step 2: Run it; expected FAIL (no `run_daily`).
- [ ] Step 3: Implement the split; `main` stays under 30 lines.
- [ ] Step 4: `pytest -q`. Expected: 433 passed.

### Task 4: Split API

**Files:**
- Create: `src/hungry_hunt/api/deps.py` (`get_settings`, `get_session`, `require_token`), `src/hungry_hunt/api/routes/{health,companies,jobs,digest,outreach}.py` each exposing `router = APIRouter()`, `src/hungry_hunt/api/app.py` (`create_app(settings: Settings | None = None) -> FastAPI` and module-level `app = create_app()`).
- Modify: `tests/test_web.py` (import `create_app`), `render.yaml` start command `uvicorn hungry_hunt.api.app:app`.

- [ ] Step 1: Move routes by prefix; bodies unchanged; CORS and auth middleware in `create_app`.
- [ ] Step 2: `pytest -q tests/test_web.py`. Expected: pass.
- [ ] Step 3: `uvicorn hungry_hunt.api.app:app --port 8011 &` then `curl -s localhost:8011/health`. Expected: 200 JSON. Kill server.
- [ ] Step 4: Regenerate `frontend/openapi.json` from `/openapi.json` and run `npm run gen`; `git diff frontend/src/shared/api/schema.d.ts` is empty (routes unchanged).

### Task 5: Mirror tests

**Files:**
- Move (git mv): `tests/test_ats.py, test_careers.py` → `tests/adapters/`; `test_discover.py, test_discover_sources.py, test_sniff.py, test_funding.py` → `tests/discovery/`; `test_fetch.py, test_prune.py, test_hardening.py` → `tests/pipeline/`; `test_rules.py, test_gemini.py, test_assess.py, test_breakdown.py, test_profile.py` → `tests/scoring/`; `test_digest.py, test_send.py, test_outreach.py` → `tests/delivery/`; `test_track.py` → `tests/tracking/`; `test_web.py` → `tests/api/`; `test_models.py, test_copydb.py` → `tests/db/`; `test_cli.py` → `tests/cli/`. Add `__init__.py` per folder; `tests/fixtures/` stays.
- [ ] Step 1: Move; fix any `fixtures/` relative path (`Path(__file__).parent / "fixtures"` → `tests/conftest.py` exposes a `fixtures_dir` fixture).
- [ ] Step 2: `pytest -q`. Expected: 433 passed, same count.

### Task 6: Logging and resilience

**Files:**
- Create: `src/hungry_hunt/log.py` (`configure_logging(level: str = "INFO", fmt: str | None = None) -> None`; JSON lines when `fmt == "json"`; reads `LOG_LEVEL`/`LOG_FORMAT` from `Settings` fields `log_level`, `log_format`).
- Modify: `config.py` (two new fields), `cli/__init__.py` (call `configure_logging` first), `api/app.py` (same in `create_app`), `cli/commands.py` and `pipeline/run.py` (prints → `log.info` / `log.error`), `tracking/track.py:245,264`, `discovery/sniff.py:46,53` (`log.debug("...", exc_info=True)` instead of bare `pass`/`continue`), `db/engine.py` (`pool_pre_ping=True, pool_recycle=300` only when URL is not SQLite).
- Test: `tests/db/test_engine.py`, `tests/cli/test_cli.py`

- [ ] Step 1: Test `test_make_engine_sqlite_has_no_pool_recycle` and `test_make_engine_postgres_sets_pre_ping` (inspect `engine.pool._pre_ping` / `engine.pool._recycle` with `create_engine(..., poolclass=NullPool)`? no: assert via `make_engine("postgresql+psycopg://u:p@h/db").pool._pre_ping is True` without connecting).
- [ ] Step 2: Test `test_run_logs_stage_summary(caplog)`: `run_daily` with stubbed stages emits an INFO record starting with `fetch:`.
- [ ] Step 3: Run; expected FAIL.
- [ ] Step 4: Implement; `pytest -q`. Expected: all pass, and `ruff check` reports no S110/S112.

### Task 7: Lint, format, types, pre-commit

**Files:**
- Modify: `pyproject.toml` (ruff `select`, per-file ignores `tests/* = ["S101","S105","S106"]`, `[tool.mypy]`), add `.pre-commit-config.yaml` (ruff, ruff-format, mypy, end-of-file, trailing-whitespace).
- Modify: every file ruff/mypy flags.

- [ ] Step 1: `ruff format .` then `ruff check . --fix`; fix the rest by hand (RUF059 in `tests/tracking/test_track.py`: prefix unused unpacked names with `_`).
- [ ] Step 2: `mypy src`. Fix the 34 baseline errors; `# type: ignore[code]` only with a reason comment.
- [ ] Step 3: `pytest -q`. Expected: all pass.
- [ ] Step 4: `pre-commit run --all-files`. Expected: all hooks pass.
- [ ] Step 5: Frontend: `npm run lint` (add script `"lint": "oxlint ."` if missing) and `npm run typecheck` clean.
- [ ] Step 6: Verify `ruff format --check .` exits 0; introduce a deliberate drift in a scratch copy and confirm exit 1 (then discard).

### Task 8: Repo tooling and operations

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `Makefile`, `LICENSE` (MIT, Sai Poojitha Sajjavarapu, 2026), `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md` (Keep a Changelog, `0.1.0` summarising what exists), `.github/workflows/ci.yml`, `uv.lock`, `frontend/README.md` (replace Vite template), `scripts/com.poojitha.hungryhunt.plist.example`.
- Modify: `.github/workflows/daily.yml` (drop heartbeat step and `contents: write`; use `uv`; call `hunt run`), `discover.yml` (same), `scripts/run_local.sh` (`.venv/bin/hunt run`), `.env.example` (add `LOG_LEVEL`, `LOG_FORMAT`), `.gitignore`.
- Delete: `JOB_PRD.docx`.

- [ ] Step 1: Install uv (`pip install uv` into the venv or `brew install uv`); `uv lock`; verify `uv sync --extra dev` in a temp dir reproduces the env and `pytest -q` passes there.
- [ ] Step 2: Dockerfile: `python:3.12-slim`, non-root `app` user, `COPY pyproject.toml uv.lock README.md src migrations alembic.ini`, `pip install .`, `EXPOSE 8000`, `CMD ["uvicorn","hungry_hunt.api.app:app","--host","0.0.0.0","--port","8000"]`. `docker build .` if Docker is available; else note skipped.
- [ ] Step 3: Makefile targets: `install lint fmt typecheck test check run api ui digest-preview migrate lock`.
- [ ] Step 4: `ci.yml`: on push + pull_request; job `python` (uv sync, ruff check, ruff format --check, mypy src, pytest) and job `frontend` (npm ci, lint, typecheck, test, build) with `working-directory: frontend`.
- [ ] Step 5: `bash scripts/run_local.sh` with `DATABASE_URL=sqlite:////tmp/x.db` and no SMTP creds: exits non-zero cleanly with a logged `send` failure, no traceback from a missing module.
- [ ] Step 6: `git status` shows `JOB_PRD.docx` deleted and no `.env`, `hunt.db`, or `digest.html` tracked.

### Task 9: README and architecture doc

**Files:**
- Rewrite: `README.md`
- Create: `docs/ARCHITECTURE.md`

README sections, in order (Aidra voice: centered title, one-line pitch, badges, blockquote tagline, table of contents):
1. Why this exists (the no-referrals fresher problem, "finds and decides, the human applies").
2. What it does (feature table).
3. Architecture: `flowchart LR` system overview (schedulers → pipeline → Neon → API → SPA → Gmail); `flowchart TD` daily run; `flowchart TD` assessment decision (rules gates → Gemini rubric 40/25/20/15 → digest); `erDiagram` for Company, Job, Assessment, Delivery, Application, Profile, Run, FundingSignal; `sequenceDiagram` for one digest email; `flowchart` deployment (GitHub Actions, Render, Cloudflare Pages, Neon, Gmail, launchd fallback).
4. The layers, one subsection each with "what it does / where it lives / how to extend": discovery, adapters, pipeline, scoring (rules then Gemini), delivery, tracking, API, frontend, storage and migrations, CLI, scheduling.
5. Hiring systems supported (table: ATS, slug form, how discovered, description source, status) including the known blind spots.
6. Project structure (tree).
7. Getting started (uv and pip paths), configuration (table of every Settings field with default and meaning), running the pipeline, the review app, Docker.
8. Deployment (GitHub secrets/vars list, Render, Cloudflare Pages root `frontend`, launchd fallback).
9. Testing and quality (commands, what CI runs).
10. Design decisions (why own ATS adapters, why rules before LLM, why delivery is a ledger, why no auto-apply, why Gemini Flash Lite, adaptive fetch cadence, posting-age cap).
11. Known limitations, Roadmap, License.

- [ ] Step 1: Write README; every path in it must exist (`grep -oE '\`[a-z_/.]+\.(py|yml|toml|md|sh|json)\`' README.md | tr -d '\`' | xargs ls` passes).
- [ ] Step 2: Render-check Mermaid blocks with `npx -y @mermaid-js/mermaid-cli -i README.md -o /tmp/readme.md` or at minimum `npx -y mermaid-isvalid`; if unavailable, paste each block into a scratch `.mmd` and run `mmdc` once. Expected: no parse errors.
- [ ] Step 3: `docs/ARCHITECTURE.md`: module dependency diagram (`flowchart` of subpackages, arrows = imports), the assessment key / versioning rules (`RULES_VERSION`, `SCORING_VERSION`, `|b{bar}`), fetch cadence state machine (target / watch / dormant / dead), and the SSRF guard.

### Task 10: Final verification

- [ ] `make check` (ruff, format check, mypy, pytest) green; `cd frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build` green.
- [ ] `alembic upgrade head` on scratch SQLite; `hunt digest --preview /tmp/d.html` on scratch DB writes a file.
- [ ] `git status --short` reviewed: renames, no stray binaries, no secrets; print the summary for the owner.
- [ ] Dispatch one fresh reviewer over the whole working tree diff (`git diff HEAD --stat` plus key files) and fix what it finds.
