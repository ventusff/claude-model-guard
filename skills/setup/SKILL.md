---
name: setup
description: Interactive setup for the model-guard statusline — asks two quick preference questions, copies the script, and registers the statusLine in ~/.claude/settings.json (with a timestamped backup). Safe to re-run anytime to change options or to refresh after a plugin update.
argument-hint: "(no arguments)"
---

# model-guard: interactive setup

You are installing (or reconfiguring) the model-guard statusline for this user.

Plugin root: `${CLAUDE_PLUGIN_ROOT}`
(If the path above looks like an unexpanded shell variable instead of a real
directory, locate the plugin root via `claude plugin list --json` or by finding
`*/model-guard/scripts/statusline.sh` under `~/.claude/plugins/`.)

Target paths — use exactly these:
- script:   `~/.claude/model-guard.sh`
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

If `settings.json` already has a `statusLine` that is **not** model-guard, add
Question 3 — header "Existing bar": "Replace (keep restorable backup)" /
"Cancel setup". If the user cancels, stop cleanly.

## 3. Install files

- Copy `${CLAUDE_PLUGIN_ROOT}/scripts/statusline.sh` → `~/.claude/model-guard.sh`, `chmod +x` it.
- Write `~/.claude/model-guard.conf` with the two answers, **preserving** any
  unrelated existing keys (`SETUP_HINT`, `PREV_STATUSLINE_B64`, `EXPECTED_MODEL`,
  `SHOW_CONTEXT`, `LIMIT_WARN_AT`):

```
LANGUAGE=auto        # or en / zh / ja / ko / es / fr / de / pt
SHOW_ACCOUNT=true    # or false
```

Do NOT write `EXPECTED_MODEL` unless the user explicitly asked for a manual
override — auto-detection from the settings.json `model` field is the default.

## 4. Register the statusLine

- Backup first:
  `cp ~/.claude/settings.json ~/.claude/settings.json.bak-model-guard-$(date +%Y%m%d-%H%M%S)`
- If replacing a foreign statusLine, save it for restore-on-uninstall:
  `printf 'PREV_STATUSLINE_B64=%s\n' "$(jq -c .statusLine ~/.claude/settings.json | base64 -w0)" >> ~/.claude/model-guard.conf`
- Merge without touching other keys:

```bash
jq '.statusLine={"type":"command","command":"'"$HOME"'/.claude/model-guard.sh","padding":0,"refreshInterval":5}' \
  ~/.claude/settings.json > ~/.claude/settings.json.tmp && mv ~/.claude/settings.json.tmp ~/.claude/settings.json
```

- Validate: `jq -e .statusLine ~/.claude/settings.json` must succeed.

## 5. Verify — show the user real output

Run both and let the raw ANSI output render in the terminal (band colors included):

1. Normal state — use the user's actual pinned model id so it renders green:
   `echo '{"model":{"id":"<pinned-model-id>","display_name":"<name>"},"effort":{"level":"xhigh"},"thinking":{"enabled":true},"context_window":{"used_percentage":12}}' | ~/.claude/model-guard.sh`
2. Downgrade drill — must render the full red alarm band:
   `echo '{"model":{"id":"claude-haiku-4-5","display_name":"Haiku 4.5"}}' | ~/.claude/model-guard.sh`

If the drill does not come out as an alarm (e.g. the user's `model` is `default`,
so there is no expectation), explain that and point at `EXPECTED_MODEL` in the conf.

## 6. Report (short)

- The statusline hot-reloads: the band should appear at the bottom within seconds
  (worst case: next session).
- Re-run `/model-guard:setup` anytime to change options or after a plugin update.
- `/model-guard:remove` uninstalls cleanly and restores any previous statusline.
- Advanced knobs live in `~/.claude/model-guard.conf`: `LANGUAGE`, `SHOW_ACCOUNT`,
  `SHOW_CONTEXT`, `LIMIT_WARN_AT` (5h rate-limit warning threshold, default 80,
  `off` to disable), `EXPECTED_MODEL` (grep -Ei pattern override).
