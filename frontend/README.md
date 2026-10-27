# Review app

The React front end of Hungry Hunt: today's digest, job detail with the rule and score breakdown, application
status, outreach drafts, the company watch-list and pipeline coverage. It talks only to the review API.

```bash
npm ci
npm run gen            # TypeScript client from openapi.json (regenerate with `make openapi` at the root)
VITE_API_URL=http://localhost:8000 npm run dev
npm run lint && npm run typecheck && npm test && npm run build
```

Open it once from the **Review** link in a digest email: the token in the link is stored in `localStorage` and
removed from the URL. Deploy as static files (`dist/`) on Cloudflare Pages with the root directory set to `frontend`
and `VITE_API_URL` pointing at the API; `public/_redirects` handles client-side routing.

Layout: `src/app` (shell and routing), `src/features/*` (one folder per screen), `src/shared/api` (generated client
and React Query hooks), `src/shared/auth` (token handling).
