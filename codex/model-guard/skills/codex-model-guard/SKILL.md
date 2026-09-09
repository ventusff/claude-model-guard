---
name: codex-model-guard
description: Install, inspect, update or remove native Model Guard for Codex CLI. Use for its status line, model-routing diagnostics, passive 516 reasoning anomalies and account display.
---

Model Guard extends the native Codex status line. It uses a pinned custom build of official Codex with auditable source patches. Do not add a terminal wrapper, tmux server, separate live app-server adapter or shell PATH override.

The default footer is quiet: selected/requested model, request effort and the known account. Only a disclosed different model or repeated reasoning anomaly expands a warning. Missing disclosure and single 516 hits belong in `/status`; never add permanent question marks or yellow unknown banners. At high/xhigh/max/ultra, at least three of the last five measured responses with exactly 516 reasoning tokens produce a heuristic warning. This threshold has no calibrated false-positive rate and does not identify a replacement model. Never infer recovery from answer quality or automatically retry/change models.

For setup/update, run `python3 scripts/install.py` from this plugin's root (two directories above this skill). Use `--language zh` or `--language en`. The prebuilt runtime requires Linux x86_64, glibc 2.39+, Python 3.12+, and official standalone Codex 0.153.4 with its existing executable symlink. The installer verifies `native/release.json`, prepares versioned files, then atomically switches the Codex symlink. It preserves model/provider defaults and login files. Native builds must be updated together with the plugin; do not silently substitute a different upstream version. See `native/README.md` for source builds.

Run `model-guard-codex doctor` after installation. Then `codex`, `cx`, `resume` and `fork` work through the same native executable in the current shell. Do not say that already running sessions were upgraded. Normal input handling, terminal scrolling, paste, profile loading and directory selection remain Codex's own. Remote app-servers need the metadata extension for complete disclosures.

Use `/status` inside the relevant Codex conversation for live routing evidence and reasoning details. Selected model, effort setting, `response.model`, assistant self-identification, benchmark answers and a 516 hit cannot prove backend identity. A provider may omit or rewrite effective-model headers. Explain absent evidence when asked; do not claim an unknown route is verified. Never read login files, persist raw transport logs, or edit Codex session records to diagnose routing. Read `ROUTING.md` or `ROUTING.zh-CN.md` for researched community methods and limits.

`model-guard-codex probe --json` makes one separate ephemeral read-only model request through official authentication and consumes provider quota. Use it for an authorized active check; `-m MODEL -r EFFORT` affects only that probe. It cannot certify another conversation. Exit codes are 0 for matching effective-model disclosure, 2 for a difference, 3 for missing disclosure, and 4 for failure/unavailability. JSON omits account identifiers and conversation text. Old external `status` and `check` commands direct users to native `/status`.

For removal, run `model-guard-codex remove`. It restores the original Codex symlink only while the entry is still managed, and preserves running sessions, packages and preferences. The plugin may then be removed with Codex's plugin manager if requested. Never terminate user sessions to finish installation, removal or validation.
