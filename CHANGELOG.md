# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Changed
- Restructured the flat `hunt/` package into `src/hungry_hunt/` with `adapters`, `discovery`, `pipeline`, `scoring`,
  `delivery`, `tracking`, `api`, `db`, `core` and `cli` subpackages; tests mirror the layout.
- One adapter module per hiring system; `adapters/registry.py` is the single entry point.
- The review API is split into routers with an app factory; `create_app()` keeps its injection points.
- All pipeline output goes through `logging` (plain or JSON via `LOG_FORMAT`); no bare `except: pass` remains.
- Postgres engines recycle pooled connections every 5 minutes and pre-ping, which fixes dropped Neon connections on
  long runs.
- Strict ruff rule set, `ruff format`, mypy, pre-commit and a CI workflow on every push and pull request.
- `uv.lock` for reproducible installs; Dockerfile for the API image; Makefile for the common commands.
- Frontend moved from `web/ui` to `frontend/`.

### Removed
- The heartbeat commit step from the daily workflow.
- The digest preview artifact from the daily workflow: on a public repo artifacts are downloadable by any signed-in user and the HTML carried review links with the token.
- `JOB_PRD.docx` (superseded by `docs/PRD.md`).

## [0.1.0] - 2026-10-15

### Added
- Discovery from seeds, Wayback, Common Crawl, GitHub, YC, careers pages, funding feeds and a headless sniffer.
- Adapters for Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Workday, Amazon, Google and JSON-LD careers pages.
- Deterministic drop rules (location, title, seniority, posting age) and Gemini scoring with a four-part rubric.
- Daily digest email with a delivery ledger, review API and React review app.
- Application tracker over forwarded hiring mail.
- Adaptive fetch cadence (target / watch / dormant / dead boards).
