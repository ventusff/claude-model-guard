---
name: remove
description: Cleanly uninstall the model-guard statusline — unregisters statusLine from ~/.claude/settings.json (restoring any previously saved statusline), and optionally deletes the installed script and config.
argument-hint: "(no arguments)"
---

# model-guard: uninstall

You are removing the model-guard statusline for this user. Keep the final report short.

## 1. Inspect (one Bash call)

- Read `~/.claude/settings.json` → `.statusLine.command`.
- Read `~/.claude/model-guard.conf` if present → note `PREV_STATUSLINE_B64`.
- If the current statusLine is NOT model-guard (command doesn't contain
  `model-guard`), say so — only offer file cleanup (step 3b), don't touch settings.

## 2. Ask (ONE AskUserQuestion call)

Header "Cleanup": "Unregister + delete files (Recommended)" / "Unregister only
(keep script & config)".

## 3. Execute

Backup first:
`cp ~/.claude/settings.json ~/.claude/settings.json.bak-model-guard-$(date +%Y%m%d-%H%M%S)`

a) Unregister — restore the pre-model-guard statusline if one was saved:
- If the conf has `PREV_STATUSLINE_B64`:
  ```bash
  jq --argjson sl "$(sed -n 's/^PREV_STATUSLINE_B64=//p' ~/.claude/model-guard.conf | base64 -d)" \
    '.statusLine=$sl' ~/.claude/settings.json > ~/.claude/settings.json.tmp \
    && mv ~/.claude/settings.json.tmp ~/.claude/settings.json
  ```
- Otherwise: `jq 'del(.statusLine)' ...` (same tmp+mv pattern).
- Validate the result parses: `jq . ~/.claude/settings.json >/dev/null`.

b) If deleting files: `rm -f ~/.claude/model-guard.sh ~/.claude/model-guard.conf`
   and the per-session recovery state: `rm -rf "${XDG_RUNTIME_DIR:-/tmp}/model-guard"`.
   If `~/.config/kitty/kitty.conf` carries the two remote-control lines that
   `setup` added (`allow_remote_control socket-only`, `listen_on unix:@kitty`),
   mention them — they are harmless, the user decides whether to keep them.

## 4. Report (short)

- StatusLine unregistered (and previous statusline restored, if there was one);
  a timestamped settings backup was kept.
- The plugin itself can be uninstalled with `/plugin` → Manage plugins, or
  `claude plugin uninstall model-guard@claude-model-guard`.
