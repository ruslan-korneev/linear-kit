#!/usr/bin/env bash
# scripts/ai/review.sh — review fan-out: one reviewer per rubric lens + a wildcard, run in parallel,
# then a judge that dedupes and adversarially verifies. Core file.
#
#   review.sh <round> [validation-path] [--profile superlight|light|standard|deep] [--lenses a,b,c]
#
# superlight → same as light: one reviewer is the floor, not something a profile can drop
# light    → 1 reviewer, no wildcard, no judge
# standard → 3 lenses + wildcard, no judge (raw findings)
# deep     → all configured lenses + wildcard + judge (deduped, verified, ranked)
#
# Findings land in .tasks/<id>/review/round-<n>/ and are posted to the PR when `gh` is available.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$here/lib.sh"

root="$(adw_repo_root)" || adw_die "not a git repo"
cd "$root" || adw_die "cannot enter the repository root: $root"

round="${1:-1}"; shift || true
validation=""; profile=""; lenses=""
while (( $# )); do
  case "$1" in
    --profile) profile="${2:-}"; shift 2 ;;
    --lenses)  lenses="${2:-}"; shift 2 ;;
    *) [[ -z "$validation" ]] && validation="$1"; shift ;;
  esac
done

base="$(adw_cfg BASE_BRANCH main)"
branch="$(git rev-parse --abbrev-ref HEAD)"
profile="${profile:-$(adw_cfg DEFAULT_PROFILE standard)}"
lenses="${lenses:-$(adw_cfg REVIEW_LENSES correctness,security,performance,architecture,tests)}"

case "$profile" in
  # One reviewer is the floor. A run with none is a solo run awarding itself a green tick, and the
  # cheapest independent look at a diff is one agent — so superlight buys a smaller loop, not no review.
  superlight|light) IFS=',' read -ra lens_list <<< "correctness"; wildcard=0; judge=0 ;;
  # wildcard + judge stay on at standard: on the evidence, the majors come from the adversarial angle,
  # and an unjudged fan-out hands the operator six overlapping lists instead of one verified one.
  standard) IFS=',' read -ra all <<< "$lenses"; lens_list=("${all[@]:0:3}"); wildcard=1; judge=1 ;;
  deep)     IFS=',' read -ra lens_list <<< "$lenses"; wildcard=1; judge=1 ;;
  *) adw_die "unknown profile: $profile (superlight|light|standard|deep)" ;;
esac

rubric_file=""
for c in .claude/skills/slice-review/SKILL.md .codex/skills/slice-review/SKILL.md; do
  [[ -f "$c" ]] && { rubric_file="$c"; break; }
done
[[ -n "$rubric_file" ]] || adw_die "missing rubric: install the slice-review skill"

base_rubric="$(sed -n '/^## Reviewer rubric/,/^## Lens/p' "$rubric_file" | sed '$d')"
[[ -n "${base_rubric// }" ]] || adw_die "could not extract the rubric from $rubric_file"
lens_block() { sed -n "/^### lens: $1\$/,/^### /p" "$rubric_file" | sed '$d'; }

task_id=""
[[ -n "$validation" ]] && task_id="$(printf '%s' "$validation" | sed -E 's#^\.tasks/([^/]+)/.*#\1#')"
outdir=".tasks/${task_id:-_review}/review/round-$round"
mkdir -p "$outdir"

# Reviewers run as separate CLI processes: their tokens never appear in the launching session's /cost.
# Without this the operator picks a profile blind — "roughly twice as expensive" is not a number.
export ADW_USAGE_FILE="$outdir/.usage.tsv"
: > "$ADW_USAGE_FILE"
start_ts="$(date -u +%s)"

diversity="$("$here/engines.sh" diversity)"
case "$diversity" in
  DEGRADED)    adw_warn "one usable engine → the reviewer shares the implementer's blind spots. Labelled DIVERSITY: DEGRADED — not an independent verdict. Widen with: bash scripts/ai/engines.sh probe --write" ;;
  CROSS-MODEL) adw_log  "single vendor, multiple models → DIVERSITY: CROSS-MODEL (real, weaker than cross-engine)" ;;
esac

context_common=$'\n\n'"CONTEXT: branch '$branch' vs '$base' (review round $round). Diff: git diff $base...HEAD."
[[ -n "$validation" ]] && context_common+=$'\n'"Validation criteria: $validation — re-run the checks you can (static + tests + READ-ONLY inspection). Never run destructive or shared-state-mutating checks. A check with no reproducible evidence is NOT passed."

count=$(( ${#lens_list[@]} + wildcard ))
# `while read`, not mapfile: mapfile is bash 4+. On bash 3.2 it is simply not a command, and the next
# line reads ${engines[0]} under `set -u` and aborts — a review that dies before spawning a reviewer.
engines=(); while IFS= read -r _line; do engines+=("$_line"); done < <("$here/engines.sh" pick-review "$count")
usable=();  while IFS= read -r _line; do usable+=("$_line");  done < <("$here/engines.sh" list 2>/dev/null)

# engines.sh writes its own diagnosis to stderr and exits, which leaves this array empty rather than
# unset. Saying so here beats letting an array subscript deliver the news: the operator otherwise gets
# the real reason followed by a bash "unbound variable", and on bash 3.2 the abort comes first.
(( ${#engines[@]} )) || adw_die "no review engine available (see the error above). Fix with: bash scripts/ai/engines.sh probe --write"

# run_lens <engine> <outfile> <prompt> — retries once on a different usable engine when output is empty
# (an unauthenticated or rate-limited CLI fails silently; a missing lens must not look like a clean lens).
run_lens() {
  local engine="$1" out="$2" prompt="$3" e
  printf '%s' "$prompt" | "$here/engines.sh" run "$engine" > "$out" 2>/dev/null
  if [[ ! -s "$out" ]]; then
    for e in ${usable[@]+"${usable[@]}"}; do
      [[ "$e" == "$engine" ]] && continue
      adw_warn "engine '$engine' returned nothing for $(basename "$out" .md) → retrying on '$e'"
      printf '%s' "$prompt" | "$here/engines.sh" run "$e" > "$out" 2>/dev/null
      [[ -s "$out" ]] && { engine="$e"; break; }
    done
  fi
  printf '%s' "$engine"
}
adw_log "round $round · profile $profile · ${#lens_list[@]} lens reviewer(s) + wildcard=$wildcard + judge=$judge · diversity=$diversity"

pids=(); idx=0
for lens in ${lens_list[@]+"${lens_list[@]}"}; do
  engine="${engines[$idx]}"; out="$outdir/lens-$lens.md"
  prompt="$(printf '%s\n%s\n%s\n' "$base_rubric" "$(lens_block "$lens")" "$context_common")"
  {
    used="$(run_lens "$engine" "$out" "$prompt")"
    printf '\n<!-- engine: %s · lens: %s · diversity: %s -->\n' "$used" "$lens" "$diversity" >> "$out"
  } &
  pids+=($!); idx=$((idx+1))
done

if (( wildcard )); then
  engine="${engines[$idx]}"; out="$outdir/lens-wildcard.md"
  prompt="$(printf '%s\n%s\n%s\n%s\n' "$base_rubric" "$(lens_block wildcard)" \
    "The other reviewers on this diff cover exactly these lenses: ${lens_list[*]-}. Anything inside them is THEIR job — do not duplicate it." \
    "$context_common")"
  {
    used="$(run_lens "$engine" "$out" "$prompt")"
    printf '\n<!-- engine: %s · lens: wildcard · diversity: %s -->\n' "$used" "$diversity" >> "$out"
  } &
  pids+=($!)
fi

for p in ${pids[@]+"${pids[@]}"}; do wait "$p" || true; done

findings_files=("$outdir"/lens-*.md)
combined="$outdir/findings.md"
{
  printf '# Review round %s — profile %s — diversity %s\n\n' "$round" "$profile" "$diversity"
  for f in ${findings_files[@]+"${findings_files[@]}"}; do
    [[ -s "$f" ]] || { adw_warn "empty output: $f"; continue; }
    printf '\n## %s\n\n' "$(basename "$f" .md)"; cat "$f"
  done
} > "$combined"

final="$combined"
if (( judge )); then
  judge_engine="$("$here/engines.sh" pick-review 1)"
  judged="$outdir/verdict.md"
  {
    sed -n '/^## Judge rubric/,/^## Notes/p' "$rubric_file" | sed '$d'
    printf '\n\nFINDINGS FROM THE FAN-OUT (dedupe, verify, rank these):\n\n'
    cat "$combined"
    printf '\n%s\n' "$context_common"
  } | "$here/engines.sh" run "$judge_engine" > "$judged" 2>/dev/null
  if [[ -s "$judged" ]]; then
    printf '\n<!-- judge engine: %s -->\n' "$judge_engine" >> "$judged"
    final="$judged"
  else
    adw_warn "judge produced no output — falling back to raw findings"
  fi
fi

if [[ ! -s "$final" ]]; then adw_die "no reviewer output (all engines failed)"; fi

# Cost report — one row per engine call, plus a total. Reported even when partial.
{
  printf '# Review round %s — cost\n\nprofile: %s · lenses: %s · wildcard: %s · judge: %s · diversity: %s\n' \
    "$round" "$profile" "${lens_list[*]-}" "$wildcard" "$judge" "$diversity"
  printf 'wall clock: %ss\n\n' "$(( $(date -u +%s) - start_ts ))"
  if [[ -s "$ADW_USAGE_FILE" ]]; then
    printf '| call | input | output | cache |\n| --- | --- | --- | --- |\n'
    awk -F'\t' '{printf "| %s | %s | %s | %s |\n", $1, $2, $3, $4; i+=$2; o+=$3; c+=$4}
                END {printf "| **total** | **%d** | **%d** | **%d** |\n", i, o, c}' "$ADW_USAGE_FILE"
  else
    printf '_No usage reported: the engine did not return a JSON envelope. Wall clock above is all we have._\n'
  fi
} > "$outdir/cost.md"
rm -f "$ADW_USAGE_FILE"
adw_log "cost → $outdir/cost.md"

if command -v gh >/dev/null 2>&1 && gh pr view >/dev/null 2>&1; then
  { printf 'ADW review round %s (profile %s, diversity %s)\n\n' "$round" "$profile" "$diversity"; cat "$final"; } \
    | gh pr comment --body-file - >/dev/null 2>&1 \
    && adw_log "posted to PR" || adw_warn "could not post PR comment"
fi

cat "$final"
adw_log "artifacts: $outdir"
printf '%s' "$(cat "$final")" | grep -Eo 'VERDICT: (APPROVED|CHANGES_REQUESTED)' | tail -1 || {
  adw_warn "no VERDICT line found — treat as CHANGES_REQUESTED"; printf 'VERDICT: CHANGES_REQUESTED\n'; }
