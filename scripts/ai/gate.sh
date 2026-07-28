#!/usr/bin/env bash
# scripts/ai/gate.sh — machine-checkable ADW gates. Core file: never edited per project.
# Every project-specific command comes from .tasks/_STACK.md.
#
#   gate.sh format [--changed]     run the writing formatter (on-edit hook uses --changed)
#   gate.sh static                 format-check + lint + typecheck
#   gate.sh test [path]            run the suite (or one target)
#   gate.sh red [path]             RED gate: tests MUST fail (TDD step 1)
#   gate.sh green [path]           GREEN gate: static + tests must pass
#   gate.sh groom <id>             G1: no open blocker + 2 quiet passes in GROOM_LOG.md
#   gate.sh plan <id>              G2: PLAN.md + VALIDATION.md complete, acceptance mapped
#   gate.sh workspace <id>         G3: linked worktree + own branch + pushed + draft PR open
#   gate.sh committed              after every step: nothing left uncommitted
#   gate.sh evidence <id>          G5: every VALIDATION.md check has evidence
#   gate.sh ready <id>             G6: PR out of draft + body states what was NOT verified
#   gate.sh all <id>               plan + green + evidence
#
# Exit 0 = gate passed. Exit 1 = gate failed. Exit 2 = misuse/misconfiguration.
# Exit 3 = DEGRADED: the gate never ran a single check, so it verified nothing. Not a pass, not a
#          failure — the run continues, but the summary and the PR must say what was not verified.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$here/lib.sh"

root="$(adw_repo_root)" || adw_die "not a git repo"
cd "$root" || adw_die "cannot enter the repository root: $root"

cmd="${1:-}"; shift || true

changed_files() { git diff --name-only --diff-filter=ACMR HEAD 2>/dev/null; }

gate_format() {
  local fmt; fmt="$(adw_cfg FORMAT_CMD)"
  [[ -n "${fmt// }" ]] || { adw_log "format: SKIPPED (FORMAT_CMD not configured)"; return 0; }
  if [[ "${1:-}" == "--changed" ]]; then
    local files; files="$(changed_files | tr '\n' ' ')"
    [[ -n "${files// }" ]] || return 0
    # Formatters that accept paths get them; the rest run repo-wide.
    bash -c "$fmt $files" >/dev/null 2>&1 || bash -c "$fmt" >/dev/null 2>&1 || true
    return 0
  fi
  adw_run_cmd format "$fmt"
}

# Exit 3 (DEGRADED) when not one of the three ran: "nothing was verified" is a third outcome, and
# collapsing it into 0 is how a project with an empty _STACK.md produces a green run over no checks.
# A partial skip still passes — something did run — but it is reported, because the PR has to say so.
gate_static() {
  local fail=0 ran=0 skipped="" rc pair label key
  for pair in format-check:FORMAT_CHECK_CMD lint:LINT_CMD typecheck:TYPECHECK_CMD; do
    label="${pair%%:*}"; key="${pair#*:}"
    adw_run_cmd "$label" "$(adw_cfg "$key")" "$key"; rc=$?
    case $rc in
      0)              ran=$(( ran + 1 )) ;;
      "$ADW_SKIPPED") skipped="$skipped $label" ;;
      *)              ran=$(( ran + 1 )); fail=1 ;;
    esac
  done
  (( fail )) && return 1
  if (( ran == 0 )); then
    adw_warn "DEGRADED: static — no check ran (${skipped# }). That is not a pass; report it as NOT VERIFIED."
    return $ADW_SKIPPED
  fi
  [[ -n "${skipped// }" ]] && adw_log "static: $ran check(s) ran; never configured:$skipped"
  return 0
}

test_command() {
  local target="${1:-}" one all
  one="$(adw_cfg TEST_ONE_CMD)"; all="$(adw_cfg TEST_CMD)"
  if [[ -n "$target" && -n "${one// }" ]]; then
    printf '%s' "${one//<path>/$target}"
  else
    printf '%s' "$all"
  fi
}

gate_test() { adw_run_cmd test "$(test_command "${1:-}")" TEST_CMD; }

# A test can fail for the wrong reason, or pass for no reason at all. Running the new tests against the
# BASE branch catches the second: a test that is already green without the feature asserts nothing, and
# the implementer will happily write code "to satisfy" it.
gate_red_against_base() {
  local target="${1:-}" base cmd tmp tmp_parent rc out changed
  base="$(adw_cfg BASE_BRANCH main)"
  git rev-parse --verify "$base" >/dev/null 2>&1 || base="origin/$base"
  if ! git rev-parse --verify "$base" >/dev/null 2>&1; then
    adw_warn "RED/base: base branch not found locally — skipping the tautology check"; return 0
  fi

  local test_paths; test_paths="$(adw_cfg TEST_PATHS tests)"
  changed="$( { git diff --name-only "$base"...HEAD -- $test_paths 2>/dev/null;
                git ls-files --others --exclude-standard -- $test_paths 2>/dev/null;
                git diff --name-only HEAD -- $test_paths 2>/dev/null; } | sort -u | sed '/^$/d')"
  if [[ -z "${changed// }" ]]; then
    adw_warn "RED/base: no new or changed test files under '$test_paths' — nothing to verify"; return 0
  fi

  cmd="$(test_command "$target")"
  # `git worktree remove` takes the worktree away but not the mktemp -d that holds it. Removing the
  # parent on every exit path — including the ones that return early below — is why this is a trap
  # rather than an rm before each return.
  tmp_parent="$(mktemp -d)"
  trap 'rm -rf "${tmp_parent:?}"' RETURN
  tmp="$tmp_parent/base"
  adw_log "RED/base: running the new tests against '$base' — they must fail there too"
  if ! git worktree add --detach -q "$tmp" "$base" 2>/dev/null; then
    adw_warn "RED/base: could not create a scratch worktree — skipping"; return 0
  fi

  local f
  while IFS= read -r f; do
    [[ -f "$f" ]] || continue
    mkdir -p "$tmp/$(dirname "$f")" && cp "$f" "$tmp/$f"
  done <<< "$changed"

  ( cd "$tmp" && bash "$here/setup-worktree.sh" >/dev/null 2>&1 )
  out="$( cd "$tmp" && bash -c "$cmd" 2>&1 )"; rc=$?
  git worktree remove --force "$tmp" >/dev/null 2>&1

  if (( rc == 0 )); then
    adw_warn "RED/base FAILED: these tests PASS on '$base', without the feature — they assert nothing new:"
    printf '%s\n' "$changed" | sed 's/^/    /' >&2
    adw_warn "Rewrite them to assert the behaviour the slice adds, then re-run. Do not implement against them."
    return 1
  fi
  adw_log "RED/base OK: the new tests fail on '$base' too (exit $rc)"
  return 0
}

gate_red() {
  local target="" check_base=1 a
  for a in "$@"; do
    case "$a" in
      --no-base) check_base=0 ;;
      *) target="$a" ;;
    esac
  done

  local cmd; cmd="$(test_command "$target")"
  if [[ -z "${cmd// }" ]]; then
    adw_warn "RED gate: no TEST_CMD configured — this project cannot do TDD; use observation checks in VALIDATION.md"
    return 1
  fi
  adw_log "RED gate: expecting failure from: $cmd"
  local out; out="$(bash -c "$cmd" 2>&1)"; local rc=$?
  printf '%s\n' "$out"
  if (( rc == 0 )); then
    adw_warn "RED gate FAILED: the suite passed. A test that passes before the code exists proves nothing."
    return 1
  fi
  adw_log "RED gate OK (exit $rc). Confirm the failure reason is the intended assertion, not a syntax/import error."

  (( check_base )) || { adw_warn "RED/base check skipped (--no-base) — say so in the summary."; return 0; }
  gate_red_against_base "$target"
}

gate_green() {
  local fail=0 static_rc test_rc
  gate_static;              static_rc=$?
  gate_test "${1:-}";       test_rc=$?
  (( static_rc == 1 )) && fail=1
  (( test_rc   == 1 )) && fail=1
  (( fail )) && return 1

  if (( static_rc == ADW_SKIPPED && test_rc == ADW_SKIPPED )); then
    adw_warn "DEGRADED: green — no static check and no suite ran. Nothing about this diff was verified;"
    adw_warn "     GREEN here means 'we looked at nothing'. Configure .tasks/_STACK.md or rely on"
    adw_warn "     observation checks in VALIDATION.md, and say which in the PR's 'Not verified' section."
    return $ADW_SKIPPED
  fi
  (( static_rc == ADW_SKIPPED )) && adw_warn "green: PARTIAL — the suite ran, no static check did. List it under 'Not verified'."
  (( test_rc   == ADW_SKIPPED )) && adw_warn "green: PARTIAL — static checks ran, no suite did. List it under 'Not verified'."
  return 0
}

require_task() { [[ -n "${1:-}" ]] || adw_die "usage: gate.sh $cmd <task-id>"; [[ -d ".tasks/$1" ]] || adw_die "no such task workspace: .tasks/$1"; }

gate_groom() {
  local id="$1" oq=".tasks/$1/OPEN_QUESTIONS.md" log=".tasks/$1/GROOM_LOG.md" fail=0
  if [[ -f "$oq" ]] && sed -n '/^## Blockers/,/^## /p' "$oq" | grep -qE '^[0-9]+\. \*\*'; then
    adw_warn "G1 FAILED: open blocker in $oq — STOP, resolve with the operator."
    fail=1
  fi
  # The lens set IS the coverage. Every lens gets one pass; a lens is repeated only if it found something
  # major, and then only that lens. Counting "quiet passes" instead rewards re-running the same questions:
  # on a real run, passes 5 and 6 produced three minors and no majors, for a third of the token budget.
  local lenses lens closed missing="" profile all_lenses
  all_lenses="$(adw_cfg LENSES contracts,failure-modes,adversary,meta | tr ',' ' ')"
  # The profile decides how much coverage this task earns; PLAN.md records it (workflow-triage).
  # 'superlight' has to be IN the alternation, or "**Profile:** superlight" matches the 'light' inside it
  # and the run is silently groomed as light. Order does not matter — ERE is leftmost-longest, so both
  # alternatives start at the same offset and the longer one wins either way.
  profile="$(grep -m1 -iE '^\s*[-*]?\s*\*\*Profile:\*\*' ".tasks/$id/PLAN.md" 2>/dev/null \
             | grep -oiE 'superlight|light|standard|deep' | head -1 | tr '[:upper:]' '[:lower:]')"
  profile="${profile:-$(adw_cfg DEFAULT_PROFILE standard)}"

  # superlight runs no groom pass, so there is no ledger to demand — but the blocker check above still
  # applies, because a blocker found while planning stops the run at every profile.
  if [[ "$profile" == "superlight" ]]; then
    adw_log "G1: profile 'superlight' → no groom pass required"
    (( fail )) || adw_log "G1 OK: no open blocker"
    return $fail
  fi

  if [[ ! -f "$log" ]]; then
    adw_warn "G1 FAILED: $log missing — run groom-harden at least once."
    return 1
  fi
  case "$profile" in
    light)    lenses="$(printf '%s' "$all_lenses" | awk '{print $1}')" ;;
    standard) lenses="$(printf '%s\n' $all_lenses | grep -xE 'contracts|adversary' | tr '\n' ' ')"
              [[ -n "${lenses// }" ]] || lenses="$(printf '%s' "$all_lenses" | awk '{print $1, $2}')" ;;
    *)        lenses="$all_lenses" ;;
  esac
  adw_log "G1: profile '$profile' → lenses required:$(printf ' %s' $lenses)"
  for lens in $lenses; do
    # last row for this lens: | P<n> | <lens> | <outcome> | <blockers> | <majors> | ...
    local row; row="$(grep -E "^\| *P[0-9]+ *\| *$lens *\|" "$log" | tail -1)"
    if [[ -z "${row// }" ]]; then missing+=" $lens"; continue; fi
    local blockers majors
    blockers="$(printf '%s' "$row" | awk -F'|' '{gsub(/ /,"",$5); print $5}')"
    majors="$(printf '%s'  "$row" | awk -F'|' '{gsub(/ /,"",$6); print $6}')"
    if [[ "${blockers:-0}" != "0" || "${majors:-0}" != "0" ]]; then
      adw_warn "G1: lens '$lens' last reported ${blockers:-?} blocker(s) / ${majors:-?} major(s) — fold them in and re-run THAT lens."
      fail=1
    else
      closed+=" $lens"
    fi
  done
  if [[ -n "${missing// }" ]]; then
    adw_warn "G1 FAILED: no pass recorded for lens(es):$missing — one pass per lens, that is the coverage."
    fail=1
  fi
  (( fail )) || adw_log "G1 OK: every lens closed clean ($(printf '%s' "$closed" | wc -w | tr -d ' ') lenses)"
  return $fail
}

gate_plan() {
  local id="$1" plan=".tasks/$1/PLAN.md" val=".tasks/$1/VALIDATION.md" fail=0
  [[ -f "$plan" ]] || { adw_warn "G2 FAILED: $plan missing"; fail=1; }
  [[ -f "$val"  ]] || { adw_warn "G2 FAILED: $val missing"; fail=1; }
  (( fail )) && return 1
  for section in 'Touches' 'Depends-on' 'Out of scope' 'Decisions locked'; do
    grep -qiF "$section" "$plan" || { adw_warn "G2: PLAN.md missing section '$section'"; fail=1; }
  done
  local checks; checks="$(grep -cE '^\| *[0-9]+ *\|' "$val" || true)"
  if [[ "${checks:-0}" -lt 1 ]]; then
    adw_warn "G2 FAILED: VALIDATION.md has no numbered checks"; fail=1
  else
    adw_log "G2: $checks validation check(s) declared"
  fi
  grep -qiE '\bTBD\b|\bTODO\b|<[a-z-]+>' "$val" && { adw_warn "G2: VALIDATION.md still has placeholders"; fail=1; }
  (( fail )) || adw_log "G2 OK: plan + validation complete"
  return $fail
}

# G3 — the workspace itself. Checked BEFORE any source file is touched: an implementation that starts in
# the operator's checkout, on the base branch, with nothing pushed and no PR, is invisible work. Nobody
# can see it, nothing else can run in parallel, and a crash loses it.
gate_workspace() {
  local id="$1" fail=0 base branch root common main_root
  base="$(adw_cfg BASE_BRANCH main)"
  root="$(git rev-parse --show-toplevel)"
  common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
  main_root="$(dirname "$common")"
  branch="$(git rev-parse --abbrev-ref HEAD)"

  if [[ "$main_root" == "$root" ]]; then
    adw_warn "G3: this is the primary checkout, not a worktree. Create one first:"
    adw_warn "     git worktree add ../$(basename "$root")-$id -b $id-<slug> && cd ../$(basename "$root")-$id && bash scripts/ai/setup-worktree.sh"
    fail=1
  else
    adw_log "G3: worktree OK ($root)"
  fi

  if [[ "$branch" == "$base" || "$branch" == "HEAD" ]]; then
    adw_warn "G3: on '$branch' — implementation never happens on the base branch."
    fail=1
  fi

  if ! git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' >/dev/null 2>&1; then
    adw_warn "G3: branch has no upstream — push it now so the work is visible: git push -u origin HEAD"
    fail=1
  elif [[ -n "$(git log '@{upstream}..HEAD' --oneline 2>/dev/null)" ]]; then
    adw_warn "G3: local commits are not pushed — push after every step, not at the end."
    fail=1
  fi

  if command -v gh >/dev/null 2>&1; then
    local pr_state
    pr_state="$(gh pr view --json isDraft,state -q '.state + " draft=" + (.isDraft|tostring)' 2>/dev/null)" || pr_state=""
    if [[ -z "$pr_state" ]]; then
      adw_warn "G3: no pull request for this branch. Open it as a DRAFT before implementing:"
      adw_warn "     gh pr create --draft --title \"$id: <title>\" --body \"WIP. Plan: .tasks/$id/PLAN.md\""
      fail=1
    else
      adw_log "G3: PR $pr_state"
    fi
  else
    adw_warn "G3: gh not installed — cannot verify the draft PR. Open one by hand or say so in the summary."
  fi

  # The plan is the first commit on the branch. A reviewer who sees code before the reasoning cannot tell
  # a deliberate design from an accident, and an uncommitted .tasks/ dies with the session that wrote it.
  local task_dirty
  task_dirty="$(git status --porcelain ".tasks/$id" 2>/dev/null | grep -v '_worktree.env' || true)"
  if [[ -n "${task_dirty// }" ]]; then
    adw_warn "G3: .tasks/$id is not committed — the plan is the FIRST commit on this branch, before any code:"
    adw_warn "     git add .tasks/$id && git commit -m \"docs(tasks): plan $id\" && git push"
    printf '%s\n' "$task_dirty" | head -10 >&2
    fail=1
  else
    adw_log "G3: .tasks/$id committed"
  fi

  # The harness itself is the operator's to commit, so this is a note rather than a failure.
  local harness_dirty
  harness_dirty="$(git status --porcelain scripts/ai .claude/skills .claude/agents .tasks/_STACK.md 2>/dev/null | head -3 || true)"
  [[ -n "${harness_dirty// }" ]] && adw_warn "G3: harness files are uncommitted (scripts/ai, .claude, _STACK.md) — ask the operator whether to include them."

  # The tracker is where everyone else looks. A ticket still sitting in Todo while a branch, a PR and a
  # worktree exist means two people can pick up the same work.
  if [[ "$(adw_cfg INTAKE_WRITEBACK false)" == "true" && -n "$(adw_cfg INTAKE_CMD)" ]]; then
    local ref want have
    ref="$(ticket_ref "$id")"
    # state names contain spaces ("In Progress") — take everything after the arrow, not one field
    want="$(bash "$(dirname "${BASH_SOURCE[0]}")/intake.sh" states "$ref" 2>/dev/null \
            | sed -n 's/^ *start *→ *//p' | head -1)"
    have="$(bash "$(dirname "${BASH_SOURCE[0]}")/intake.sh" fetch "$ref" 2>/dev/null \
            | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))' 2>/dev/null)"
    if [[ -z "${have// }" ]]; then
      adw_warn "G3: could not read the ticket state for $ref — move it by hand if it is still open."
    # `tr`, not ${x,,}: bash 3.2 — the /bin/bash macOS ships — aborts the whole script on that
    # expansion with "bad substitution", so the gate dies instead of returning a verdict.
    elif [[ -n "${want// }" && "$(lower "$have")" != "$(lower "$want")" ]]; then
      adw_warn "G3: ticket $ref is '$have', not '$want'. Move it now so nobody picks up the same work:"
      adw_warn "     bash scripts/ai/intake.sh writeback $ref --status start"
      fail=1
    else
      adw_log "G3: ticket $ref is '$have'"
    fi
  fi

  (( fail )) || adw_log "G3 OK: worktree, own branch, pushed, PR open, ticket moved"
  return $fail
}

# .tasks/<id> is lowercased; trackers usually key on the original case (smbh-267 → SMBH-267).
ticket_ref() {
  local id="$1"
  if [[ "$id" =~ ^([a-zA-Z]+)-([0-9]+)$ ]]; then
    printf '%s-%s' "$(printf '%s' "${BASH_REMATCH[1]}" | tr '[:lower:]' '[:upper:]')" "${BASH_REMATCH[2]}"
  else
    printf '%s' "$id"
  fi
}

# Run after every step. A step that is not committed does not exist: it cannot be reviewed, reverted,
# or recovered, and a long uncommitted stretch turns into one unreviewable blob.
gate_committed() {
  local dirty; dirty="$(git status --porcelain 2>/dev/null | grep -v '^?? \.tasks/_worktree.env' || true)"
  if [[ -n "${dirty// }" ]]; then
    adw_warn "uncommitted changes — commit this step before starting the next one:"
    printf '%s\n' "$dirty" | head -20 >&2
    return 1
  fi
  if ! git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' >/dev/null 2>&1; then
    adw_warn "branch has no upstream — nothing has ever been pushed: git push -u origin HEAD"
    return 1
  fi
  local unpushed
  unpushed="$(git log '@{upstream}..HEAD' --oneline 2>/dev/null || true)"
  if [[ -n "${unpushed// }" ]]; then
    adw_warn "committed but not pushed ($(printf '%s\n' "$unpushed" | wc -l | tr -d ' ') commit(s)) — push so the PR reflects reality."
    return 1
  fi
  adw_log "step committed and pushed"
  return 0
}

# G6 — handing the PR over. A run that leaves the PR in draft is not finished: the operator has to
# notice, read the artifacts to work out whether it is safe to review, and click the button themselves.
gate_ready() {
  local id="$1" fail=0
  command -v gh >/dev/null 2>&1 || { adw_warn "G6: gh not installed — mark the PR ready for review by hand."; return 0; }

  local pr; pr="$(gh pr view --json isDraft,state,body,number 2>/dev/null)" || pr=""
  if [[ -z "${pr// }" ]]; then
    adw_warn "G6 FAILED: no pull request for this branch."; return 1
  fi

  local is_draft body number
  is_draft="$(printf '%s' "$pr" | python3 -c 'import json,sys; print(json.load(sys.stdin)["isDraft"])' 2>/dev/null)"
  body="$(printf '%s' "$pr" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("body") or "")' 2>/dev/null)"
  number="$(printf '%s' "$pr" | python3 -c 'import json,sys; print(json.load(sys.stdin)["number"])' 2>/dev/null)"

  if [[ "$is_draft" == "True" || "$is_draft" == "true" ]]; then
    adw_warn "G6 FAILED: PR #$number is still a draft. Finish the handoff yourself — do not leave it for the operator:"
    adw_warn "     gh pr ready"
    fail=1
  else
    adw_log "G6: PR #$number is ready for review"
  fi

  # "Tests are green" is true and nearly useless; what the operator needs is which parts were never run.
  if ! printf '%s' "$body" | grep -qiE 'not verified|everything in .?VALIDATION\.md.? was run'; then
    adw_warn "G6 FAILED: the PR body has no \"## Not verified\" section. List every NOT RUN check with its"
    adw_warn "     reason, acceptance never observed, degraded review diversity and skipped gates — or state"
    adw_warn "     plainly that everything in VALIDATION.md was run and passed."
    fail=1
  else
    adw_log "G6: PR body reports what was not verified"
  fi

  (( fail )) || adw_log "G6 OK: PR handed over honestly"
  return $fail
}

gate_evidence() {
  local id="$1" val=".tasks/$1/VALIDATION.md" dir=".tasks/$1/evidence"
  [[ -f "$val" ]] || adw_die "no VALIDATION.md for $id"
  local checks; checks="$(grep -cE '^\| *[0-9]+ *\|' "$val" || true)"
  local files=0; [[ -d "$dir" ]] && files="$(find "$dir" -type f | wc -l | tr -d ' ')"
  if [[ "${files:-0}" -lt "${checks:-0}" ]]; then
    adw_warn "G5 FAILED: $checks check(s) declared, $files evidence file(s) in $dir"
    return 1
  fi
  adw_log "G5 OK: $files evidence file(s) for $checks check(s)"
  return 0
}

case "$cmd" in
  format)   gate_format "${1:-}" ;;
  static)   gate_static ;;
  test)     gate_test "${1:-}" ;;
  red)      gate_red "$@" ;;
  green)    gate_green "${1:-}" ;;
  groom)     require_task "${1:-}"; gate_groom "$1" ;;
  plan)      require_task "${1:-}"; gate_plan "$1" ;;
  workspace) require_task "${1:-}"; gate_workspace "$1" ;;
  committed) gate_committed ;;
  ready)     require_task "${1:-}"; gate_ready "$1" ;;
  evidence)  require_task "${1:-}"; gate_evidence "$1" ;;
  all)      require_task "${1:-}"; rc=0
            gate_plan "$1" || rc=1
            gate_green; green_rc=$?
            (( green_rc == 1 )) && rc=1
            (( green_rc == ADW_SKIPPED && rc == 0 )) && rc=$ADW_SKIPPED   # degraded survives, failure wins
            gate_evidence "$1" || rc=1
            exit $rc ;;
  ""|-h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
  *) adw_die "unknown gate: $cmd" ;;
esac
