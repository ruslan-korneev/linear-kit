#!/usr/bin/env bash
# scripts/ai/lib.sh — shared helpers for the ADW gate scripts. Sourced, not run.
# Core file: identical in every project. All project-specific values come from .tasks/_STACK.md.

adw_repo_root() { git rev-parse --show-toplevel 2>/dev/null; }

# adw_cfg <KEY> [default] — read KEY from any ```ini block in .tasks/_STACK.md.
# A trailing " # reason" is a note, not part of the command: an empty value with a stated reason
# ("# none: no linter in this toolchain") is a decision; an empty value with no reason is an omission,
# and the two must not look alike in a report.
adw_cfg() {
  local key="$1" default="${2:-}" root value
  root="$(adw_repo_root)" || { printf '%s' "$default"; return 0; }
  [[ -f "$root/.tasks/_STACK.md" ]] || { printf '%s' "$default"; return 0; }
  value="$(sed -n '/^```ini/,/^```/p' "$root/.tasks/_STACK.md" \
    | grep -m1 -E "^${key}=" | sed -E "s/^${key}=//" | sed -E 's/[[:space:]]+#[[:space:]].*$//' \
    | sed -E 's/[[:space:]]+$//')"
  [[ -n "$value" ]] || value="$default"
  printf '%s' "$value"
}

# adw_cfg_note <KEY> — the "# …" note attached to a key, if any. Empty when there is none.
adw_cfg_note() {
  local key="$1" root
  root="$(adw_repo_root)" || return 0
  [[ -f "$root/.tasks/_STACK.md" ]] || return 0
  sed -n '/^```ini/,/^```/p' "$root/.tasks/_STACK.md" \
    | grep -m1 -E "^${key}=" | grep -oE '#[[:space:]].*$' | sed -E 's/^#[[:space:]]*//'
}

# Case folding, portably. `${x,,}` and `${x^^}` need bash 4, and bash 3.2 does not merely ignore them:
# it aborts the script with "bad substitution", so a gate using one returns no verdict at all on the
# /bin/bash macOS ships. Everything here has to run on that shell.
lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }
upper() { printf '%s' "$1" | tr '[:lower:]' '[:upper:]'; }

adw_log()  { printf '[adw] %s\n' "$*" >&2; }
adw_warn() { printf '[adw] WARN: %s\n' "$*" >&2; }
adw_die()  { printf '[adw] ERROR: %s\n' "$*" >&2; exit 2; }

# A check that never ran is not a check that passed. Reporting both as 0 makes a project with nothing
# configured indistinguishable from one where everything ran clean — which is the same failure the
# engine probe exists to prevent ("installed does not mean usable"), one layer down.
ADW_SKIPPED=3

# adw_run_cmd <label> <command-string> [config-key] — run a configured command.
# Exit: 0 ran and passed · the command's own code if it ran and failed · 3 never ran.
# The config key, when given, is only used to quote the reason the operator wrote for leaving it empty.
adw_run_cmd() {
  local label="$1" cmd="$2" key="${3:-}" note=""
  if [[ -z "${cmd// }" ]]; then
    [[ -n "$key" ]] && note="$(adw_cfg_note "$key")"
    if [[ -n "${note// }" ]]; then
      adw_log "$label: SKIPPED — declared none in .tasks/_STACK.md ($note)"
    else
      adw_log "$label: SKIPPED (${key:-it} is not configured in .tasks/_STACK.md)"
    fi
    return $ADW_SKIPPED
  fi
  adw_log "$label: $cmd"
  bash -c "$cmd"
}
