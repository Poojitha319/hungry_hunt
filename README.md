<div align="center">

# 🎯 Hungry Hunt

**A job-search agent that reads company hiring systems directly, drops what does not fit an early-career engineer, scores the rest against your resume, and emails one honest digest a day.**

[![CI](https://github.com/Poojitha319/hungry_hunt/actions/workflows/ci.yml/badge.svg)](https://github.com/Poojitha319/hungry_hunt/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Postgres](https://img.shields.io/badge/Postgres-Neon-4169E1?logo=postgresql&logoColor=white)](https://neon.tech/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Gemini](https://img.shields.io/badge/LLM-Gemini_Flash_Lite-4285F4?logo=google&logoColor=white)](https://ai.google.dev/)
[![mypy](https://img.shields.io/badge/types-mypy-2A6DB2)](https://mypy-lang.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

> *It finds and decides. You apply.*

</div>

---

## The problem

Job boards are built for recruiters. A fresher with no referrals gets aggregator listings that closed weeks ago,
"SDE I" postings that quietly require three years, and a hundred tabs a day to find the four roles that are real.

Every company that hires at scale runs an applicant tracking system, and most expose their live openings as JSON.
Hungry Hunt reads those sources directly. A job reaches your inbox only if it is **posted on the company's own
hiring system**, **still live**, **in India or genuinely remote**, and its **experience bar** is one you can meet.
It never applies or messages anyone on your behalf.

## What it does

| | |
|---|---|
| 🔭 **Discovery** | Seeds, Wayback Machine, Common Crawl, GitHub lists, the YC directory, funding feeds and a headless sniffer turn company names into ATS boards. ~9,100 companies watched. |
| 🧩 **Adapters** | Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Workday, Amazon, Google and JSON-LD careers pages, each read through the system's own API. |
| 🚦 **Rules** | Location, title, seniority, service companies, posting age and the years bar are pure functions with a reason tag per drop and a table-driven test per rule. |
| 🧠 **Scoring** | Gemini scores survivors on a four-part rubric; every claimed skill is checked against the resume, every cited experience figure against the posting. |
| 📬 **Delivery** | One email a day, a delivery ledger so nothing repeats, and a footer that says what the pipeline could not see. |
| 📮 **Tracking** | Forward a hiring email and the tracker links it to the job and advances its status. |
| 🖥 **Review app** | FastAPI + React: digest, job detail with score breakdown, status, outreach drafts, watch-list, coverage. |

---

## Architecture

```mermaid
flowchart LR
    subgraph Sources["The market"]
        ATS[ATS APIs<br/>Greenhouse · Lever · Ashby<br/>SmartRecruiters · Workable · Workday]
        PAGES[Careers pages · Amazon · Google]
        ARCH[Wayback · Common Crawl<br/>GitHub · YC · funding feeds]
    end

    subgraph Pipe["hungry_hunt  ·  GitHub Actions 07:00 + 19:00 IST"]
        D[discovery] --> F[fetch] --> R[rules] --> G[Gemini scoring] --> DG[digest] --> S[send]
        T[tracking]
    end

    DB[(Postgres · Neon)]
    MAIL[Gmail]
    API[FastAPI review API · Render]
    UI[React review app · Cloudflare Pages]
    YOU((You))

    ARCH --> D
    ATS --> F
    PAGES --> F
    Pipe <--> DB
    S --> MAIL --> YOU
    MAIL --> T
    DB --> API --> UI --> YOU
    UI -- status · outreach · watch-list --> API
```

Three ideas hold it together:

1. **Every drop is a pure function with a reason.** `scoring/rules.py` has no I/O. A job that is not in your
   digest has a tag (`location`, `senior`, `years>bar`, `stale_posting`, …) stored on its assessment.
2. **Delivery is a ledger.** A job is "delivered" only after SMTP accepts the message. Anything else rolls into
   tomorrow.
3. **Re-evaluation is keyed, not scheduled.** An assessment is cached under
   `content_hash | rules version | scoring version | years bar`. Change any one and only the affected jobs are
   redone on the next run.

### How a job gets decided

```mermaid
flowchart TD
    J[Job with description] --> stale{posted ≤ 14 days ago?}
    stale -- no --> X1[drop · stale_posting]
    stale -- yes --> comp{company avoided<br/>or a consultancy?}
    comp -- yes --> X2[drop · avoid_company / service_company]
    comp -- no --> loc{India, or remote<br/>without a region restriction?}
    loc -- no --> X3[drop · location]
    loc -- yes --> title{engineering title,<br/>not senior, not excluded?}
    title -- no --> X4[drop · not_engineering / senior / excluded_title]
    title -- yes --> years{years from title, else<br/>from description, > your bar?}
    years -- yes --> X5[drop · years>bar]
    years -- no --> ok[✅ rules passed]

    ok --> gem[Gemini: resume + profile summary<br/>+ company + title + location + description]
    gem --> rubric["skills /40 · seniority /25<br/>domain /20 · practical /15"]
    rubric --> val[validate in code:<br/>skills ∈ resume · years evidence ∈ posting<br/>total summed here, not trusted from the model]
    val --> v{total}
    v -- "≥ 70" --> apply[🟢 apply]
    v -- "45–69" --> review[🟡 review]
    v -- "< 45" --> skip[⚪ skip]
```

Rules run on every job, every time their inputs change, with no model call. Gemini is spent only on jobs that
already passed, and its output is checked against the two documents it was given before anything is stored.

### Data model

```mermaid
erDiagram
    COMPANY ||--o{ JOB : lists
    JOB ||--o{ ASSESSMENT : "per resume version"
    JOB ||--o{ DELIVERY : "sent in digest"
    JOB ||--o| APPLICATION : "your status"
    PROFILE ||--o{ ASSESSMENT : "resume_version"

    COMPANY {
        string ats "greenhouse | lever | ... | careers"
        string slug
        string status "target | watch | avoid"
        string kind "product | service"
        bool dormant "no junior posting in 30 d"
    }
    JOB {
        string external_id
        string title
        text description
        string content_hash
        datetime posted_at
        datetime closed_at
    }
    ASSESSMENT {
        string content_hash "hash | r7 | s2 | b1"
        bool passed_rules
        json rule_fails
        int fit_score
        json breakdown
        string verdict "apply | review | skip"
    }
    DELIVERY {
        string digest_id
        datetime sent_at
        datetime confirmed_at "set after SMTP accepts"
    }
    APPLICATION {
        string status "applied | test | interview | rejected"
        datetime applied_at
    }
    PROFILE {
        string resume_version
        json skills
        json target_titles
        int max_years_bar
    }
```

### The layers

| Layer | Lives in | Responsibility |
|---|---|---|
| Discovery | `discovery/` | Turn the market into `(ats, slug)` boards; classify company kind and tier; record blind spots |
| Adapters | `adapters/` | One module per hiring system → `list[Posting]`; `registry.py` is the only entry point |
| Pipeline | `pipeline/` | Fetch with adaptive cadence (target / watch / dormant / dead), prune, the daily run with per-stage isolation |
| Scoring | `scoring/` | Rules first, Gemini second, validation of the model's claims in code |
| Delivery | `delivery/` | Rank, section, render, send, confirm; grounded outreach drafts |
| Tracking | `tracking/` | IMAP reader for forwarded hiring mail → application status |
| API | `api/` | FastAPI app factory, token auth, routers per resource |
| Core | `core/`, `db/` | SSRF-guarded HTTP client with per-host limits, Pydantic schemas, protocols for fakes, SQLAlchemy models and Alembic migrations |

The full mechanics (daily run, fetch cadence, assessment key, HTTP guard, module dependency graph) are in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Setup, configuration and deployment are in
[docs/OPERATIONS.md](docs/OPERATIONS.md).

---

## Project structure

```
src/hungry_hunt/
├── cli/          parser.py · commands.py
├── core/         http.py · schemas.py · ports.py
├── db/           engine.py · models.py
├── adapters/     greenhouse · lever · ashby · smartrecruiters · workable · workday · amazon · google · careers · registry
├── discovery/    discover.py · seeds.py · funding.py · sitemaps.py · sniff.py
├── pipeline/     fetch.py · prune.py · run.py
├── scoring/      rules.py · gemini.py · assess.py · profile.py
├── delivery/     digest.py · send.py · outreach.py · templates/
├── tracking/     track.py
└── api/          app.py · deps.py · routes/
frontend/         Vite + React review app
migrations/       Alembic
tests/            mirrors src/ · fixtures captured from real APIs · no network
```

## Quick start

```bash
make install                 # uv sync --extra dev (pip fallback) + pre-commit hook
cp .env.example .env         # Gemini key, Gmail app password, review token
make migrate                 # SQLite locally, Postgres in production
hunt profile                 # extract your profile from resume.tex, once per resume
hunt discover --seeds && hunt fetch && hunt assess && hunt digest --preview digest.html
make check                   # ruff · ruff format · mypy · pytest (439 tests, ~7 s)
```

## Engineering notes

- **Tests never touch the network.** DNS is pinned by a fixture, HTTP is mocked, fixtures are real API responses.
- **Strict tooling.** Ruff with the security, bugbear and simplification rule sets, `ruff format`, mypy on
  `src/`, pre-commit, and a CI workflow that runs all of it plus the frontend checks on every push.
- **Hardened outbound HTTP.** Hosts are resolved and refused unless every address is public; redirects are followed
  by hand through the same check; bodies are size-capped; regexes are ReDoS-safe.
- **Own adapters, not a scraping library.** Each ATS has a stable public API. Reading it directly is more reliable
  than HTML scraping and lets discovery cover the whole market rather than a fixed list.
- **Keyed re-evaluation.** Bumping `RULES_VERSION` or `SCORING_VERSION` re-scores exactly the jobs it affects.
- **Blind spots are reported, never hidden.** The digest footer lists hiring systems it cannot read and boards that
  went stale.

## License

MIT. Built by [Sai Poojitha Sajjavarapu](https://github.com/Poojitha319).
