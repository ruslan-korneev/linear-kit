---
name: handoff
description: Compact the current conversation into a handoff document for another agent or session to pick up. Use before switching sessions/agents, before a long context compaction, or when parking work.
---

# handoff — compact the session for the next agent

Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save
it to the OS temporary directory — not the workspace — unless the work has a `.tasks/<id>/` folder, in
which case `.tasks/<id>/HANDOFF.md` is fine (it is committed provenance).

Include:
- **Goal** — what the user actually wants, in their terms.
- **State** — what is done, what is in flight, what is not started. Branch, PR, and dirty files.
- **Next action** — the single concrete next step.
- **Open questions / blockers** — or a pointer to `.tasks/<id>/OPEN_QUESTIONS.md`.
- **Suggested skills** — which skills the next agent should invoke, in order.

Do not duplicate content already captured in other artifacts (PRDs, plans, ADRs, issues, commits, diffs).
Reference them by path or URL instead.

Redact any sensitive information: API keys, tokens, passwords, personal data.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor
the doc accordingly.
