# Changelog

## 1.1.0 — 2026-09-04

Auto-recovery from safeguard-flag downgrades.

- Hooks (`PostModelSwitch`, `PreModelSwitch`, `PreToolUse`, `UserPromptSubmit`,
  `SessionStart`, `SessionEnd`): an automatic downgrade stops the turn, a
  detached driver switches the session to `RECOVER_MODEL` at `RECOVER_EFFORT`
  through the terminal's remote control (tmux pane or kitty socket) and resumes
  the task with `RECOVER_PROMPT`; the previous default model is restored after
  the switch. Per-session state in `$XDG_RUNTIME_DIR/model-guard/`.
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
