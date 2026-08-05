# Changelog

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
