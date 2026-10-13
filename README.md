# Hungry Hunt

Finds **genuine** job openings for an early-career engineer in India and delivers them as a daily email with direct
apply links, plus a small review app. Genuine means: posted on the company's own hiring system (never an aggregator or
agency), still live, and with an experience bar — read from the description, not the title — that a 0–2 year engineer
can meet. The agent never applies, never messages anyone, and never invents a fact about the candidate.

```
discover (weekly) → fetch (daily) → assess (rules, then Gemini) → digest → send (Gmail) → prune
                       ↓ Postgres (Neon) / SQLite locally
                 FastAPI review API  ←  React review app
```

Every drop decision is a pure function in `hunt/rules.py` with a table-driven test. Delivery is a ledger: a job is
"delivered" only after SMTP accepts the message; anything else rolls into tomorrow. The digest footer reports what the
pipeline could not see (unsupported hiring systems, stale boards, Gemini quota).

## Run it locally

```bash
python3.12 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
cp .env.example .env                      # fill GEMINI_API_KEY, SMTP_USER, SMTP_PASSWORD, DIGEST_TO, REVIEW_TOKEN
alembic upgrade head                      # SQLite hunt.db by default
python -m hunt profile                    # reads ../Poojitha_resume.tex once per change (local only — never in CI)
python -m hunt discover --seeds           # referral list + verified boards
python -m hunt discover --slugs data/slugs.json   # 8.7k boards harvested from Common Crawl (optional, one-off)
python -m hunt fetch --only lever:hevodata,greenhouse:observeai,ashby:atlan
python -m hunt assess --max-calls 20
python -m hunt digest --preview digest.html && open digest.html
python -m hunt send                       # or: python -m hunt run   (fetch → assess → send → prune)

uvicorn web.api.app:app --reload          # API on :8000
cd web/ui && npm ci && npm run gen && npm run dev   # SPA on :5173 (VITE_API_URL=http://localhost:8000)
pytest -q && ruff check . && (cd web/ui && npm test && npm run typecheck)
```

Open the SPA from the **Review** link in a digest email once: it stores the token and drops it from the URL.

## Hiring systems the agent can read

| `discover add …` | Source | Notes |
|---|---|---|
| `greenhouse:slug`, `lever:slug`, `ashby:slug` | public JSON APIs | EU hosts tried on 404 |
| `smartrecruiters:slug` | public JSON API | paginated; descriptions fetched per job |
| `workable_feed:India` | jobs.workable.com aggregate feed | one feed covers every Workable account hiring in India; companies appear as `workable:` rows (never polled directly: apply.workable.com rate-bans) |
| `workday:host.wdN.myworkdayjobs.com/tenant/site` | Workday CXS JSON | host must be `*.myworkdayjobs.com` |
| `amazon:IND`, `google:India` | amazon.jobs / Google Careers search feeds | descriptions inline |
| `careers:https://…` | company careers page | JSON-LD `JobPosting`, one-level link crawl, then sitemap job URLs + plain-HTML job pages |

Any board URL works too (`discover add https://jobs.lever.co/hevodata`). For pages rendered only by JavaScript the weekly
`discover --sources sniff` step opens the page headlessly (Playwright, `pip install '.[sniff]'`), watches every frame and
API call the app makes, and upgrades the company to the hiring system it finds (PhonePe and Swiggy both turned out to front
SmartRecruiters). What it still cannot read (Microsoft's Eightfold site, Darwinbox/Keka tenants) stays listed as a **blind spot**
in every digest.

## Hosting ($0)

| Piece | Where | Notes |
|---|---|---|
| Pipeline | GitHub Actions `daily.yml`, 07:00 and 19:00 IST | commits `.heartbeat` so the schedule is never auto-disabled |
| Weekly discovery | GitHub Actions `discover.yml`, Sunday | Wayback + Common Crawl + GitHub lists + YC + careers-page probe |
| Database | Neon Postgres (pooled URL, `sslmode=require`) | `DATABASE_URL` secret |
| Review API | Render free web service | `uvicorn web.api.app:app --host 0.0.0.0 --port $PORT` |
| Review app | Cloudflare Pages, build `web/ui` | `VITE_API_URL` = the Render URL |

Secrets: `DATABASE_URL GEMINI_API_KEY SMTP_USER SMTP_PASSWORD DIGEST_TO REVIEW_TOKEN`. Variables: `REVIEW_BASE_URL
GEMINI_MODEL USER_ID`. Score the first backlog from a laptop (`assess --max-calls 1000`), not in Actions.

## Sources, and what is deliberately not one

Read: Greenhouse, Lever, Ashby public job-board APIs (keyless, the same data the careers pages render), Wayback/Common
Crawl indexes to *find* boards, YC's public dataset, public GitHub job lists, and companies' own careers pages.
Never: LinkedIn, Naukri, Indeed, HiringCafe or any site whose terms forbid automated access.

## Tests

`tests/fixtures/` holds trimmed real board responses (≤3 postings each). Refresh with the `curl`s in
`tests/fixtures/README.md`. The resume used in tests is synthetic.

## Going live (first time)

```bash
# 1. migrate the hosted database and copy the local one into it (keeps every Gemini score)
DATABASE_URL="$NEON_DATABASE_URL" alembic upgrade head
python -m hunt.copydb sqlite:///hunt.db "$NEON_DATABASE_URL"

# 2. prove the hosted database works from here
DATABASE_URL="$NEON_DATABASE_URL" python -m hunt fetch --only lever:hevodata
DATABASE_URL="$NEON_DATABASE_URL" python -m hunt digest --preview /tmp/digest.html

# 3. push, add the GitHub secrets/variables listed above, then trigger the first cloud run
gh workflow run daily.yml && gh run watch
```

Render (API) reads `render.yaml`; Cloudflare Pages builds `web/ui` (`npm ci && npm run build`, output `dist`,
env `VITE_API_URL`). Then set `REVIEW_BASE_URL` to the Pages URL so email links open the app.
