# Hungry Hunt — Product Requirements

**Version:** 2.0 · **Status:** Draft for review · **Date:** 2026-10-04
**Replaces:** `JOB_PRD.docx` (v1.0, September 2026)

---

## 1. Overview

Hungry Hunt is an AI job-search agent for early-career software engineers in India who have **no referrals**. Every day it finds **real, open roles** at **good companies**, filters out what doesn't fit, ranks the rest against the candidate's actual resume, and tracks what happens next.

It finds and decides. **The human applies and reaches out.** Hungry Hunt never submits an application or sends a message on anyone's behalf.

> Find the right job → Understand your fit → Reach out yourself → Track → Learn

## 2. Problem

For an engineer with 0–2 years of experience and no referrals, a job search in 2026 looks like this:

- **Fake and stale listings.** Estimates put 18–27% of online listings as ghost jobs. LinkedIn and job portals mix real roles with reposts, scams and expired ads.
- **Generic IT is shrinking while specific skills grow.** Naukri JobSpeak, September 2026: IT/software −4% YoY, AI/ML +20%, GCCs +4%, BFSI fresher hiring +14%. Searching everything wastes time; searching the right segment works.
- **No referral network.** Most strong startup and fintech roles fill through referrals. Without one, the candidate must find the right person to ask, one company at a time.
- **No time.** The candidate already works full time, so a search has to fit into ~5 hours a week.
- **Company quality is invisible.** Layoffs, funding trouble and regulatory shocks (e.g., the 2025 real-money-gaming ban) aren't visible on a job listing.

## 3. Users

| | Who | Need |
|---|---|---|
| **Primary (v1)** | Poojitha: backend engineer (Python, FastAPI, LangGraph, Postgres, Redis, Docker), ~1 year at an AI startup, targeting SDE-1 backend in Bangalore/Hyderabad, switching within 6–12 months | A short daily list of companies with real roles worth applying to |
| **Secondary (v3+)** | Other early-career engineers in India without referrals | The same, with their own profile and filters |

v1 is built for one user. The data model carries a `user_id` from day one so v3 doesn't require a rewrite.

## 4. Principles

1. **Real jobs only.** Jobs come from the company's own applicant tracking system (ATS): public job-board APIs for Greenhouse, Lever, Ashby and SmartRecruiters. No LinkedIn or Naukri scraping, and no anti-detection browsers.
2. **Decide, don't spray.** Fewer, better applications. The product measures relevance, not volume.
3. **The human sends everything.** No auto-apply, no automated connection requests, no automated DMs. Referrals depend on a real person writing a real message.
4. **Never fabricate.** Match explanations and any generated text use only facts from the candidate's resume.
5. **Rules in code, judgement in the LLM.** Location, experience and blocklists are deterministic filters. The LLM only scores fit and explains it, which keeps it cheap, fast and testable.
6. **Explainable.** Every score comes with matching skills, missing skills and a one-line reason.

## 5. Landscape: what we learned from existing tools

| Tool | What it does well | What we take | What we avoid |
|---|---|---|---|
| **HiringCafe** | Indexes jobs straight from company career pages, links to the employer's own portal | **Source jobs from company ATS systems; that's how we avoid fakes** | US-centric, no fit scoring |
| **Jobright.ai** | Ranks jobs against your profile, surfaces "insider" connections | **Explainable match score; a referral-finding step** | Auto-apply |
| **Simplify** | Autofill and tracking, free core | **Free core features; the human clicks apply** | — |
| **Teal / Huntr** | Kanban tracker tied to each application | **Status pipeline per job** | Resume builder scope (later phase) |
| **Auto-apply bots** (LoopCV, ApplyPilot, AIHawk) | Volume | — | **Mass applying, anti-detection scraping, platform ToS risk** |
| **JobSpy** (open source) | Scrapes LinkedIn, Indeed, Glassdoor | — | **Scraping platforms that forbid it** |
| **Open-source LangGraph job agents** | Agent pipeline: search → filter → match | **The stateful-graph structure** | Remote-only or US-only sources |

**Our gap to fill:** none of these is built for **India, early-career, no referrals**, with company-quality filtering (layoffs, stability) built in.

## 6. Core flow

```
Profile (resume + filters)
  → Company registry (curated list, with quality notes)
  → Discovery (ATS APIs, daily)
  → Normalize + dedupe
  → Hard filters (city, experience, role, blocklist)
  → Trust signals (age, reposts, experience mismatch)
  → LLM match (score, matched/missing skills, Apply / Review / Skip)
  → Daily update (companies with fitting roles, ranked)
```

The candidate applies manually from the update.

## 7. Phases

| Phase | Scope | Serves |
|---|---|---|
| **v1: Find and notify** | Sections 8.1–8.7 below | Poojitha |
| v1.1: More sources | A careers-page watcher for companies not on a public ATS API (Workday, Kula, Darwinbox, Keka, custom pages) | Poojitha |
| v1.2: Referral helper and tracker | People-search links, draft referral messages, application status pipeline | Poojitha |
| v2: Resume tailoring | Per-job resume suggestions using only real experience | Poojitha |
| v3: Web app and multi-user | React UI, accounts, onboarding, a shared company registry | Others |
| v4: Browser extension | Match score on any job page | Others |
| v5: Coach | Outcome analytics, skill gaps, interview prep | Both |

## 8. v1 requirements

### 8.1 Profile
- Load the candidate's resume (LaTeX or PDF) and extract skills, experience, projects and education.
- Hold the candidate's filters in one config file: target roles, cities, experience range, remote OK, blocklisted companies.
- Re-extract only when the resume file changes.

### 8.2 Company registry
- A curated, version-controlled list (YAML) of companies. Each entry has: name, ATS type and board slug, cities, founded year, stage, status (`target` / `watch` / `avoid`) and a quality note (e.g., "layoffs 2026", "gaming ban").
- Seeded from `job-search/referral-list-2026-09-24.md`: 9 target companies (10 roles), 14 to watch, 9 to avoid.
- The system never invents company-quality facts. Notes are written by the human.

### 8.3 Discovery
- One adapter per ATS: **Greenhouse, Lever, Ashby, SmartRecruiters**. Each returns a common `Job` record: source, company, title, location, description, URL, posted/updated date and external ID.
- Runs daily. Remembers what it has already seen, so only new or changed jobs reach the LLM.
- If one company's board fails, it logs the failure and moves on; a single bad board never stops the run.

### 8.4 Hard filters (code, not LLM)
- City matches (or remote OK), title matches role keywords, the company isn't blocklisted.
- Experience: parse "X+ years" or "X–Y years"; drop roles whose minimum exceeds the candidate's maximum plus one year of slack.

### 8.5 Trust signals
Shown with each job; v1 doesn't hide jobs because of them.
- **Age:** a job open more than 60 days gets a yellow flag, more than 90 days a red flag.
- **Repost:** the same title at the same company reappears under a new ID.
- **Mismatch:** an "entry-level" or "SDE-1" title that asks for 4+ years.
- **Verified source:** always true in v1 (every job comes from the company's own ATS). Shown so the user knows why it's trustworthy.

### 8.6 LLM match
- Input: the profile plus the job description. Output, as structured JSON: score 0–100, matching skills, missing skills, verdict (`apply` / `review` / `skip`) and a one-line reason.
- The prompt forbids claiming skills that aren't in the resume.
- Results are cached per (job, resume version), so a job is never scored twice.
- The LLM provider is swappable (Gemini / OpenAI / Groq / Claude) behind one interface.

### 8.7 Daily update
- Daily, grouped **by company**: each company with at least one fitting role, its roles ranked by score, each with the score, verdict, one-line reason, trust flags and a direct link to apply on the company's own site.
- Shows what's **new since the last update** first.
- Delivered as a Markdown file plus terminal output. The delivery channel is an open question (section 12).

## 9. Non-goals (v1)
- Auto-applying, form filling or sending any message.
- Scraping LinkedIn, Naukri or any site whose terms forbid it.
- A web UI, user accounts or a browser extension.
- Referral helper and application tracker (moved to v1.2).
- Judging company quality automatically.

## 10. Success metrics (v1, measured on Poojitha's own search)
- **Relevance:** at least 70% of digest jobs marked "worth a look".
- **Time:** at most 15 minutes a day to review the digest.
- **Throughput:** enough fitting roles each week to support 3–5 quality applications.
- **Outcome:** first interview within 6 weeks of daily use.
- **Coverage:** at least 60% of target companies have a working ATS adapter (rising to 90% with v1.1).

## 11. Risks
| Risk | Mitigation |
|---|---|
| Many Indian companies use ATS systems without public APIs (Workday, Kula, Darwinbox) | v1.1 careers-page watcher; measure coverage from day one |
| ATS APIs change or rate-limit | Per-adapter tests with recorded responses; polite daily schedule |
| LLM scores drift or flatter | Store the user's "worth a look" feedback against scores; review weekly |
| Building replaces applying | v1 scoped to about one weekend; apply to the existing list in parallel |

## 12. Open questions
1. **LLM provider and key.** The earlier React plan was blocked on `GEMINI_API_KEY`. Which provider is available today?
2. **Storage.** SQLite for v1 (zero setup) or Postgres (matches Aidra, easier for v3)?
3. **Schedule and delivery.** Run manually, cron on the laptop, or a free hosted scheduler (GitHub Actions)? Delivered by file, email or Telegram?
4. **How far does the company registry extend in v3?** Shared and curated by the community, or one per user?

## Sources
- [Naukri JobSpeak, Sept 2026](https://www.infoedge.in/pdfs/News_Events_pdfs/Naukri-Jobspeak-September-2026.pdf)
- [HiringCafe review](https://jobscoutly.com/reviews/hiringcafe/) · [HiringCafe funding/approach](https://www.citybiz.co/article/910203/hiringcafe-raises-6-8m-for-ai-job-search-engine-that-find-the-hidden-80-of-open-roles/)
- [Jobright vs Simplify](https://jobright.ai/compare/simplify) · [Jobscan: AI job search tools 2026](https://www.jobscan.co/blog/ai-job-search-tools/) · [Glever: AI application tools compared](https://glever.co/blog/best-ai-job-application-tools)
- [tsouk88/job-search-agent (LangGraph)](https://github.com/tsouk88/job-search-agent) · [BjornMelin/ai-job-scraper](https://github.com/BjornMelin/ai-job-scraper) · [JobSpy topic](https://github.com/topics/jobspy) · [ApplyPilot](https://github.com/Pickle-Pixel/ApplyPilot)
- [SmartRecruiters Posting API](https://developers.smartrecruiters.com/docs/get-job-postings)
- [Ghost jobs 2026 (Glider)](https://glider.ai/ghost-jobs-2026-fake-roles/) · [Ghost job (Wikipedia)](https://en.wikipedia.org/wiki/Ghost_job)
