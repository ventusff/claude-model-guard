# Changelog

## 1.5.1 — 2026-09-09

- **Enable the Codex launcher in Fish.** Add a reversible PATH block to the
  existing Fish configuration (or create it when Fish is the login shell),
  respecting `XDG_CONFIG_HOME`. New terminals resolve Model Guard before stock
  Codex, including when its directory was already later in PATH. No persistent
  Fish universal variables, model defaults or running sessions are changed.
- Preserve custom shell content and dotfile symlinks on install/removal.
  Regression checks execute real Fish startup with quoted paths and verify
  that removal restores the official command.

## 1.5.0 — 2026-09-09

- **Passive Codex reasoning diagnostics.** Show the last response's reasoning
  tokens and exact-516 frequency over up to 20 measured responses. At high or
  greater effort, any exact-516 hit is highlighted through the turn; at least
  three hits among the last five measurements show `REASONING SUSPECT` in red.
  These are explicit heuristics, independent of the strict model-routing verdict.
- Deduplicate usage snapshots, ignore delayed/foreign events, distinguish fresh
  threads from attached history, and keep observations scoped to the request's
  model, provider, effort, tier and account. Higher 518n-2 values remain diagnostic
  counts. No extra inference requests, forced retries or model changes.
- Export allowlisted reasoning signals in `check`/`probe` JSON and add a standalone
  metadata-only historical audit. Expanded bilingual research covers Reddit's
  516 reports, existing hooks/proxies, KBF, PAMELA, fpverify and other fingerprints.
- Regression tests include genuine official-Codex SSE/WebSocket usage handling,
  duplicate and stale events, account transitions, and a real 516 TUI warning
  retained after resizing. Claude behavior retains the 1.4 per-model effort fix.

## 1.4.0 — 2026-09-09

- **Claude effort defaults follow the model picker.** Read the active model's
  saved `modelSettings` effort before the legacy global `effortLevel`, including
  `[1m]` context variants. Saving `high` no longer produces a false `high < xhigh`
  warning when the old global setting remains `xhigh`; real reductions still warn.
- **Codex CLI integration.** A persistent two-row terminal band puts requested
  versus server-reported model routing first, followed by account, reasoning,
  context and account usage. Matching reports are green, differences red, absent
  evidence amber; disconnected or stale observers are explicitly red.
- Uses the official Codex TUI/app-server protocol and an isolated tmux server.
  No Codex fork, HTTPS interception, credential-file access or model-default edits.
  Evidence is scoped to the visible thread and current sampling request. The
  plugin does not infer hidden weights or automatically change Codex models.
- Reversible bash/zsh installation, pinned Python dependency, Codex plugin skill,
  English/Chinese display, diagnostics and source-linked routing research.
- Strict `check` and separate `probe` commands return nonzero when routing is
  unverified or unavailable, with shareable metadata that omits account identity.
  Research covers recent GPT-4o claims, community fingerprints, negative controls
  and live checks; undisclosed backend routing remains unverifiable.
- Real Codex integration tests cover HTTP/SSE, WebSocket metadata, missing
  effective headers and a gpt-4o fixture mismatch; PTY tests exercise the actual
  terminal band and resizing. Claude regression tests cover per-model defaults,
  legacy settings and changes during a running session.

## 1.3.0 — 2026-09-08

- **The rate-limit reading is the logged-in account's.** The 5-hour and 7-day
  usage is asked from Claude Code's own usage endpoint (the one behind `/usage`)
  with the stored login token, one reading per machine shared by every session
  for 30 s. The `rate_limits` in the statusline payload is what one session last
  read from a response header: it stands still until that session gets another
  response and it survives `/login`, so after an account switch the band kept
  reporting — and updating — the previous account. Now a new login is asked at
  once; until the answer is in, the segment is empty rather than another
  account's number. Sessions without a login token keep the payload value.
- **`SHOW_LIMIT`** (default `true`) puts `⏳ 5h 37% · 7d 18%` in the everyday
  band. The `LIMIT_WARN_AT` red patch is unchanged and reads the same source.
- The account email and the credentials follow `CLAUDE_CONFIG_DIR`.

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
