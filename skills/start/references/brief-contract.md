# Brief contract

A brief is a markdown file. `overnight` needs these sections (level-2 or level-3 headings; matching ignores case and any suffix after a space plus "(" or a dash):

| Section | Accepted headings | Requirement |
|---|---|---|
| Mission | Mission | Not empty |
| Hard constraints | Hard constraints, Constraints | At least one list item |
| Must-have | Must-have, Must-haves, Must have, Requirements | At least one list item |
| Done-criteria | Done-criteria, Done criteria, Definition of done | At least one list item; each item is one checkable statement |
| Guardrails | Guardrails | At least one list item; the first `HH:MM` here is the stop time, unless `--until HH:MM` is passed |

Other sections (Users and auth, Stretch, Method, Journal) are kept as they are and read by the build like any other part of the brief.

Write done-criteria that a command can prove: "`npm test` passes", "`curl -sI https://…` returns 302 to the Access login". Criteria that need a person (receiving an email, looking at a design) are converted to provable proxies at launch and kept as morning checks.
