---
name: setup
description: Interactive setup for model-guard — asks three quick preference questions (band language, account display, auto-recovery), installs the statusline scripts, registers the statusLine in ~/.claude/settings.json (with a timestamped backup) and checks the keystroke channel the recovery hooks need. Safe to re-run anytime to change options or to refresh after a plugin update.
argument-hint: "(no arguments)"
---

# model-guard: interactive setup

You are installing (or reconfiguring) model-guard for this user: the statusline
scripts and the auto-recovery hooks' configuration.

Plugin root: `${CLAUDE_PLUGIN_ROOT}`
(If the path above looks like an unexpanded shell variable instead of a real
directory, locate the plugin root via `claude plugin list --json` or by finding
`*/model-guard/scripts/statusline.sh` under `~/.claude/plugins/`.)

Target paths — use exactly these:
- scripts:  `~/.claude/model-guard/` (`statusline.sh`, `lib.sh`, `text.sh`)
- config:   `~/.claude/model-guard.conf`
- register: the `statusLine` key in `~/.claude/settings.json`

Follow the steps in order. Keep your final report short.

## 1. Preflight (one Bash call)

- `command -v jq` — **required**. If missing, stop and tell the user how to install
  it (`sudo apt install jq` / `brew install jq` / `sudo pacman -S jq`), then exit.
- Read `~/.claude/settings.json`: note the current `statusLine` (if any) and the
  `model` field (used for auto-detecting the expected model — no question needed).
- Read `~/.claude/model-guard.conf` if it exists (this run is then a reconfigure —
  mention the current values inside the question descriptions below).
- Keystroke channel for auto-recovery, from this session's environment, first hit wins:
  `TMUX` + `TMUX_PANE` set → tmux; `ZELLIJ_SESSION_NAME` + a numeric `ZELLIJ_PANE_ID` set
  → zellij; `KITTY_WINDOW_ID` set and `KITTY_LISTEN_ON` set → kitty; `KITTY_WINDOW_ID` set
  but `KITTY_LISTEN_ON` empty → kitty without remote control (fixable, see step 3b);
  otherwise none.

## 2. Ask preferences (ONE AskUserQuestion call)

Question 1 — header "Language", band text language:
- "Auto (Recommended)" — follow Claude Code's `language` setting, fall back to English
- "English"
- "中文"
- "More…" — description: also available: 日本語 · 한국어 · Español · Français · Deutsch · Português; type one via Other (conf values: ja / ko / es / fr / de / pt)

Question 2 — header "Account", show the logged-in account email on the band
(useful when juggling multiple accounts):
- "Show (Recommended)"
- "Hide"

Question 3 — header "Recovery", what to do when a safeguard flag downgrades the
session automatically (Fable/Opus 5 → Opus 4.8):
- "Stop, switch to Opus 5 (1M) at max effort, continue (Recommended)" — conf:
  `RECOVER_MODEL=claude-opus-5[1m]`, `RECOVER_EFFORT=max`
- "Stop, switch to another model…" — description: type the model id (and
  optionally an effort level) via Other, e.g. `claude-opus-5 high`
- "Stop only" — conf: `RECOVER_CHANNEL=none` (the turn stops once; the band tells which /model to run)
- "Off" — conf: `RECOVER=off` (no hooks act; statusline only)

If `settings.json` already has a `statusLine` that is **not** model-guard, add
Question 4 — header "Existing bar": "Replace (keep restorable backup)" /
"Cancel setup". If the user cancels, stop cleanly.

## 3. Install files

- `mkdir -p ~/.claude/model-guard`, then copy `${CLAUDE_PLUGIN_ROOT}/scripts/statusline.sh`,
  `${CLAUDE_PLUGIN_ROOT}/scripts/lib.sh` and `${CLAUDE_PLUGIN_ROOT}/scripts/text.sh` into it and
  `chmod +x` them. The statusline sources its two neighbours, so all three must be present.
- If a flat `~/.claude/model-guard.sh` from an earlier install exists, delete it: the
  `statusLine` registered in step 4 points at the directory.
- Write `~/.claude/model-guard.conf` with the answers, **preserving** any
  unrelated existing keys (`SETUP_HINT`, `PREV_STATUSLINE_B64`, `EXPECTED_MODEL`,
  `SHOW_CONTEXT`, `SHOW_LIMIT`, `LIMIT_WARN_AT`):

```
LANGUAGE=auto                    # or en / zh / ja / ko / es / fr / de / pt
SHOW_ACCOUNT=true                # or false
RECOVER_MODEL=claude-opus-5[1m]  # from Question 3; omit the RECOVER_* keys entirely for the defaults
RECOVER_EFFORT=max
```

Do NOT write `EXPECTED_MODEL` unless the user explicitly asked for a manual
override — auto-detection from the settings.json `model` field is the default.

### 3b. Keystroke channel (only when recovery is on)

- tmux, zellij, or kitty with `KITTY_LISTEN_ON`: nothing to do, say which channel was found.
- kitty without remote control: ask (ONE AskUserQuestion, header "kitty") whether to
  append these two lines to `~/.config/kitty/kitty.conf` (backup first:
  `cp ~/.config/kitty/kitty.conf ~/.config/kitty/kitty.conf.bak-model-guard-$(date +%Y%m%d-%H%M%S)`):

  ```
  allow_remote_control socket-only
  listen_on unix:@kitty
  ```

  Tell the user kitty must be restarted for this to take effect (open sessions can be
  resumed with `claude --resume`). `socket-only` keeps the tty channel closed; only
  local processes reaching the socket can control kitty.
- No channel at all (a plain terminal, or SSH without a multiplexer): say so in one
  line — a downgrade stops the turn once and the band names the `/model` to run;
  running the session inside tmux or zellij enables the automatic switch.

## 4. Register the statusLine

- Backup first:
  `cp ~/.claude/settings.json ~/.claude/settings.json.bak-model-guard-$(date +%Y%m%d-%H%M%S)`
- If replacing a foreign statusLine, save it for restore-on-uninstall:
  `printf 'PREV_STATUSLINE_B64=%s\n' "$(jq -c .statusLine ~/.claude/settings.json | base64 -w0)" >> ~/.claude/model-guard.conf`
- Merge without touching other keys:

```bash
jq '.statusLine={"type":"command","command":"'"$HOME"'/.claude/model-guard/statusline.sh","padding":0,"refreshInterval":5}' \
  ~/.claude/settings.json > ~/.claude/settings.json.tmp && mv ~/.claude/settings.json.tmp ~/.claude/settings.json
```

- Validate: `jq -e .statusLine ~/.claude/settings.json` must succeed.

## 5. Verify — show the user real output

Run both and let the raw ANSI output render in the terminal (band colors included):

1. Normal state — use the user's actual pinned model id so it renders green:
   `echo '{"model":{"id":"<pinned-model-id>","display_name":"<name>"},"effort":{"level":"xhigh"},"thinking":{"enabled":true},"context_window":{"used_percentage":12}}' | ~/.claude/model-guard/statusline.sh`
2. Downgrade drill — must render the full red alarm band:
   `echo '{"model":{"id":"claude-haiku-4-5","display_name":"Haiku 4.5"}}' | ~/.claude/model-guard/statusline.sh`

If the drill does not come out as an alarm (e.g. the user's `model` is `default`,
so there is no expectation), explain that and point at `EXPECTED_MODEL` in the conf.

3. Only if the user asks for proof of the hooks: `bash "${CLAUDE_PLUGIN_ROOT}/tests/run.sh"`
   (about 20 s, isolated temp state, no keystrokes are sent).

## 6. Report (short)

- The statusline hot-reloads: the band should appear at the bottom within seconds
  (worst case: next session).
- The recovery hooks are plugin hooks: they load when a session starts, so sessions
  that were already open before the install/update do not have them until restarted.
- Keep the marketplace on auto-update (`/plugin` → Manage marketplaces → Enable
  auto-update, or `"autoUpdate": true` on the `extraKnownMarketplaces` entry) so
  later fixes arrive without a manual update.
- Re-run `/model-guard:setup` anytime to change options. After a plugin update there
  is nothing to re-run: the session-start hook refreshes the installed statusline
  scripts itself.
- `/model-guard:remove` uninstalls cleanly and restores any previous statusline.
- Advanced knobs live in `~/.claude/model-guard.conf`: `LANGUAGE`, `SHOW_ACCOUNT`,
  `SHOW_CONTEXT`, `SHOW_LIMIT` (the account's 5h/7d usage in the band, default true),
  `LIMIT_WARN_AT` (5h rate-limit warning threshold, default 80,
  `off` to disable), `EXPECTED_MODEL` (grep -Ei pattern override), and for recovery
  `RECOVER`, `RECOVER_MODEL`, `RECOVER_EFFORT`, `RECOVER_PROMPT`, `RECOVER_CHANNEL`,
  `RECOVER_MAX`, `DEBUG` (see README).
