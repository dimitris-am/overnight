# Goal condition and provability

The `/goal` checker is a separate small model that reads the conversation and cannot run anything. A criterion only counts as met when the conversation shows proof: the command that was run and its real output.

## Provable (keep as written)

- Test suites: "tests pass" → proven by the test command's output.
- Files and content: "README documents usage" → proven by printing the relevant section.
- Live deployments reachable without logging in: "live URL responds" → proven by `curl -sI <url>` output.
- CLI behavior: "`tally --json` prints valid JSON" → proven by the command and its output.

## Not provable by an agent (propose a proxy, keep the original as a morning check)

| Needs a human because… | Example criterion | Provable proxy |
|---|---|---|
| An email inbox or one-time PIN | "A fresh email address can sign in with a PIN" | "A signed-out request to the live URL redirects to the Cloudflare Access login page (show the HTTP status and Location header)" |
| A real person's account or device | "Works on a phone" | "The page's HTML includes a responsive viewport meta tag and passes an automated mobile-width render check" |
| Subjective judgment | "The design looks polished" | "The pages render without console errors in a headless browser, with screenshots saved to `.overnight/screenshots/`" |

Keep proxies as close to the original intent as possible, and never weaker than a check a skeptical reviewer would accept.
