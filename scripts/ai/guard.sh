#!/usr/bin/env bash
# scripts/ai/guard.sh — enforce phase file-scope on the working diff. Core file.
#
# Agent identity is defined by what it may NOT touch. Prompts are advisory; this is mechanical.
#
#   guard.sh builder      → the diff must NOT touch test paths (tests are the spec; the implementer
#                           may not bend them to fit the implementation)
#   guard.sh test-author  → the diff must NOT touch source paths (tests first, no peeking impl)
#   guard.sh reviewer     → the diff must be empty (reviewers are read-only)
#   guard.sh planner      → the diff may only touch .tasks/
#   guard.sh siblings     → sibling repositories listed in SIBLING_REPOS have no uncommitted changes
#
# Paths come from TEST_PATHS / SRC_PATHS in .tasks/_STACK.md. Compares against the base branch by
# default; pass --staged or --head to scope differently.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$here/lib.sh"

root="$(adw_repo_root)" || adw_die "not a git repo"
cd "$root" || adw_die "cannot enter the repository root: $root"

role="${1:-}"; scope="${2:---branch}"
[[ -n "$role" ]] || adw_die "usage: guard.sh <builder|test-author|reviewer|planner|siblings> [--branch|--staged|--head]"

base="$(adw_cfg BASE_BRANCH main)"
case "$scope" in
  --branch) files="$(git diff --name-only "$base"...HEAD 2>/dev/null; git diff --name-only HEAD 2>/dev/null)" ;;
  --staged) files="$(git diff --name-only --cached)" ;;
  --head)   files="$(git diff --name-only HEAD)" ;;
  *) adw_die "unknown scope: $scope" ;;
esac
files="$(printf '%s\n' "$files" | sed '/^$/d' | sort -u)"

matches() { # $1 = space-separated path prefixes
  local prefixes="$1" f p
  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    for p in $prefixes; do
      [[ -n "$p" ]] || continue
      case "$f" in "$p"/*|"$p") printf '%s\n' "$f" ;; esac
    done
  done <<< "$files"
}

# A harness instance covers ONE repository, so nothing in this repo's diff can show an edit made in a
# sibling checkout. In a multi-repo product that is the easiest boundary to cross by accident: the slice
# touches the client, the agent "just fixes" the shared core next door, and no gate here ever sees it.
# SIBLING_REPOS=<path>[:ro|:ask] — a dirty sibling is reported; :ro means it must never be touched.
if [[ "$role" == "siblings" ]]; then
  siblings="$(adw_cfg SIBLING_REPOS)"
  if [[ -z "${siblings// }" ]]; then
    adw_log "no SIBLING_REPOS configured — nothing to check"; exit 0
  fi
  sib_fail=0
  for spec in $siblings; do
    path="${spec%%:*}"; mode="${spec#*:}"; [[ "$mode" == "$path" ]] && mode="ask"
    case "$path" in /*) ;; *) path="$(adw_repo_root)/$path" ;; esac
    if [[ ! -d "$path/.git" && ! -f "$path/.git" ]]; then
      adw_warn "SIBLING_REPOS: not a git repo — $path"; continue
    fi
    dirty="$(git -C "$path" status --porcelain 2>/dev/null | head -10)"
    if [[ -n "${dirty// }" ]]; then
      case "$mode" in
        ro) adw_warn "GUARD FAILED: '$path' is read-only for this run, and it has uncommitted changes:" ;;
        *)  adw_warn "GUARD FAILED: '$path' has uncommitted changes. Cross-repo edits need the operator's go first:" ;;
      esac
      printf '%s\n' "$dirty" | sed 's/^/    /' >&2
      sib_fail=1
    else
      adw_log "sibling clean ($mode): $path"
    fi
  done
  (( sib_fail )) && exit 1
  exit 0
fi

test_paths="$(adw_cfg TEST_PATHS tests)"
src_paths="$(adw_cfg SRC_PATHS src)"
violations=""

case "$role" in
  builder)     violations="$(matches "$test_paths")"; forbidden="test paths ($test_paths)" ;;
  test-author) violations="$(matches "$src_paths")";  forbidden="source paths ($src_paths)" ;;
  reviewer)    violations="$files"; forbidden="any file (reviewers are read-only)" ;;
  planner)
    violations="$(printf '%s\n' "$files" | grep -v '^\.tasks/' || true)"
    forbidden="anything outside .tasks/" ;;
  *) adw_die "unknown role: $role" ;;
esac

if [[ -n "${violations// }" ]]; then
  adw_warn "GUARD FAILED for role '$role' — diff touches $forbidden:"
  printf '  %s\n' $violations >&2
  case "$role" in
    builder) adw_warn "If a test is genuinely wrong, STOP and hand it back to the test-author with the reason. Do not edit it." ;;
    test-author) adw_warn "Write the failing test only. Implementation belongs to the builder." ;;
  esac
  exit 1
fi

adw_log "guard OK: role '$role' stayed in scope ($(printf '%s\n' "$files" | sed '/^$/d' | wc -l | tr -d ' ') file(s) changed)"
