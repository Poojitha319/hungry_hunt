# Security

## Reporting

Open a private security advisory on GitHub or email the maintainer (see the commit history). Please do not open a
public issue for anything exploitable.

## What the agent does and does not do

- It never applies, never messages anyone and never submits a form. It reads public job boards and sends one email
  to the owner.
- Secrets (database URL, Gemini key, Gmail app password, review token) come only from environment variables or a
  local `.env`, which is git-ignored. Nothing in this repository's history contains a credential.
- Outbound HTTP goes through `src/hungry_hunt/core/http.py`: hosts are resolved and refused if any address is
  private, loopback, link-local or reserved; redirects are followed manually with the same check; response bodies
  are size-capped; per-host concurrency is limited.
- The review API is protected by a single shared bearer token compared in constant time.

## Known limitations

- **DNS rebinding window.** `safe_url` resolves the host before the request; a hostile DNS server could answer with
  a public address first and a private one on the connect. Pinning the validated address into the transport is the
  planned fix.
- **Token in the URL.** The review link in the digest email carries the token as `?t=`; the SPA stores it and drops
  it from the URL on first load, but it still transits mail and browser history. A short-lived session cookie is
  the planned replacement.
- **Forwarded-mail trust.** The tracker accepts mail that Gmail marked `arc=pass` from a trusted domain. A sender
  who can pass ARC through Gmail could inject a fake "interview" event; the effect is limited to a status label in
  the owner's own tracker.
