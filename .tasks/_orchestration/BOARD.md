# Orchestration board

Single source of truth for what is in flight. Maintained by the `orchestrate` skill; refreshed every
monitor pass. States: `queued → grooming → ready → running → review → blocked → failed → pr-open → merged`.

| id | state | branch | depends-on | touches | task id | last checked | PR | notes |
| -- | ----- | ------ | ---------- | ------- | ------- | ------------ | -- | ----- |

## Rules

- Two slices run in parallel **only** if their `Touches` do not overlap and neither `Depends-on` the other.
- Conflicts are re-evaluated **at launch time**, against currently-running slices — not stale groom data.
- Transient failure → auto-retry ≤3, then escalate. A real `blocker` → escalate immediately, no retry.
- Merge order respects `Depends-on`; one PR to the base branch at a time; after each merge, flag which
  in-flight branches must rebase.
- Merging is the operator's call. The orchestrator recommends only.
