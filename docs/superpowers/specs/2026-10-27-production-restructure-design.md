# Production restructure and public README — design

Date: 2026-10-27. Status: approved in chat by the owner; nothing is committed by the agent.

## Intent

Make `hungry_hunt` safe and credible to open to the public: a stranger should be able to clone it, understand
every layer from the README, run it, and contribute without asking the owner anything. The scoring and
pipeline logic is already well tested (432 pytest, 10 vitest); the work is structure, operations and docs,
not behaviour.

## Goals

1. A `src/hungry_hunt/` package split by responsibility, tests mirrored by subpackage.
2. Structured logging everywhere the pipeline reports; no silently swallowed exceptions.
3. Strict lint, formatter, type checker, pre-commit, and a CI workflow that runs them on every push/PR.
4. Reproducible installs (lockfile), Dockerfile, Makefile, LICENSE, CONTRIBUTING, SECURITY.
5. A README with Mermaid diagrams and one section per layer, in the owner's own README voice (Aidra, MediBuddy).

## Non-goals

- No behaviour change to rules, scoring, digest content, or adapters. The test suite must pass unchanged in
  meaning (only import paths move).
- No new features. The uncommitted digest/rules changes already in the tree are kept as they are.
- No commits, no pushes. The owner reviews `git status` and commits.
- No function-level docstrings on every function (owner prefers lean code). One-line module docstrings only.

## Anti-goals

- A restructure that breaks the scheduled runs. `render.yaml`, both workflows, `alembic.ini`,
  `scripts/run_local.sh` and the launchd plist must still work after the move.
- Secrets or personal data leaking into the public tree.

## Target layout

```
hungry_hunt/
├── src/hungry_hunt/
│   ├── __init__.py            version
│   ├── __main__.py            python -m hungry_hunt
│   ├── config.py              Settings (pydantic-settings)
│   ├── log.py                 configure_logging(); plain or JSON by LOG_FORMAT
│   ├── cli/                   argparse wiring (parser.py) and one function per command (commands.py)
│   ├── core/                  schemas.py (pydantic DTOs), ports.py (protocols), http.py (safe client, SSRF guard)
│   ├── db/                    engine.py (make_engine with pool_pre_ping/recycle, session_factory), models.py, copy.py
│   ├── adapters/              one module per hiring system + careers.py (JSON-LD/HTML) + html.py (text utils)
│   │                          + registry.py (SUPPORTED, list_jobs, board_url, AtsSource, description fetchers)
│   ├── discovery/             discover.py, seeds.py, sniff.py (Playwright), funding.py, sitemaps.py
│   ├── pipeline/              fetch.py, prune.py, run.py (the daily orchestration lifted out of the CLI)
│   ├── scoring/               rules.py, gemini.py, assess.py, profile.py
│   ├── delivery/              digest.py, send.py, outreach.py, templates/digest.html.j2
│   ├── tracking/              track.py (IMAP application tracker)
│   └── api/                   app.py (factory + middleware), deps.py (auth, session), routes/{health,companies,jobs,digest,outreach}.py
├── frontend/                  the Vite/React review app (was web/ui)
├── migrations/                Alembic (unchanged location; env.py imports updated)
├── tests/                     mirrored: tests/{adapters,discovery,pipeline,scoring,delivery,tracking,api,db,cli}/
├── scripts/                   run_local.sh, launchd plist template
├── data/slugs.json            the only tracked data file
├── docs/                      PRD.md, ARCHITECTURE.md (deeper than README), superpowers/{specs,plans}
├── .github/workflows/         ci.yml (new), daily.yml, discover.yml
├── Dockerfile, .dockerignore, Makefile, LICENSE (MIT), CONTRIBUTING.md, SECURITY.md, CHANGELOG.md
├── .pre-commit-config.yaml, pyproject.toml, uv.lock, alembic.ini, render.yaml, .env.example
└── README.md
```

Module mapping from the flat `hunt/` package:

| old | new |
|---|---|
| `hunt/__main__.py` | `cli/parser.py`, `cli/commands.py`, `pipeline/run.py`, `__main__.py` |
| `hunt/config.py` | `config.py` |
| `hunt/db.py`, `hunt/models.py`, `hunt/copydb.py` | `db/engine.py`, `db/models.py`, `db/copy.py` |
| `hunt/schemas.py`, `hunt/ports.py`, `hunt/http.py` | `core/schemas.py`, `core/ports.py`, `core/http.py` |
| `hunt/ats.py` | `adapters/{greenhouse,lever,ashby,smartrecruiters,workable,workday,amazon,google,careers,html,registry}.py` |
| `hunt/discover.py`, `seeds.py`, `sniff.py`, `funding.py`, `sitemaps.py` | `discovery/` same names |
| `hunt/fetch.py`, `hunt/prune.py` | `pipeline/fetch.py`, `pipeline/prune.py` |
| `hunt/rules.py`, `gemini.py`, `assess.py`, `profile.py` | `scoring/` same names |
| `hunt/digest.py`, `send.py`, `outreach.py`, `templates/` | `delivery/` same names |
| `hunt/track.py` | `tracking/track.py` |
| `web/api/app.py` | `api/app.py`, `api/deps.py`, `api/routes/*.py` |
| `web/ui/` | `frontend/` |

Entry points: console script `hunt = hungry_hunt.cli:main` and `python -m hungry_hunt`. Render start command
becomes `uvicorn hungry_hunt.api.app:app`. Workflows call `hunt run` / `hunt discover ...`.

## Decisions the owner made

- Full-depth restructure (not a top-level tidy).
- Mermaid diagrams, Aidra/MediBuddy voice.
- Agent never commits.

## Decisions made by the builder (owner can override)

- Package import name `hungry_hunt`, console script `hunt`.
- Logging: stdlib `logging`, one logger per module (`logging.getLogger(__name__)`), configured once in the CLI
  and API factory. Plain text by default, JSON lines when `LOG_FORMAT=json`. Pipeline stage summaries that the
  launchd log and GitHub run log rely on are emitted at INFO, so the log text stays readable.
- The four `try/except: pass` sites become `log.debug(..., exc_info=True)` with the same control flow.
- Ruff: `select = ["E","F","I","B","UP","S","SIM","C4","RUF","PTH","N","D100","D104"]`, line length 120,
  `ruff format` adopted (existing per-file ignores kept, `S101` ignored in tests).
- mypy on `src/` with `check_untyped_defs`, `warn_unused_ignores`, `ignore_missing_imports`; the 34 baseline
  errors are fixed, not suppressed, unless a fix would change behaviour.
- Lockfile: `uv.lock` generated with uv; `pip install -e .` still works for people without uv.
- Dockerfile: single image, `python:3.12-slim`, non-root user, installs the package and copies `migrations/`;
  default CMD is the API; the pipeline runs as `docker run image hunt run`.
- License: MIT, copyright "Sai Poojitha Sajjavarapu".
- `JOB_PRD.docx` is deleted from the tree (PRD.md already states it supersedes it; the file stays in git history).
- `web/ui/README.md` (Vite template boilerplate) is replaced with a short real README for the frontend.
- `.heartbeat` commit step in `daily.yml` is removed; run status is visible in Actions and the digest log.
- CI uses `uv` for speed, caches it, runs: ruff check, ruff format --check, mypy, pytest, and in `frontend/`:
  npm ci, typecheck, lint, test, build.

## Operational impacts the owner must act on after review

- Cloudflare Pages root directory setting changes from `web/ui` to `frontend`.
- The launchd plist runs `scripts/run_local.sh`; the script is updated in place, no plist change needed.
- Render redeploys from `render.yaml`; nothing to click.

## Left to the builder

Exact split lines inside `adapters/`, route grouping in `api/routes`, wording of docs, Makefile targets.

## Builder-check rulings (2026-10-27)

- History: the repo goes public with its existing history. The builder scans history for secrets and reviews
  `JOB_PRD.docx` text before hand-off and reports; a rewrite is the owner's call only if something is found.
- Personal values: `render.yaml` `USER_ID` becomes `sync: false`; the plist example uses a generic label;
  `resume_tex` default becomes `./resume.tex` (owner's `.env` keeps their path). The owner's name appears
  only in LICENSE and README credits.
- Tests: files move whole; patch-string targets are repointed and verified by the suite; new tests may be
  added; the count must not go down.
- Adapters: `adapters/registry.py` is the import point for the rest of the code; `core/ports.py` never imports
  adapters; `adapters/__init__.py` re-exports the old `hunt.ats` public names.
- mypy: a targeted `# type: ignore[code]  # reason` is allowed where a fix would change behaviour; listed in the hand-off.
- Ruff: `D100/D104` and `S` rules are not applied to `tests/` and `migrations/`; `BLE001` and `C408` ignores carry over.
- `data/slugs.json` is only a CLI argument (`discover --slugs`), never read package-relative; Docker does not need it.
  Docker copies `alembic.ini` and `migrations/`; workflows keep `alembic upgrade head` from the checkout root.
- `frontend/openapi.json` is generated from the app (`make openapi`); CI checks it for drift.
- Work happens in place with `git mv`; the owner stages what they want per commit.
