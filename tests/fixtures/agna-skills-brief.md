# Overnight build brief — agna-skills

**Runner:** `/goal course-materials/overnight/agna-skills-brief.md` — Superpowers: brainstorm → plan → execute, until done.
**This file is canonical.** Slide 27 of the course deck carries an abbreviated version; if they disagree, this file wins.

## Mission

The company's Claude Code skills need one home. Build the company skills library: anyone uploads a skill as a zip, and the site turns it into a showcase page with rendered docs, version history, and one-click download. The skills the team writes on Day 1 of the course move in on Day 2.

## Users and auth

- Everyone signs in via Cloudflare Access one-time PIN (a code sent to their email). Zero Trust free plan.
- Any signed-in user can upload and download. No roles.

## Hard constraints

- Cloudflare free tier ONLY: Pages or Workers, D1 for metadata, R2 for zip storage. No paid features. No services outside Cloudflare.
- Authentication exclusively via Cloudflare Access one-time PIN. Never build custom passwords.
- No secrets committed to the repo — use wrangler secrets.
- Uploads capped at 10 MB per zip. Reject anything that is not a zip containing a SKILL.md.

## Skill format (what uploads contain)

A zip with `SKILL.md` at the root (or inside a single top-level directory). SKILL.md starts with YAML frontmatter — `name` (kebab-case, required), `description` (required), `version` (optional) — followed by the instructions as markdown body. The zip may contain any supporting files and directories.

## Must-have

1. Sign-in gate; the uploader's email is recorded on every version
2. Upload zip → validated (SKILL.md present, frontmatter parses) → stored in R2
3. Showcase page per skill: name, description, rendered SKILL.md body, file tree of the zip contents, install hint, download button
4. Versioning: re-uploading the same `name` creates a new version (frontmatter `version` if present, else auto-increment); history listed, every old version still downloadable
5. Index page: browse all skills, search by name and description
6. Seed content: 2–3 realistic multi-file example skills already uploaded
7. Tests for the core logic (zip validation, frontmatter parsing, version bumping), all green

## Stretch (touch only after every must-have is done)

- Syntax-highlighted preview of supporting files
- Per-skill download counts
- A "copy install command" button

## Done-criteria (all must hold, verified against the LIVE deployment)

- Live URL on *.pages.dev or *.workers.dev, behind Access one-time PIN
- A fresh email address can sign in with a PIN
- Uploading a valid multi-file zip produces a showcase page; an invalid zip is rejected with a clear message
- Re-uploading the same name shows version 2, with both versions downloadable
- Search finds the seeded skills; tests green; README covers setup and local development
- JOURNAL.md complete (see below)

## Method — Superpowers

Brainstorm the design first and record the decisions in the journal, write the spec and the plan, then execute with TDD. Loop until every done-criterion verifies against the live deployment, not localhost.

## Journal

Maintain `JOURNAL.md` at the repo root. Timestamped entries (Europe/Tirane): every decision (what and why), every setback (what broke and what you did about it), every milestone (what shipped, with evidence). This journal is read aloud to fifteen people at 09:00 — write it for humans.

## Guardrails

- Work only inside this repository's directory and the Cloudflare project you create for it.
- Commit after every passing milestone. Never force-push. Never rewrite history.
- Blocked more than 30 minutes on one approach? Journal it, then try a different approach.
- Never delete Cloudflare resources you did not create tonight.
- Stop when the done-criteria verify (record the verification in the journal) — or at 07:30, whichever comes first. Journal the final state honestly.
