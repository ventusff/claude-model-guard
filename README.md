<div align="center">

<img src="assets/hero.svg" alt="model-guard statusline — four states" width="880">

# 🚨 model-guard

**The statusline that catches silent model downgrades in Claude Code — before they burn your session.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Made for Claude Code](https://img.shields.io/badge/made%20for-Claude%20Code-d97757)](https://claude.com/claude-code)
[![Deps](https://img.shields.io/badge/deps-bash%20%2B%20jq-4EAA25)](#install)
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
| 🟦 `●` | No expectation configured — neutral display |

And model identity is only half the story. Red **inline patches** catch the other silent downgrades:

- ⚡ **Reasoning effort** dropped below your configured `effortLevel`
- 🧠 **Extended thinking** switched off
- ⏳ **5-hour rate-limit window ≥ 80 %** — the precondition for a forced fallback, flagged *before* it happens

Plus the useful everyday bits: current model & effort, context-window usage, and which account you're logged in with (multi-account users know the pain).

## Install

```
/plugin marketplace add ventusff/claude-model-guard
/plugin install model-guard@claude-model-guard
/model-guard:setup
```

The last step is **interactive** — arrow keys, two questions, done. It copies the script, writes the config, and registers the `statusLine` in `~/.claude/settings.json` with a timestamped backup. No copy-pasting shell commands from a README.

<div align="center"><img src="assets/setup.svg" alt="interactive setup" width="880"></div>

> **Why is there a setup step at all?** Claude Code plugins can't register a main statusline by themselves (plugin `settings.json` only supports `agent` and `subagentStatusLine`). `setup` is the one honest extra step — and a session-start hint reminds you if it's still pending, or when a plugin update ships a newer script.

**Requirements:** bash 4+ and [`jq`](https://jqlang.github.io/jq/). That's the whole dependency list — one script, no daemon, nothing phones home.

## How "downgraded" is decided

**Expected model** — first hit wins:

1. `EXPECTED_MODEL` in `~/.claude/model-guard.conf` (a `grep -Ei` pattern, manual override)
2. `~/.claude/statusline-expected-model` (legacy override file)
3. The `model` you pinned in `~/.claude/settings.json` (`opus[1m]` → `opus`; `default` = no expectation)

**Strength ranking:** `fable/mythos > opus > sonnet > haiku`.

- Actual model ranks **below** expected → 🟥 full-width alarm.
- **Same rank but a different id** → still 🟥. We can't prove it isn't weaker, so we don't guess. Conservative by design.
- Actual ranks **above** expected → 🟦 calm blue. Free upgrades are not emergencies.

## Configuration

Everything lives in `~/.claude/model-guard.conf` (created by `setup`, safe to edit by hand):

| Key | Default | What it does |
|---|---|---|
| `LANGUAGE` | `auto` | Band language. `auto` follows Claude Code's `language` setting, else English. Available: `en` `zh` `ja` `ko` `es` `fr` `de` `pt` |
| `SHOW_ACCOUNT` | `true` | Show the logged-in account email (reads `~/.claude.json` live — switching accounts updates the band) |
| `SHOW_CONTEXT` | `true` | Show context-window usage, e.g. `◔ 13%` |
| `LIMIT_WARN_AT` | `80` | Red patch when the 5-hour rate-limit usage reaches N %. `off` disables |
| `EXPECTED_MODEL` | *(auto)* | Manual expected-model pattern, e.g. `opus\|fable` |

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

No blink (SGR 5) — its rendering is unpredictable across terminals.

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

Unregisters the statusline (restoring whatever you had before), optionally deletes the script and config, and keeps a settings backup. Then remove the plugin itself via `/plugin` if you want.

## License

[MIT](LICENSE) © [ventusff](https://github.com/ventusff)
