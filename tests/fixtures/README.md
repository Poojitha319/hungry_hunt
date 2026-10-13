# Fixtures

Real responses, trimmed to ≤3 postings and short descriptions. Refresh when an adapter test starts failing against
production:

```bash
curl -s "https://api.lever.co/v0/postings/hevodata?mode=json" | python3 -c 'import json,sys; d=json.load(sys.stdin)[:3]; print(json.dumps(d, indent=1))' > lever_hevodata.json
curl -s "https://boards-api.greenhouse.io/v1/boards/observeai/jobs" | python3 -c 'import json,sys; d=json.load(sys.stdin); d["jobs"]=d["jobs"][:3]; print(json.dumps(d, indent=1))' > greenhouse_observeai_list.json
curl -s "https://boards-api.greenhouse.io/v1/boards/observeai/jobs/<id>" > greenhouse_job_content.json
curl -s "https://api.ashbyhq.com/posting-api/job-board/atlan" | python3 -c 'import json,sys; d=json.load(sys.stdin); d["jobs"]=d["jobs"][:3]; print(json.dumps(d, indent=1))' > ashby_atlan.json
```

`wayback_cdx.json`, `cc_cdx_truncated.txt`, `github_newgrad_readme.md`, `careers_page*.html`, `yc_sample.json` and
`resume_sample.tex` are hand-written to exercise specific edge cases (truncated lines, junk slugs, unsupported ATS
hosts, LaTeX macros). The real resume is never a fixture.
