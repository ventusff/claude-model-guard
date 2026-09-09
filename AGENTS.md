# AGENTS.md — claude-model-guard

A Claude Code plugin (`model-guard`, distributed from this repo as marketplace `claude-model-guard`): a full-width statusline band that flags a silent model downgrade, plus hooks that undo a safeguard-flag downgrade — stop the turn, type `/model` and `/effort` into the session's own terminal (tmux, zellij or kitty), resume the task. Pure bash + jq, no build step, no daemon. Installed via `/plugin marketplace add ventusff/claude-model-guard`, so `main` on GitHub is what every install fetches.

The Codex integration lives independently under `codex/model-guard/`: a valid Codex plugin and Python package, with a pinned native Codex build with metadata events and a conditional footer warning; the Python app-server adapter is used only by explicit standalone probes. See its `ROUTING.md` for evidence boundaries and primary sources. It monitors disclosed routing and does not perform automatic model recovery.

## Layout

| Path | What |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest: name, version, description, keywords. |
| `.claude-plugin/marketplace.json` | The marketplace this repo is; lists the one plugin with `source: ./`. |
| `hooks/hooks.json` | Registers `scripts/guard-hook.sh` on SessionStart, SessionEnd, PreModelSwitch, PostModelSwitch, PreToolUse, Stop, UserPromptSubmit; `check-install.sh` on SessionStart. |
| `scripts/statusline.sh` | The statusline. `setup` copies it to `~/.claude/model-guard.sh`; that copy is what Claude Code runs. Asks Claude Code's usage endpoint for the logged-in account's rate-limit usage, cached in `usage.json` under the state dir. |
| `scripts/lib.sh` | Shared helpers (`mg_*`): config, language, model strength ranking, per-session state, keystroke channels. Sourced by the hook and the driver. |
| `scripts/guard-hook.sh` | The one hook command; dispatches on `hook_event_name`, answers with hook JSON. |
| `scripts/recover.sh` | The detached driver that types Esc, `/model`, `/effort`, continue prompt into the terminal. |
| `scripts/check-install.sh` | SessionStart: hints until setup is done; refreshes the installed statusline copy when the plugin ships a newer `MG_VERSION`. |
| `skills/setup/SKILL.md`, `skills/remove/SKILL.md` | `/model-guard:setup` and `/model-guard:remove` — step lists the agent follows, not shell scripts. |
| `tests/run.sh` | The test suite: synthetic hook payloads, `dryrun` channel, fake tmux/zellij binaries, isolated state and config. |
| `README.md`, `README.zh-CN.md`, `CHANGELOG.md` | User docs in both languages, and the release log. |
| `assets/` | The README's hero and setup SVGs. |
| `codex/model-guard/model_guard/` | Codex probe metadata, standalone probe adapter, native installer and diagnostics. |
| `codex/model-guard/tests/` | Python unit tests and opt-in real Codex/HTTP/WebSocket/PTY fixtures. |

## Run and verify

```sh
tests/run.sh      # the whole suite (state machine, driver, channel detection, bands); must end "0 failed"
```

For Codex, run from `codex/model-guard/` with Python 3.12+ and Codex 0.153.4: create a venv, install `requirements.lock` with `pip --require-hashes`, install the package with `pip --no-deps -e .`, then `PYTHONPATH=. MODEL_GUARD_INTEGRATION=1 <venv>/bin/python -m unittest discover -s tests -v`. Fixtures use isolated Codex homes and loopback servers; never use live credentials for regression tests.

Codex invariants: requested model is not observed evidence; absent headers stay unknown in diagnostics without a default warning; metadata is bound to thread/turn; model/account text is sanitized before native rendering. The observer never reads auth files or writes Codex session records. Preserve stock CLI behavior for noninteractive/profile/remote invocations and preserve existing terminals during install/removal. Code changes belong in the source package, never the installed environment. No terminal wrapper or separate multiplexer is permitted for Codex. Native source patches, schema artifacts, source pin and build instructions live in `codex/model-guard/native/`. Use the upstream `just test` runner for Rust checks and review native terminal behavior including `cx resume`. Keep the Codex manifest, Python package and pyproject release versions aligned with the four Claude release locations below.

Codex reasoning telemetry is a separate heuristic: a single exact 516 at high or greater effort stays in diagnostics; at least three of five recent valid response observations produces a visible heuristic warning. Higher 518n-2 values alone do not alert. Count unique native response IDs, not repeated usage notifications. Bind statistics to model/provider/effort/tier/account, preserve in-flight settings, and distinguish fresh threads from attachments/accepted rollbacks. Strict route exit codes never incorporate a heuristic as model identity.

Requirements: bash 4+, jq and curl; the recovery path also uses `flock` and `setsid`. There is no CI workflow — `tests/run.sh` on the machine is the bar. Hooks load at session start, so a change under `hooks/` or `scripts/` is only observed by a freshly started session, and the statusline change only after the installed copy is refreshed.

## Hard rules

- **The version lives in four places and must match**: `.claude-plugin/plugin.json`, `MG_VERSION` in `scripts/statusline.sh`, `MG_VERSION` in `scripts/lib.sh`, the top entry of `CHANGELOG.md`. `check-install.sh` decides whether to refresh a user's installed statusline by comparing `MG_VERSION` — a release that bumps plugin.json but not `MG_VERSION` leaves every user on the old script, silently.
- **The installed statusline is a copy** (`~/.claude/model-guard.sh`). Editing `scripts/statusline.sh` changes nothing in a running session until the copy is refreshed (session-start hook or `setup`).
- **Effort follows the active model's saved default.** Prefer `modelSettings[canonical_model].effortLevel` over the legacy global `effortLevel`; `[1m]` variants share the canonical key. Read it on each refresh. Never overwrite the user's saved effort to make an alarm disappear.
- **Config, settings, state and the login token are resolved through the `MODEL_GUARD_*` overrides** (`MODEL_GUARD_CONF`, `MODEL_GUARD_SETTINGS`, `MODEL_GUARD_STATE_DIR`, `MODEL_GUARD_SESSIONS_DIR`, and `MODEL_GUARD_CREDENTIALS`, which also switches off the environment and keychain lookups) in `lib.sh` and `statusline.sh`; the tests point them at a temp dir and put a stand-in `curl` first on `PATH`. A new read of `~/.claude/...` that bypasses them makes the suite touch the real machine or the network.
- **Hooks are silent unless they act.** Session start, upgrades, and switches from the named user-driven sources (`command`, `picker`, `sdk`, `config`, `fast_mode`, `slash_command`) produce no output and no state; every other switch source to a weaker model starts a recovery episode. The suite asserts both directions.
- **Keystrokes address one pane by id, never the focused window** — tmux `$TMUX_PANE`, zellij `terminal_<ZELLIJ_PANE_ID>`, kitty `$KITTY_WINDOW_ID`. A missing or non-numeric pane id means "no channel", not a guess.
- **A recovery never changes tomorrow's default.** `/model <id>` also writes `model` into `settings.json`; the driver restores the previous default afterwards, and the suite checks it.
- **Colours are truecolor with a 256-colour fallback, every pair >= 7:1 contrast, no blink.** No plain ANSI 16-colour codes — themes remap them and the alarm stops being an alarm.
- **`README.md` and `README.zh-CN.md` say the same thing** — change both. User-visible behaviour changes get a `CHANGELOG.md` entry.
- Comments and commit messages are English. A release is one commit titled `model-guard <version> — <what changed>`.
