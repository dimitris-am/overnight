# Overnight build brief — agna-answers

**Runner:** `/bmad-loop course-materials/overnight/agna-answers-brief.md` — the BMAD cycle in a loop until done.
**This file is canonical.** Slide 26 of the course deck carries an abbreviated version; if they disagree, this file wins.

## Mission

AGNA staff have questions for the internal tools team, and the answers keep dying in inboxes. Build an internal answers portal: staff sign in with their email, ask the tools team anything, and every answered question joins a searchable knowledge base. Ask once, answered forever.

## Users and auth

- Everyone signs in via Cloudflare Access one-time PIN (a code sent to their email). Zero Trust free plan.
- Two roles: **staff** (ask, browse, search) and **admin** (answer, change status, manage). Admins are an email allowlist in configuration.

## Hard constraints

- Cloudflare free tier ONLY: Pages or Workers, plus D1 for data. No paid features. No services outside Cloudflare.
- Authentication exclusively via Cloudflare Access one-time PIN. Never build custom passwords.
- No secrets committed to the repo — use wrangler secrets.
- Boring, documented technology only. No experimental frameworks.

## Must-have

1. Email sign-in gate; the signed-in identity is visible in the app
2. Ask: title + body; the asker's email is captured automatically
3. Answer: admins reply; a thread is the question plus one or more replies
4. Status per thread: open / answered / closed — visible and filterable
5. Browse newest-first, plus full-text search across questions and answers
6. Admin view: the unanswered queue
7. Seed content: 8–10 realistic English Q&As about Claude Code and internal tools
8. Tests for the core logic (routes, search, status transitions), all green

## Stretch (touch only after every must-have is done)

- Email notification to the asker when answered (Cloudflare Email Routing)
- Albanian/English UI toggle
- Tags or categories

## Done-criteria (all must hold, verified against the LIVE deployment)

- Live URL on *.pages.dev or *.workers.dev, behind Access one-time PIN
- A fresh email address can sign in with a PIN and post a question
- An admin can answer it; the status changes; search finds it
- Seed content present; tests green; README covers setup, roles, and local development
- JOURNAL.md complete (see below)

## Method — BMAD

Run the full cycle: PRD → architecture → sharded stories → implement story by story → QA each story. Loop until every must-have story ships and the done-criteria verify. Re-verify against the live deployment, not localhost.

## Journal

Maintain `JOURNAL.md` at the repo root. Timestamped entries (Europe/Tirane): every decision (what and why), every setback (what broke and what you did about it), every milestone (what shipped, with evidence). This journal is read aloud to fifteen people at 09:00 — write it for humans.

## Guardrails

- Work only inside this repository's directory and the Cloudflare project you create for it.
- Commit after every passing milestone. Never force-push. Never rewrite history.
- Blocked more than 30 minutes on one approach? Journal it, then try a different approach.
- Never delete Cloudflare resources you did not create tonight.
- Stop when the done-criteria verify (record the verification in the journal) — or at 07:30, whichever comes first. Journal the final state honestly.
