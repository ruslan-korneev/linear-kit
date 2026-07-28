#!/usr/bin/env bash
# scripts/ai/setup-worktree.sh — make a fresh git worktree buildable, then allocate its resources.
# Core file: what to link/copy comes from DEP_DIRS / LOCAL_ONLY_FILES in .tasks/_STACK.md.
#
# A linked worktree shares .git with the primary checkout but starts with an empty working tree for heavy
# gitignored dep dirs. Reinstalling them per worktree is slow and can desync mid-flight, so they are
# symlinked from the primary checkout, local-only config is copied, and both are git-excluded.
#
# Run from inside the worktree:  bash scripts/ai/setup-worktree.sh
# Idempotent: re-running only fills in what is missing.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$here/lib.sh"

root="$(adw_repo_root)" || adw_die "not a git repo"
cd "$root" || adw_die "cannot enter the repository root: $root"

common_git="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" \
  || adw_die "cannot resolve git common dir"
main_root="$(dirname "$common_git")"

if [[ "$main_root" == "$root" ]]; then
  adw_log "this IS the primary checkout — nothing to link; install dependencies here directly."
  bash "$here/worktree-alloc.sh" >/dev/null 2>&1 || true
  exit 0
fi

adw_log "worktree: $root"
adw_log "primary:  $main_root"

dep_dirs="${DEP_DIRS:-$(adw_cfg DEP_DIRS)}"
local_files="${LOCAL_ONLY_FILES:-$(adw_cfg LOCAL_ONLY_FILES)}"
excluded=()

for dir in $dep_dirs; do
  [[ -e "$root/$dir" || -L "$root/$dir" ]] && continue
  if [[ -d "$main_root/$dir" ]]; then
    ln -s "$main_root/$dir" "$root/$dir"
    excluded+=("$dir")
    adw_log "linked $dir -> $main_root/$dir"
  fi
done

for file in $local_files; do
  [[ -e "$root/$file" ]] && continue
  if [[ -f "$main_root/$file" ]]; then
    cp "$main_root/$file" "$root/$file"
    excluded+=("$file")
    adw_log "copied $file"
  fi
done

if (( ${#excluded[@]} )); then
  excl="$common_git/worktrees/$(basename "$root")/info/exclude"
  [[ -d "$(dirname "$excl")" ]] || excl="$common_git/info/exclude"
  mkdir -p "$(dirname "$excl")"
  for entry in ${excluded[@]+"${excluded[@]}"}; do
    grep -qxF "$entry" "$excl" 2>/dev/null || printf '%s\n' "$entry" >> "$excl"
  done
  adw_log "updated git exclude: $excl"
fi

for dir in $dep_dirs; do
  [[ -L "$root/$dir" ]] && adw_warn "$dir is a symlink to the primary — do NOT run a package install here (it writes through the link). Reinstall in the primary checkout."
done

bash "$here/worktree-alloc.sh" >/dev/null

# Generated artifacts (bindings, codegen, protobufs) must be REGENERATED, never copied: a stale copy is
# a silently wrong build rather than an error. The same command is what makes a fresh clone buildable.
bootstrap="$(adw_cfg BOOTSTRAP_CMD)"
if [[ -n "${bootstrap// }" ]]; then
  adw_log "bootstrap: $bootstrap"
  if ! bash -c "$bootstrap"; then
    adw_warn "BOOTSTRAP_CMD failed — this worktree is not buildable yet. Fix it before running any gate."
    exit 1
  fi
else
  adw_log "no BOOTSTRAP_CMD configured. If this project has generated artifacts (bindings, codegen), set it"
  adw_log "  — copying them via LOCAL_ONLY_FILES ships a stale artifact, which fails silently, not loudly."
fi

adw_log "done. Next: source .tasks/_worktree.env, then 'bash scripts/ai/gate.sh static' to confirm."
