<div align="center">

<img src="assets/hero.svg" alt="model-guard statusline — four states" width="880">

# 🚨 model-guard

**The statusline that catches silent model downgrades in Claude Code — and, since 1.1, undoes the one a safeguard flag causes.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Made for Claude Code](https://img.shields.io/badge/made%20for-Claude%20Code-d97757)](https://claude.com/claude-code)
[![Deps](https://img.shields.io/badge/deps-bash%20%2B%20jq%20%2B%20curl-4EAA25)](#install)
[![Languages](https://img.shields.io/badge/band%20languages-8-8A2BE2)](#configuration)

English · [简体中文](README.zh-CN.md)

</div>

---

## The problem

You hit a usage limit mid-session. Claude Code falls back to a weaker model — **quietly**. No flash, no bell, just a subtly dumber pair programmer. You keep prompting for another hour, wondering why the code got sloppy, while the tokens keep burning.

This plugin exists because exactly that happened to us: half a working session on a silently-downgraded model before anyone noticed the tiny model name in the corner. Never again.

## What you get

One always-on, full-width color band at the bottom of every session. You don't read it — you *notice* it.

| Band | Meaning |
|:---:|---|
| 🟩 `✔` | Model matches what this machine expects |
| 🟦 `⬆` | Running **above** your default — FYI, no alarm |
| 🟥 `🚨` | **Silent downgrade** — the whole bar turns red and tells you to `/model` back |
| 🟧 `🔁` | **Recovered** — a flag downgraded the session, the plugin switched it to the recovery model |
| 🟦 `●` | No expectation configured — neutral display |

And model identity is only half the story. Red **inline patches** catch the other silent downgrades:

- ⚡ **Reasoning effort** dropped below your configured `effortLevel`
- 🧠 **Extended thinking** switched off
- ⏳ **5-hour rate-limit window ≥ 80 %** — the precondition for a forced fallback, flagged *before* it happens

Plus the useful everyday bits: current model & effort, context-window usage, your account's 5-hour and 7-day usage (`⏳ 5h 37% · 7d 18%`), and which account you're logged in with (multi-account users know the pain).

## Auto-recovery

Showing a downgrade is half the job. The most common silent downgrade today is a **safeguard flag**: Fable's (or Opus 5's) safeguards flag a message, Claude Code re-runs it on Opus 4.8 — and keeps the whole session there. With the 1.1 hooks the session instead

1. **stops** — the next tool call is denied and the turn ends (`PreToolUse`);
2. **switches** — a detached driver presses Esc, types `/model <recovery model>` and `/effort <level>` into the session's own terminal, and waits for Claude Code's `PostModelSwitch` event to confirm the switch (the plugin's `PreModelSwitch` hook answers *allow*, so no cache-miss dialog gets in the way);
3. **continues** — sends the continue prompt, and the interrupted task resumes on the recovery model.

Default: `claude-opus-5[1m]` at `max` effort, continue prompt `Continue.` (or `继续` when the band language is Chinese). Measured round trip: about 8 seconds from the downgrade to the first token on the recovery model.

Steps 2 and 3 only exist where the terminal can be driven: a tmux pane (`send-keys`), a zellij pane (`action write-chars`), or kitty with remote control over a socket (`allow_remote_control socket-only` + `listen_on unix:@kitty` in `kitty.conf`, then restart kitty — `setup` offers to add both lines). tmux and zellij need no configuration at all. Anywhere else the plugin does step 1 and nothing more: the turn stops once, the band names the `/model` to run, and the hooks stay out of your way.

Inside a multiplexer the keystrokes address one pane by id, never "the focused window", so a recovery in one pane cannot type into the session next door.

Two details worth knowing:

- `/model <id>` in an interactive session also saves `<id>` as your default for new sessions. The plugin puts your previous default back after its own switch, so a recovery never changes what tomorrow's sessions start with.
- If the recovery model itself gets flagged (Opus 5 → Opus 4.8), or a session is downgraded more than `RECOVER_MAX` times, the plugin only stops. The band says so; pick a model with `/model`.

## Install

```
/plugin marketplace add ventusff/claude-model-guard
/plugin install model-guard@claude-model-guard
/model-guard:setup
```

The last step is **interactive** — arrow keys, two questions, done. It copies the script, writes the config, and registers the `statusLine` in `~/.claude/settings.json` with a timestamped backup. No copy-pasting shell commands from a README.

<div align="center"><img src="assets/setup.svg" alt="interactive setup" width="880"></div>

> **Why is there a setup step at all?** Claude Code plugins can't register a main statusline by themselves (plugin `settings.json` only supports `agent` and `subagentStatusLine`). `setup` is the one honest extra step, and it is a one-time one: when a later plugin update ships a newer script, the session-start hook refreshes the installed copy itself and says so.

**Requirements:** bash 4+, [`jq`](https://jqlang.github.io/jq/) and `curl`; the recovery hooks also use `flock` and `setsid` (util-linux) and, when present, `notify-send` for a desktop notice. No daemon. The one network call is the statusline asking Claude Code's own usage endpoint (the one behind `/usage`) for your account's rate-limit usage, with the login token Claude Code stored, at most once every 30 s per machine; nothing else leaves the machine. Plugin hooks load at session start — restart your sessions after installing or updating.

## How "downgraded" is decided

**Expected model** — first hit wins:

1. `EXPECTED_MODEL` in `~/.claude/model-guard.conf` (a `grep -Ei` pattern, manual override)
2. `~/.claude/statusline-expected-model` (legacy override file)
3. The `model` you pinned in `~/.claude/settings.json` (`opus[1m]` → `opus`; `default` = no expectation)

**Strength ranking:** family `fable/mythos > opus > sonnet > haiku`, then version within the family (`claude-opus-5 > claude-opus-4-8`).

- Actual model ranks **below** expected → 🟥 full-width alarm.
- Unknown ids score zero → 🟥. We can't prove it isn't weaker, so we don't guess. Conservative by design.
- Actual ranks **above** expected → 🟦 calm blue. Free upgrades are not emergencies.
- Automatic downgrades (Claude Code's `PostModelSwitch` with source `auto` or `resume`) use the same ranking to decide whether a recovery starts.

## Where the usage numbers come from

The 5-hour and 7-day numbers are your **account's**, asked from Claude Code's own usage endpoint (the one behind `/usage`) with the login token Claude Code stored — environment variable, macOS keychain or `~/.claude/.credentials.json`, in that order. One reading is shared by every session on the machine for 30 s.

They are deliberately not the `rate_limits` Claude Code hands to statuslines. That value is what one session last read from a response header: it stands still until that session gets another response, and it survives `/login`. After an account switch it keeps reporting the previous account — and keeps climbing while requests already in flight finish on the old token. Here a new login is a new cache key, so the next refresh asks again immediately; until the answer is in, the segment stays empty rather than showing another account's number. Sessions without a login token (API key, Bedrock, Vertex) fall back to the payload value.

## Configuration

Everything lives in `~/.claude/model-guard.conf` (created by `setup`, safe to edit by hand):

| Key | Default | What it does |
|---|---|---|
| `LANGUAGE` | `auto` | Band language. `auto` follows Claude Code's `language` setting, else English. Available: `en` `zh` `ja` `ko` `es` `fr` `de` `pt` |
| `SHOW_ACCOUNT` | `true` | Show the logged-in account email (reads `~/.claude.json` live — switching accounts updates the band) |
| `SHOW_CONTEXT` | `true` | Show context-window usage, e.g. `◔ 13%` |
| `SHOW_LIMIT` | `true` | Show the logged-in account's 5-hour and 7-day usage, e.g. `⏳ 5h 37% · 7d 18%` (see above) |
| `LIMIT_WARN_AT` | `80` | Red patch when the 5-hour rate-limit usage reaches N %. `off` disables |
| `EXPECTED_MODEL` | *(auto)* | Manual expected-model pattern, e.g. `opus\|fable` |
| `RECOVER` | `on` | Master switch for the recovery hooks (`off` disables stop + switch entirely) |
| `RECOVER_MODEL` | `claude-opus-5[1m]` | Model the session is switched to after an automatic downgrade |
| `RECOVER_EFFORT` | `max` | `/effort` level applied on the recovery model (`off` to leave it alone) |
| `RECOVER_PROMPT` | *(by language)* | Prompt sent to resume the interrupted task |
| `RECOVER_CHANNEL` | `auto` | How keystrokes reach the session: `auto` (tmux pane, then zellij pane, then kitty), `tmux`, `zellij`, `kitty`, `dryrun` (log only), `none` |
| `RECOVER_MAX` | `3` | Automatic recoveries allowed per session; beyond that the plugin only stops |
| `DEBUG` | *(off)* | `true` appends every hook input to `$XDG_RUNTIME_DIR/model-guard/debug.log` |

Re-run `/model-guard:setup` anytime to reconfigure interactively.

## Design notes

<details>
<summary><b>Why truecolor instead of normal ANSI colors?</b></summary>

Terminal themes remap the 16 basic ANSI colors — a "red background" can render as pink, and the contrast collapses exactly when you need the alarm to be unmissable. model-guard emits **truecolor** escape codes (with a fixed 256-color-cube fallback when `COLORTERM` is unsupported), bypassing theme palettes entirely.

All three foreground/background pairs are picked for WCAG contrast ≥ 7:1 (AAA):

| State | Colors | Contrast |
|---|---|---|
| OK | `#000000` on `#3FB950` | 8.3 : 1 |
| ALARM | `#FFFFFF` on `#B00020` | 7.3 : 1 |
| INFO | `#FFFFFF` on `#0D47A1` | 8.6 : 1 |
| RECOVERED | `#000000` on `#FFB300` | 11.4 : 1 |

No blink (SGR 5) — its rendering is unpredictable across terminals.

</details>

<details>
<summary><b>How does the automatic recovery work, and why does it type into the terminal?</b></summary>

Claude Code hooks can observe a model switch (`PostModelSwitch` carries `from_model`, `to_model` and a `source` — `auto` for a fallback) and veto a user-initiated one (`PreModelSwitch`), but no hook can *set* the session model, and a running interactive session has no control channel besides its keyboard. So the plugin does exactly what you would do by hand — Esc, `/model`, `/effort`, "continue" — through the terminal's own remote-control API, and never guesses: every step waits for its echo (Claude Code's session registry going idle, the `PostModelSwitch` event, the command's line in the transcript) before the next one.

The hooks keep one small JSON file per session in `$XDG_RUNTIME_DIR/model-guard/`:

| status | meaning |
|---|---|
| `pending` | downgraded with a keystroke channel; the driver is starting |
| `switching` | the driver is typing the switch |
| `recovered` | the session model changed after the downgrade (by the driver or by you) |
| `stopped` | downgraded, no automatic switch (no channel, the recovery model itself was flagged, downgraded again while recovering, or `RECOVER_MAX` hit): the turn is stopped once, then the hooks pass everything |

`SessionStart` forgets stale state (a latched fallback re-announces itself on resume as `PostModelSwitch` source `resume`, which triggers the switch but not the continue prompt); `SessionEnd` cleans up. `tests/run.sh` drives the whole state machine with synthetic payloads and a `dryrun` channel.

</details>

<details>
<summary><b>How does the band fill the whole row at any terminal width?</b></summary>

The script pads the output with ~300 trailing spaces (or a train of 🚨 in alarm state). Anything past the terminal width is clipped by the TUI, so the colored band always spans the full row — no width detection needed.

</details>

<details>
<summary><b>What exactly does <code>setup</code> touch?</b></summary>

- Copies the statusline script to `~/.claude/model-guard.sh`
- Writes your answers to `~/.claude/model-guard.conf`
- Merges a `statusLine` block into `~/.claude/settings.json` — after making a timestamped backup, without touching any other key
- If you had a different statusline before, it's saved and **restored on uninstall**

</details>

## Uninstall

```
/model-guard:remove
```

Unregisters the statusline (restoring whatever you had before), optionally deletes the script, config and per-session state, and keeps a settings backup. Then remove the plugin itself via `/plugin` if you want — the recovery hooks live in the plugin and go with it.

## License

[MIT](LICENSE) © [ventusff](https://github.com/ventusff)
