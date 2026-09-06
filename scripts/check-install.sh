#!/usr/bin/env bash
# model-guard SessionStart hook — the closest a plugin can get to "install and go".
# Claude Code plugins cannot register a main statusLine themselves, so until
# /model-guard:setup has been run this prints a one-line hint at session start.
# Once it is registered, the statusLine points at a copy of the plugin's script:
# when a plugin update ships a newer one, this refreshes that copy in place and
# says so, so an update needs no second command. Silent otherwise.
# Silence forever:  echo 'SETUP_HINT=off' >> ~/.claude/model-guard.conf
set -u
command -v jq >/dev/null 2>&1 || exit 0
CONF="$HOME/.claude/model-guard.conf"
grep -qs '^SETUP_HINT=off' "$CONF" 2>/dev/null && exit 0

plugin_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="$plugin_root/scripts/statusline.sh"
inst="$HOME/.claude/model-guard.sh"
cmd=$(jq -r '.statusLine.command // empty' "$HOME/.claude/settings.json" 2>/dev/null || true)

msg=""
if [[ "$cmd" != *model-guard* ]]; then
  msg="model-guard: statusline not set up yet — run /model-guard:setup (interactive, ~30 s). Silence this hint: echo 'SETUP_HINT=off' >> ~/.claude/model-guard.conf"
elif [ -f "$inst" ] && [ -f "$src" ]; then
  v_inst=$(sed -n 's/^MG_VERSION="\(.*\)"$/\1/p' "$inst" | head -n1)
  v_src=$(sed -n 's/^MG_VERSION="\(.*\)"$/\1/p' "$src" | head -n1)
  if [ -n "$v_src" ] && [ "$v_inst" != "$v_src" ]; then
    if cp "$src" "$inst.mg-new" 2>/dev/null && chmod +x "$inst.mg-new" 2>/dev/null \
       && mv "$inst.mg-new" "$inst" 2>/dev/null; then
      msg="model-guard: statusline refreshed to ${v_src} (was ${v_inst:-unknown}). Settings and config untouched."
    else
      rm -f "$inst.mg-new" 2>/dev/null
      msg="model-guard: plugin updated (installed ${v_inst:-?} → ${v_src}) but the statusline script could not be refreshed — run /model-guard:setup."
    fi
  fi
fi

[ -n "$msg" ] && printf '{"systemMessage": %s}\n' "$(printf '%s' "$msg" | jq -Rs .)"
exit 0
