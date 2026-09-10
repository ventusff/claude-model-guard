#!/usr/bin/env bash
# model-guard SessionStart hook — the closest a plugin can get to "install and go".
# Claude Code plugins cannot register a main statusLine themselves, so until
# /model-guard:setup has been run this prints a one-line hint at session start.
# Once it is registered, the statusLine runs an installed copy of the plugin's
# scripts (~/.claude/model-guard/): when a plugin update ships a newer one,
# this refreshes that copy in place and says so, so an update needs no second
# command. Silent otherwise.
#
# Installs made before the directory layout copied the script to
# ~/.claude/model-guard.sh; that path keeps working as a one-line hand-off to
# the installed directory, for settings.json and for wrappers that exec it.
# Silence forever:  echo 'SETUP_HINT=off' >> ~/.claude/model-guard.conf
set -u
command -v jq >/dev/null 2>&1 || exit 0
plugin_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib.sh
. "$plugin_root/scripts/lib.sh"
[ "$(mg_conf_get SETUP_HINT)" != off ] || exit 0

MG_INSTALL_DIR="${MODEL_GUARD_INSTALL_DIR:-$HOME/.claude/model-guard}"
legacy="$HOME/.claude/model-guard.sh"
cmd=$(jq -r '.statusLine.command // empty' "$MG_SETTINGS" 2>/dev/null || true)

# The version of a complete installed set; empty when any of the three files is missing.
installed_version() {
  local f
  for f in statusline.sh lib.sh text.sh; do [ -f "$MG_INSTALL_DIR/$f" ] || return 0; done
  sed -n 's/^MG_VERSION="\(.*\)"$/\1/p' "$MG_INSTALL_DIR/lib.sh" 2>/dev/null | head -n1
}

# Copies text.sh, statusline.sh and lib.sh into place. Every file is staged first
# and lib.sh, which carries the version marker, lands last: an interrupted
# refresh leaves the old version visible, so the next session start retries.
# One refresh at a time per install dir.
mg_install_scripts() {
  local f
  mkdir -p "$MG_INSTALL_DIR" || return 1
  (
    flock -w 5 9 || exit 1
    for f in text.sh statusline.sh lib.sh; do
      cp "$plugin_root/scripts/$f" "$MG_INSTALL_DIR/$f.mg-new" && chmod +x "$MG_INSTALL_DIR/$f.mg-new" || exit 1
    done
    for f in text.sh statusline.sh lib.sh; do
      mv "$MG_INSTALL_DIR/$f.mg-new" "$MG_INSTALL_DIR/$f" || exit 1
    done
  ) 9>"$MG_INSTALL_DIR/.refresh.lock"
  local rc=$?
  rm -f "$MG_INSTALL_DIR"/*.mg-new
  return "$rc"
}

# Rewrites the flat legacy path as a hand-off to the installed statusline.
mg_handoff_line() { printf 'exec %q "$@"\n' "$MG_INSTALL_DIR/statusline.sh"; }
mg_write_handoff() {
  local staged="$legacy.mg-new"
  if ! { printf '#!/usr/bin/env bash\n# model-guard: installed under %s (run /model-guard:setup to re-register).\n%s' "$MG_INSTALL_DIR" "$(mg_handoff_line)" > "$staged" \
         && chmod +x "$staged" && mv "$staged" "$legacy"; }; then
    rm -f "$staged"
  fi
}

msg=""
if [[ "$cmd" != *model-guard* ]]; then
  msg="model-guard: statusline not set up yet — run /model-guard:setup (interactive, ~30 s). Silence this hint: echo 'SETUP_HINT=off' >> ~/.claude/model-guard.conf"
else
  v_inst=$(installed_version)
  if [ "$v_inst" != "$MG_VERSION" ]; then
    if mg_install_scripts; then
      msg="model-guard: statusline refreshed to ${MG_VERSION} (was ${v_inst:-unknown}). Settings and config untouched."
    else
      msg="model-guard: plugin updated (installed ${v_inst:-?} → ${MG_VERSION}) but the statusline scripts could not be refreshed — run /model-guard:setup."
    fi
  fi
  # A flat copy left by an earlier install becomes a hand-off to the directory,
  # whether settings.json names it directly or a wrapper of the user's execs it,
  # so nothing needs to change on a plugin update. Only a complete install is
  # handed to, and only a model-guard copy is rewritten, never a user's script.
  if grep -qs '^MG_VERSION=' "$legacy" && [ "$(installed_version)" = "$MG_VERSION" ]; then
    mg_write_handoff
  fi
fi

[ -n "$msg" ] && printf '{"systemMessage": %s}\n' "$(printf '%s' "$msg" | jq -Rs .)"
exit 0
