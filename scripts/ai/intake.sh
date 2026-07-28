#!/usr/bin/env bash
# scripts/ai/intake.sh — normalize an incoming task from any tracker. Core file.
#
#   intake.sh fetch <ref>                     → normalized JSON on stdout + ticket body on disk
#   intake.sh writeback <ref> --status <s>    → move the ticket (only if INTAKE_WRITEBACK=true)
#   intake.sh writeback <ref> --comment <txt> → post one comment (only if INTAKE_WRITEBACK=true)
#   intake.sh contract                        → print the five fields the core needs
#
# The core knows a CONTRACT, never a tracker. Whatever the project already uses — an in-house CLI, `gh`,
# `jira`, curl against an API — is configured as a command template in .tasks/_STACK.md:
#
#   INTAKE_CMD=<your-cli> issue show <ref> --json
#
# Nothing here infers a tracker. An unset INTAKE_CMD means manual intake, not "look for a CLI you know".
#
# `<ref>` is substituted with the ticket key. If the command emits JSON, this script maps the usual
# field names itself. If it emits something else, it exits 4 and hands the raw output to the agent,
# which normalizes it using the skill named in INTAKE_SKILL. No MCP required, no adapter to write.
#
# Exit codes: 0 normalized · 3 manual intake (agent asks the operator) · 4 raw output needs the agent ·
#             2 misconfiguration/failure.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$here/lib.sh"

root="$(adw_repo_root)" || adw_die "not a git repo"
cd "$root" || adw_die "cannot enter the repository root: $root"

print_contract() {
  cat <<'EOF'
The core needs exactly five fields from any tracker:

  id      stable key → .tasks/<id>/   (required; lowercased, e.g. sm-12, gh-431)
  title   one line                    (required)
  body    description, markdown       (required, may be empty)
  url     backlink for PR + provenance(optional)
  status  the human-facing state      (optional)

Anything else — epics, sprints, points, custom fields — is not the core's business.
EOF
}

# The mapper must receive the tracker output on stdin, so the program itself cannot come from stdin
# (a `python3 - <<EOF` heredoc would eat it and the mapper would silently see an empty document).
read -r -d '' NORMALIZE_PY <<'PY'
import json, sys

raw = sys.stdin.read()
try:
    d = json.loads(raw)
except Exception:
    sys.stderr.write("[adw] intake: output is not JSON\n"); sys.exit(4)

if isinstance(d, list):
    if len(d) != 1:
        sys.stderr.write("[adw] intake: command returned %d items, expected one issue\n" % len(d))
        sys.exit(4)
    d = d[0]
if not isinstance(d, dict):
    sys.stderr.write("[adw] intake: unexpected JSON shape\n"); sys.exit(4)

def pick(*names):
    for n in names:
        if n in d and d[n] not in (None, ""):
            return d[n]
    return None

def flatten(v):
    # trackers nest these: {"state": {"name": "In Progress"}}
    if isinstance(v, dict):
        for k in ("name", "title", "value", "identifier"):
            if k in v:
                return v[k]
        return None
    return v

ident = pick("identifier", "key", "number", "id")
title = pick("title", "name", "summary")
body  = pick("description", "body", "content") or ""
url   = pick("url", "permalink", "html_url", "webUrl")
state = flatten(pick("state", "status", "workflowState", "column"))

missing = [n for n, v in (("id", ident), ("title", title)) if v in (None, "")]
if missing:
    sys.stderr.write("[adw] intake: could not map required field(s): %s\n" % ", ".join(missing))
    sys.exit(4)

print(json.dumps({
    "id": str(ident).lower(),
    "title": str(title),
    "body": str(body),
    "url": url or "",
    "status": state or "",
}, ensure_ascii=False, indent=2))
PY

read -r -d '' TICKET_PY <<'PY'
import json, sys, pathlib
d = json.load(sys.stdin)
pathlib.Path(sys.argv[1]).write_text(
    "# %s — %s\n\n%s\n\n---\nsource: %s\nstatus at intake: %s\n"
    % (d["id"], d["title"], d["body"] or "_(no description)_", d["url"] or "n/a", d["status"] or "n/a")
)
PY

# Tracker CLIs often resolve their target (workspace/team/project) by walking UP from the working
# directory, so the same command run from a worktree can bind to a different project — or to none.
# A misdirected write lands in someone else's backlog and does not fail. Pin the directory.
intake_cwd() {
  local dir; dir="$(adw_cfg INTAKE_CWD)"
  [[ -n "${dir// }" ]] || { printf '%s' "$(adw_repo_root)"; return 0; }
  case "$dir" in
    /*) ;;                                   # absolute: use as given
    *)  dir="$(adw_repo_root)/$dir" ;;       # relative: from the repo root, not the caller's cwd
  esac
  if [[ ! -d "$dir" ]]; then
    adw_warn "INTAKE_CWD points at a missing directory: $dir — falling back to the repo root"
    printf '%s' "$(adw_repo_root)"; return 0
  fi
  printf '%s' "$dir"
}

normalize_json() { python3 -c "$NORMALIZE_PY"; }  # stdin: raw output → stdout: contract JSON, or exit 4

# Workflow states differ per team and per tracker: "In Progress", "Doing", "Начали". The core knows
# INTENTS (start / review / done) and resolves them from the tracker's own state list, so nobody has to
# hardcode a name that is only true in one workspace.
read -r -d '' STATES_PY <<'PY'
import json, re, sys

intent = sys.argv[1]
team_hint = (sys.argv[2] if len(sys.argv) > 2 else "").upper()

try:
    doc = json.loads(sys.stdin.read())
except Exception:
    sys.stderr.write("[adw] states: output is not JSON\n"); sys.exit(4)

states = []
def walk(node):
    if isinstance(node, dict):
        if "name" in node and "type" in node and isinstance(node.get("name"), str):
            states.append(node)
        for v in node.values():
            walk(v)
    elif isinstance(node, list):
        for v in node:
            walk(v)
walk(doc)

if not states:
    sys.stderr.write("[adw] states: no objects with name+type found\n"); sys.exit(4)

def team_key(s):
    t = s.get("team")
    if isinstance(t, dict):
        return str(t.get("key") or t.get("name") or "").upper()
    return ""

# A workspace-wide listing returns every team's states; keep only the ticket's team when we can tell.
if team_hint and any(team_key(s) for s in states):
    scoped = [s for s in states if team_key(s) == team_hint]
    if scoped:
        states = scoped

def pos(s):
    try:
        return float(s.get("position", 1e9))
    except (TypeError, ValueError):
        return 1e9

def by_type(*types):
    return sorted([s for s in states if str(s.get("type", "")).lower() in types], key=pos)

if intent == "start":
    # earliest in-progress state; a review column sits later in the workflow
    pool = [s for s in by_type("started") if not re.search(r"review|test|qa", s["name"], re.I)]
    pool = pool or by_type("started")
elif intent == "review":
    pool = [s for s in by_type("started") if re.search(r"review", s["name"], re.I)]
    pool = pool or by_type("started")[1:] or by_type("started")
elif intent == "done":
    pool = by_type("completed")
else:
    sys.stderr.write("[adw] states: unknown intent %r (start|review|done)\n" % intent); sys.exit(2)

if not pool:
    sys.stderr.write("[adw] states: no state matches intent %r. Available: %s\n"
                     % (intent, ", ".join("%s (%s)" % (s["name"], s.get("type")) for s in states)))
    sys.exit(1)

print(pool[0]["name"])
PY

# resolve_state <intent> [ref] — intent → the tracker's own state name. Echoes the intent back
# unchanged when no INTAKE_STATES_CMD is configured, so a literal name still works.
resolve_state() {
  local intent="$1" ref="${2:-}" cmd out name
  cmd="$(adw_cfg INTAKE_STATES_CMD)"
  if [[ -z "${cmd// }" ]]; then printf '%s' "$intent"; return 0; fi
  out="$(bash -c "${cmd//<ref>/$ref}" 2>/dev/null)" || out=""
  if [[ -z "${out// }" ]]; then
    adw_warn "INTAKE_STATES_CMD produced nothing — using '$intent' literally"
    printf '%s' "$intent"; return 0
  fi
  # Team hint from the ticket key (SMBH-267 → SMBH) so a workspace-wide listing narrows correctly.
  local hint="${ref%%-*}"
  if name="$(printf '%s' "$out" | python3 -c "$STATES_PY" "$intent" "$hint" 2>/dev/null)"; then
    printf '%s' "$name"
  else
    adw_warn "could not resolve intent '$intent' from the tracker's states — using it literally"
    printf '%s' "$intent"
  fi
}

fetch() {
  local ref="${1:-}"
  [[ -n "$ref" ]] || adw_die "usage: intake.sh fetch <ref>"

  local mode cmd skill
  mode="$(adw_cfg INTAKE manual)"
  cmd="$(adw_cfg INTAKE_CMD)"
  skill="$(adw_cfg INTAKE_SKILL)"

  if [[ "$mode" == "manual" || -z "${cmd// }" ]]; then
    adw_log "INTAKE=$mode with no INTAKE_CMD → manual intake."
    print_contract >&2
    adw_log "Ask the operator for the ticket text and normalize it yourself. Quote their wording verbatim."
    exit 3
  fi

  local resolved="${cmd//<ref>/$ref}" cwd
  cwd="$(intake_cwd)"
  adw_log "intake: $resolved${cwd:+  (cwd: $cwd)}"
  local out rc
  out="$( cd "${cwd:-.}" && bash -c "$resolved" 2>&1 )"; rc=$?
  if (( rc != 0 )) || [[ -z "${out// }" ]]; then
    adw_warn "intake command failed (exit $rc):"
    printf '%s\n' "$out" | head -20 >&2
    adw_warn "Fix INTAKE_CMD in .tasks/_STACK.md, or fall back to manual intake — do not invent the ticket."
    exit 2
  fi

  local normalized
  if normalized="$(printf '%s' "$out" | normalize_json 2>/dev/null)"; then
    local id; id="$(printf '%s' "$normalized" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
    mkdir -p ".tasks/$id/extra_context"
    printf '%s' "$normalized" | python3 -c "$TICKET_PY" ".tasks/$id/extra_context/ticket.md"
    adw_log "ticket body → .tasks/$id/extra_context/ticket.md (do NOT copy it into PLAN.md — link it)"
    printf '%s\n' "$normalized"
    return 0
  fi

  adw_warn "could not map the output to the contract automatically."
  [[ -n "${skill// }" ]] && adw_warn "load the '$skill' skill and normalize the raw output below yourself."
  print_contract >&2
  printf '%s\n' "$out"
  exit 4
}

writeback() {
  local ref="${1:-}"; shift || true
  [[ -n "$ref" ]] || adw_die "usage: intake.sh writeback <ref> --status <s> | --comment <text>"
  [[ "$(adw_cfg INTAKE_WRITEBACK false)" == "true" ]] || {
    adw_log "INTAKE_WRITEBACK is not true → skipping tracker write (read-only intake)."; return 0; }

  local kind="" value=""
  case "${1:-}" in
    --status)  kind=status;  value="${2:-}" ;;
    --comment) kind=comment; value="${2:-}" ;;
    *) adw_die "expected --status or --comment" ;;
  esac
  [[ -n "$value" ]] || adw_die "empty $kind"

  # A status may be given as an INTENT (start / review / done) — resolved against the tracker's own
  # workflow states — or as a literal name. Intents keep the loop portable across teams and trackers.
  if [[ "$kind" == status ]]; then
    case "$value" in
      start|review|done)
        local resolved_name; resolved_name="$(resolve_state "$value" "$ref")"
        [[ "$resolved_name" != "$value" ]] && adw_log "intent '$value' → state '$resolved_name'"
        value="$resolved_name" ;;
    esac
  fi

  local tmpl
  case "$kind" in
    status)  tmpl="$(adw_cfg INTAKE_STATUS_CMD)" ;;
    comment) tmpl="$(adw_cfg INTAKE_COMMENT_CMD)" ;;
  esac
  [[ -n "${tmpl// }" ]] || { adw_warn "no INTAKE_$(upper "$kind")_CMD configured → skipping"; return 0; }

  local resolved="${tmpl//<ref>/$ref}" cwd
  resolved="${resolved//<value>/$value}"
  cwd="$(intake_cwd)"
  adw_log "writeback ($kind): $resolved${cwd:+  (cwd: $cwd)}"
  ( cd "${cwd:-.}" && bash -c "$resolved" ) || adw_warn "writeback failed — the run continues; the tracker is not the source of truth for engineering state."
}

states() { # show how intents resolve against this tracker — diagnostic, writes nothing
  local ref="${1:-}"
  [[ -n "$(adw_cfg INTAKE_STATES_CMD)" ]] || adw_die "no INTAKE_STATES_CMD in .tasks/_STACK.md"
  local intent
  for intent in start review 'done'; do   # quoted: bare `done` reads as the loop keyword
    printf '  %-8s → %s\n' "$intent" "$(resolve_state "$intent" "$ref")"
  done
}

case "${1:-}" in
  fetch)     shift; fetch "$@" ;;
  writeback) shift; writeback "$@" ;;
  states)    shift; states "$@" ;;
  contract)  print_contract ;;
  *) adw_die "usage: intake.sh fetch <ref> | writeback <ref> --status|--comment <v> | states [ref] | contract" ;;
esac
