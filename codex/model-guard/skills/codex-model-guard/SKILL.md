---
name: codex-model-guard
description: Install, inspect, update or remove the Model Guard status band for Codex CLI, including server-reported model routing and account identity. Use for Model Guard setup and routing diagnostics; it does not identify undisclosed backend models.
---

Model Guard runs the official Codex CLI with a persistent terminal band. Plugin installation makes this skill available; the terminal launcher needs one setup step.

For setup or an update, run `python3 scripts/install.py` from this plugin's root (two directories above this skill). Use `--language zh` for Chinese or `--language en` for English. Requires Python 3.11+, tmux, and official Codex 0.153.4+. Install missing dependencies using the machine's existing package manager when authorized.

The installer creates a private Python environment and adds a managed PATH block to bash/zsh startup files. It preserves the official executable, model defaults, provider configuration and login files. After installation, run `~/.local/share/model-guard-codex/bin/model-guard-codex doctor`; if `MODEL_GUARD_CODEX_HOME` is set, use that directory instead. A new terminal picks up the launcher, then the user runs `codex` normally. Existing sessions continue as they are.

For diagnosis use `model-guard-codex status --json` (current guarded session, or a list of this user's sessions) and `model-guard-codex doctor`. The most recent server report is evidence of what the provider disclosed, not an independent attestation of the underlying weights. A selected model, `response.model`, response style, benchmark question or an assistant's self-identification must never turn an unverified route into a verified one. Do not request raw transport TRACE logs or print auth files. Server model information can be absent: say so.

For a strict routing check use `model-guard-codex check --json` inside the guarded terminal, or pass `--session DIRECTORY` explicitly. Exit codes are 0 for a reported match, 2 for a reported difference, 3 for unverified, and 4 for unavailable. `model-guard-codex probe --json` makes one separate ephemeral, read-only request through official authentication, consuming provider quota. Use it when the user authorizes an active check; its optional `-m MODEL -r EFFORT` affects only that probe. A separate probe cannot certify another live session. Check/probe JSON omits account identifiers; status JSON includes the displayed account. Consult `ROUTING.md` or `ROUTING.zh-CN.md` for inspected community solutions and their limits.

For removal, run `model-guard-codex remove`. It removes only its managed shell integration and launchers; existing sessions, settings and backups remain. The plugin itself can then be removed with Codex's plugin manager if requested. Do not terminate the user's sessions to finish setup, removal or validation.
