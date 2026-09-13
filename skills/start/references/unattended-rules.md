<!-- overnight:begin -->
## Unattended run

This project is being built unattended under /goal. No human is present and nobody will answer.
BRIEF.md is the human's approval of the direction. Read it first.

**Superpowers, without a human:**
- brainstorming: answer every clarifying question yourself from BRIEF.md; take the recommended approach; check each design section against BRIEF.md instead of waiting for approval; skip the visual companion. Replace the spec review gate with a fresh-context subagent that compares the spec against BRIEF.md; fix what it finds, then continue.
- writing-plans: always choose subagent-driven development.
- subagent-driven-development and every other skill: work directly on `main` in this repository; no worktrees. Skip finishing-a-development-branch.
- Pre-approved outside actions: {approved_actions}. Anything else that a skill would stop to ask about: log it as `needs-human` in JOURNAL.md, skip it, and continue with other work. Never force-push, spend money, or delete resources this run did not create.

**Record keeping:**
- JOURNAL.md: one line per event, `- HH:MM [decision|setback|milestone|needs-human] text`. Log every question you answered and every choice you made.
- Commit after every milestone.

**Proof of done:**
- Before claiming the goal is met, write `.overnight/evidence.md`: for each numbered done-criterion in .overnight/goal.txt, the exact command you ran and its actual output. Then print that file in the conversation.
- If the goal check says "not met", fix the gap, rerun the affected commands, update and reprint the evidence.

**Stopping:** if `.overnight/STOP` exists, stop starting new work.
<!-- overnight:end -->
