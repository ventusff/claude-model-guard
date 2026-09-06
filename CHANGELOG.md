# Changelog

## 1.2.0 — 2026-09-06

- **zellij is a recovery channel.** `auto` now tries a tmux pane, then the zellij
  pane named by `ZELLIJ_PANE_ID`, then kitty remote control. A non-numeric or
  absent pane id leaves the channel unavailable rather than guessing a target.
- **The input box is cleared before every typed line.** Interrupting a turn puts
  the interrupted prompt back into the box, so the model command used to be
  appended to it and submitted as one unusable prompt, and the switch never
  happened.
- **A turn's interruption is acknowledged by the session registry leaving `busy`**,
  not by an interruption record in the transcript, which this Claude Code version
  does not always write.
- **A switch the user did not ask for always starts a recovery.** Only the
  named user-driven sources (`command`, `picker`, `sdk`, `config`, `fast_mode`,
  `slash_command`) pass through, so a source name added later cannot let a
  downgrade slip by.
- **A plugin update no longer needs `/model-guard:setup`.** The session-start
  hook refreshes the installed statusline script in place and reports the new
  version; config and settings are untouched.

## 1.1.1 — 2026-09-04

- Without a keystroke channel (or when an automatic switch is not allowed) a
  downgrade stops the running turn once and the hooks step aside: no prompt
  gate, no second-submission release, no session-start hint. A `Stop` hook
  marks a turn that ended by itself.
- Driver: transcript match counter fixed; a failed switch leaves the session
  stopped; tmux channel verified live.

## 1.1.0 — 2026-09-04

Auto-recovery from safeguard-flag downgrades.

- Hooks (`PostModelSwitch`, `PreModelSwitch`, `PreToolUse`, `Stop`,
  `UserPromptSubmit`, `SessionStart`, `SessionEnd`): an automatic downgrade
  stops the turn. Where the terminal can be driven (tmux pane or kitty socket)
  a detached driver then switches the session to `RECOVER_MODEL` at
  `RECOVER_EFFORT` and resumes the task with `RECOVER_PROMPT`, restoring the
  previous default model afterwards; anywhere else the stop is all that
  happens. Per-session state in `$XDG_RUNTIME_DIR/model-guard/`.
- Statusline: amber 🔁 band while running on the recovery model; red bands
  for stopped / switching / halted; strength ranking now compares versions
  within a family (`claude-opus-5 > claude-opus-4-8`) instead of alarming on
  every unequal id of the same family.
- Config keys `RECOVER`, `RECOVER_MODEL`, `RECOVER_EFFORT`, `RECOVER_PROMPT`,
  `RECOVER_CHANNEL`, `RECOVER_MAX`, `DEBUG`; `setup` asks about recovery and
  offers to enable kitty remote control.
- `tests/run.sh`: state-machine, driver (dryrun channel) and statusline tests.

## 1.0.0 — 2026-08-05

Initial release.

- Full-width, theme-proof (truecolor + 256-color fallback, WCAG AAA contrast)
  statusline band: model state, reasoning effort, context usage, account.
- Silent-downgrade alarms: model below expectation, effort below `effortLevel`,
  extended thinking switched off, 5-hour rate-limit pressure (pre-fallback warning).
- 8 band languages (en / zh / ja / ko / es / fr / de / pt), auto-following
  Claude Code's `language` setting.
- Interactive `/model-guard:setup` and `/model-guard:remove` skills — backup,
  register, verify, restore; no manual config editing.
- SessionStart hint hook: nudges until setup is done, flags version drift after
  plugin updates.
