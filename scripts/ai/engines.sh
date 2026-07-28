#!/usr/bin/env bash
# scripts/ai/engines.sh — engine availability + reviewer selection with honest degradation. Core file.
#
#   engines.sh candidates      → engine CLIs found on PATH (installed ≠ usable)
#   engines.sh probe [--write] → actually call each candidate; report OK/FAIL; --write records the
#                                verified list into ENGINES= in .tasks/_STACK.md
#   engines.sh list            → engines this project may actually use
#   engines.sh pick-review [n] → n reviewer engines, cycling; prefers engines != IMPLEMENT_ENGINE
#   engines.sh diversity       → FULL (≥2 usable) | DEGRADED (1 usable)
#   engines.sh run <engine>    → run a read-only review pass, prompt on stdin
#
# Being on PATH proves nothing: an installed CLI can be unauthenticated, unpaid, rate-limited, or
# misconfigured. So availability comes from ENGINES= in .tasks/_STACK.md, and `probe` is how that list is
# earned. With no ENGINES= set, this falls back to IMPLEMENT_ENGINE alone — under-claiming beats routing a
# review to a CLI that errors out and silently returns nothing.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$here/lib.sh"

KNOWN_ENGINES="claude codex gemini opencode"

# Model pins tried when a vendor is the only one available. Probed, never assumed.
default_pins() {
  case "$1" in
    claude)   printf 'opus sonnet' ;;
    codex)    printf 'gpt-5.5 gpt-5.5-codex' ;;
    gemini)   printf '' ;;
    opencode) printf '' ;;
  esac
}
PROBE_TIMEOUT="${ADW_PROBE_TIMEOUT:-45}"

candidates() {
  local e
  for e in $KNOWN_ENGINES; do command -v "$e" >/dev/null 2>&1 && printf '%s\n' "$e"; done
}

# Run a command with a portable timeout (macOS has no coreutils `timeout` by default).
with_timeout() {
  local secs="$1"; shift
  ( "$@" ) & local pid=$!
  ( sleep "$secs"; kill -TERM "$pid" 2>/dev/null ) & local watcher=$!
  wait "$pid" 2>/dev/null; local rc=$?
  kill -TERM "$watcher" 2>/dev/null; wait "$watcher" 2>/dev/null
  return $rc
}

engine_bin()   { printf '%s' "${1%%:*}"; }               # "claude:opus" → claude
engine_model() { [[ "$1" == *:* ]] && printf '%s' "${1#*:}"; }  # "claude:opus" → opus

engine_cmd() { # $1 entry (name[:model]) — prompt on stdin
  local bin model; bin="$(engine_bin "$1")"; model="$(engine_model "$1")"
  case "$bin" in
    claude)   if [[ -n "$model" ]]; then claude -p --model "$model" 2>&1; else claude -p 2>&1; fi ;;
    codex)    if [[ -n "$model" ]]; then codex exec --sandbox read-only -c 'approval_policy="never"' -c "model=\"$model\"" - 2>&1
              else codex exec --sandbox read-only -c 'approval_policy="never"' - 2>&1; fi ;;
    gemini)   if [[ -n "$model" ]]; then gemini -m "$model" -p 2>&1; else gemini -p 2>&1; fi ;;
    opencode) if [[ -n "$model" ]]; then opencode run --model "$model" 2>&1; else opencode run 2>&1; fi ;;
    *) return 2 ;;
  esac
}

probe_one() { # $1 entry (name[:model]) → 0 usable, 1 not; prints a one-line reason
  local engine="$1" out fns
  fns="$(declare -f engine_bin engine_model engine_cmd)"
  out="$(printf 'Reply with exactly: ADW_OK' | with_timeout "$PROBE_TIMEOUT" bash -c "$fns; engine_cmd '$engine'" 2>&1)"
  local rc=$?
  if (( rc != 0 )) && [[ -z "${out// }" ]]; then
    printf 'no output (exit %s, likely not authenticated or timed out after %ss)\n' "$rc" "$PROBE_TIMEOUT"; return 1
  fi
  if grep -qi 'ADW_OK' <<< "$out"; then printf 'ok\n'; return 0; fi
  local first; first="$(printf '%s' "$out" | tr -d '\r' | sed '/^$/d' | head -1 | cut -c1-140)"
  printf 'unusable: %s\n' "${first:-empty response}"; return 1
}

probe() {
  local write=0; [[ "${1:-}" == "--write" ]] && write=1
  local usable=() e reason source_list configured
  # Probe what is declared if anything is declared (so `claude:opus,claude:sonnet` gets verified per
  # model); otherwise probe the bare CLIs found on PATH.
  configured="$(adw_cfg ENGINES)"
  if [[ -n "${configured// }" && "$configured" != "auto" ]]; then
    source_list="$(printf '%s\n' "$configured" | tr ',' '\n' | tr -d ' ' | sed '/^$/d')"
  else
    source_list="$(candidates)"
  fi
  adw_log "probing (timeout ${PROBE_TIMEOUT}s each) — installed does not mean usable"
  while IFS= read -r e; do
    [[ -n "$e" ]] || continue
    reason="$(probe_one "$e")" && { printf '  %-18s OK\n' "$e" >&2; usable+=("$e"); } \
                               || printf '  %-18s FAIL — %s\n' "$e" "$reason" >&2
  done <<< "$source_list"

  # One vendor answering is not the end of the story: different models of the same vendor have different
  # blind spots, which is the whole point of a second reviewer. Probe the pins rather than recommending
  # them in prose and writing the degraded value anyway.
  local vendors; vendors="$(printf '%s\n' "${usable[@]:-}" | sed 's/:.*//' | sort -u | sed '/^$/d')"
  if [[ "$(printf '%s\n' "$vendors" | wc -l | tr -d ' ')" == "1" && "${#usable[@]}" == "1" ]]; then
    local vendor="$vendors" pin
    for pin in $(default_pins "$vendor"); do
      reason="$(probe_one "$vendor:$pin")" \
        && { printf '  %-18s OK\n' "$vendor:$pin" >&2; usable+=("$vendor:$pin"); } \
        || printf '  %-18s FAIL — %s\n' "$vendor:$pin" "$reason" >&2
    done
    # keep only the pinned entries when at least two answered: they are strictly more informative
    local pinned=(); local e
    for e in ${usable[@]+"${usable[@]}"}; do [[ "$e" == *:* ]] && pinned+=("$e"); done
    if (( ${#pinned[@]} >= 2 )); then
      usable=(${pinned[@]+"${pinned[@]}"})
      adw_log "single vendor → pinned models probed and recorded (CROSS-MODEL, not DEGRADED)"
    fi
  fi

  if (( ${#usable[@]} == 0 )); then
    adw_warn "no usable engine. Reviews cannot run until at least one CLI is authenticated."
    return 1
  fi
  local list; list="$(IFS=,; printf '%s' "${usable[*]-}")"
  printf '%s\n' "$list"

  if (( write )); then
    local root stack; root="$(adw_repo_root)"; stack="$root/.tasks/_STACK.md"
    [[ -f "$stack" ]] || adw_die "no .tasks/_STACK.md to write into"
    if grep -qE '^ENGINES=' "$stack"; then
      python3 - "$stack" "$list" <<'PY' 2>/dev/null || sed -i.bak -E "s/^ENGINES=.*/ENGINES=$list/" "$stack"
import re, sys
p, val = sys.argv[1], sys.argv[2]
s = open(p).read()
open(p, "w").write(re.sub(r"^ENGINES=.*$", "ENGINES=" + val, s, count=1, flags=re.M))
PY
      rm -f "$stack.bak"
      adw_log "recorded ENGINES=$list in .tasks/_STACK.md"
    else
      adw_warn "no ENGINES= key in .tasks/_STACK.md — add it under ## Engines: ENGINES=$list"
    fi
  fi
}

usable_engines() {
  local configured implement
  configured="$(adw_cfg ENGINES)"
  implement="$(adw_cfg IMPLEMENT_ENGINE claude)"
  if [[ -n "${configured// }" && "$configured" != "auto" ]]; then
    printf '%s\n' "$configured" | tr ',' '\n' | tr -d ' ' | sed '/^$/d'
    return 0
  fi
  # Unset or `auto`: claim only the implementer engine. Run `engines.sh probe --write` to widen it.
  adw_warn "ENGINES not set in .tasks/_STACK.md — assuming only '$implement' is usable. Run: bash scripts/ai/engines.sh probe --write"
  printf '%s\n' "$implement"
}

pick_review() {
  local want="${1:-1}" implement available preferred=() e
  implement="$(adw_cfg IMPLEMENT_ENGINE claude)"
  available="$(usable_engines 2>/dev/null)"
  [[ -n "${available// }" ]] || adw_die "no usable engine configured"
  while IFS= read -r e; do [[ -n "$e" && "$e" != "$implement" ]] && preferred+=("$e"); done <<< "$available"
  while IFS= read -r e; do [[ -n "$e" && "$e" == "$implement" ]] && preferred+=("$e"); done <<< "$available"
  (( ${#preferred[@]} )) || adw_die "no usable review engine"
  local i
  for (( i = 0; i < want; i++ )); do printf '%s\n' "${preferred[$(( i % ${#preferred[@]} ))]}"; done
}

# Honest three-level label. Cross-engine (different vendor) is the strongest independence; cross-model
# (same vendor, different weights) is real but weaker; one entry is no independence at all.
diversity() {
  local entries vendors models
  entries="$(usable_engines 2>/dev/null | sed '/^$/d')"
  [[ -n "${entries// }" ]] || { printf 'DEGRADED\n'; return 0; }
  vendors="$(printf '%s\n' "$entries" | sed 's/:.*//' | sort -u | wc -l | tr -d ' ')"
  models="$(printf '%s\n' "$entries" | sort -u | wc -l | tr -d ' ')"
  if   [[ "$vendors" -ge 2 ]]; then printf 'CROSS-ENGINE\n'
  elif [[ "$models"  -ge 2 ]]; then printf 'CROSS-MODEL\n'
  else printf 'DEGRADED\n'; fi
}

# Fan-out reviewers run as separate CLI processes, so their cost never shows up in the launching
# session's /cost. ADW_USAGE_FILE makes it visible: the engine reports usage, we append one line.
run_engine_json_usage() { # $1 entry, $2 raw json output → appends "entry<TAB>in<TAB>out<TAB>total"
  [[ -n "${ADW_USAGE_FILE:-}" ]] || return 0
  printf '%s' "$2" | python3 -c '
import json, sys, os
entry = sys.argv[1]
try:
    d = json.loads(sys.stdin.read())
except Exception:
    raise SystemExit(0)
u = d.get("usage") or d.get("modelUsage") or {}
if isinstance(u, dict) and not any(k in u for k in ("input_tokens", "output_tokens")):
    for v in u.values():
        if isinstance(v, dict) and ("input_tokens" in v or "output_tokens" in v):
            u = v; break
i = u.get("input_tokens", 0) or 0
o = u.get("output_tokens", 0) or 0
c = (u.get("cache_read_input_tokens", 0) or 0) + (u.get("cache_creation_input_tokens", 0) or 0)
if i or o or c:
    with open(os.environ["ADW_USAGE_FILE"], "a") as f:
        f.write("%s\t%d\t%d\t%d\n" % (entry, i, o, c))
' "$1" 2>/dev/null || true
}

# Extract the assistant text from a JSON envelope; falls back to the raw body when it is not JSON.
run_engine_json_text() {
  python3 -c '
import json, sys
raw = sys.stdin.read()
try:
    d = json.loads(raw)
except Exception:
    print(raw); raise SystemExit(0)
for k in ("result", "text", "content", "response"):
    v = d.get(k)
    if isinstance(v, str) and v.strip():
        print(v); raise SystemExit(0)
print(raw)
' 2>/dev/null
}

run_engine() { # $1 entry (name[:model]); prompt on stdin
  local entry="$1" bin model prompt
  bin="$(engine_bin "$entry")"; model="$(engine_model "$entry")"; prompt="$(cat)"

  # Claude can report usage as JSON; use it when we are asked to account for cost.
  if [[ "$bin" == claude && -n "${ADW_USAGE_FILE:-}" ]]; then
    local raw
    if [[ -n "$model" ]]; then
      raw="$(printf '%s' "$prompt" | claude -p --model "$model" --output-format json 2>/dev/null)"
    else
      raw="$(printf '%s' "$prompt" | claude -p --output-format json 2>/dev/null)"
    fi
    if [[ -n "${raw// }" ]]; then
      run_engine_json_usage "$entry" "$raw"
      printf '%s' "$raw" | run_engine_json_text
      return 0
    fi
    adw_warn "json output unavailable for $entry — falling back to plain text (cost not recorded)"
  fi

  case "$bin" in
    codex)
      if [[ -n "$model" ]]; then
        printf '%s' "$prompt" | codex exec --sandbox read-only -c 'approval_policy="never"' \
          -c "model=\"$model\"" -c 'model_reasoning_effort="high"' - 2>/dev/null
      else
        printf '%s' "$prompt" | codex exec --sandbox read-only -c 'approval_policy="never"' \
          -c 'model_reasoning_effort="high"' - 2>/dev/null
      fi ;;
    claude)
      if [[ -n "$model" ]]; then printf '%s' "$prompt" | claude -p --model "$model" 2>/dev/null
      else printf '%s' "$prompt" | claude -p 2>/dev/null; fi ;;
    gemini)
      if [[ -n "$model" ]]; then printf '%s' "$prompt" | gemini -m "$model" -p 2>/dev/null
      else printf '%s' "$prompt" | gemini -p 2>/dev/null; fi ;;
    opencode)
      if [[ -n "$model" ]]; then printf '%s' "$prompt" | opencode run --model "$model" 2>/dev/null
      else printf '%s' "$prompt" | opencode run 2>/dev/null; fi ;;
    *) adw_die "unknown engine: $entry" ;;
  esac
}

case "${1:-list}" in
  candidates)  candidates ;;
  probe)       shift; probe "${1:-}" ;;
  list)        usable_engines ;;
  pick-review) shift; pick_review "${1:-1}" ;;
  diversity)   diversity ;;
  run)         shift; run_engine "${1:?engine required}" ;;
  *) adw_die "usage: engines.sh candidates|probe [--write]|list|pick-review [n]|diversity|run <engine>" ;;
esac
