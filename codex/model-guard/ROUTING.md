# Codex routing: research and evidence

Verified on Linux (`nomad-u`), 2026-09-09, using official Codex **0.153.4** and the matching source commit **3d2ee51ca2d5db578f328aa75e20aa22c0197c9a**.

[中文调研结论](ROUTING.zh-CN.md)

## What can be known

The useful distinction is between the requested model, the model identifier disclosed by the server, and the undisclosed implementation behind that identifier. A client can compare the first two. Without an independent attestation mechanism it cannot establish which weights actually generated a reply if the provider withholds or rewrites metadata. Model Guard reports this boundary in the UI: missing evidence is amber, never an assumed match.

An original community report reproduced `gpt-5.3-codex` requests returning a `gpt-5.2` identifier; an OpenAI collaborator confirmed that some cyber-safety cases were rerouted and discussed adding notifications. This establishes that rerouting can occur. It does not establish a universal GPT-4o fallback or a reliable behavioral fingerprint. [Original report and maintainer discussion](https://github.com/openai/codex/issues/11189).

A newer reporter observed missing server-model information while requesting `gpt-5.6-sol`. This is a useful example of the observability gap, not independent proof of a route change. [Report #34988](https://github.com/openai/codex/issues/34988).

**There is currently no reliable client-side solution found in this research for identifying an undisclosed GPT-4o fallback.** The implemented guard detects *disclosed* routing differences. It does not resolve the opaque-backend problem merely by displaying `UNVERIFIED`.

## Recent GPT-4o claims and behavioral checks

The [September 5 original “100% detection” post](https://linux.do/t/topic/2858863) now marks its own method as inaccurate/inapplicable. Its [follow-up](https://linux.do/t/topic/2861622) still infers routing from SVG vocabulary and generated pictures, and includes counterexamples. The [September 9 “strong evidence” post](https://linux.do/t/topic/2877589) infers GPT-4o from Plan Mode behavior. None of these reports provides a backend model identifier establishing GPT-4o. These observations can motivate investigation of output quality; they do not identify the model.

[ModelTrace](https://github.com/xqy2006/ModelTrace), audited at `60949ef522a84f66b1236b459308b48028d36949`, uses three numeric-output probes. Its author describes the result as attribution within a fixed candidate set; that set contains 13 models and **no GPT-4o**. An unknown model is nevertheless assigned to an existing candidate. [hlwy-ai-checker](https://github.com/hanlinwenyuan/hlwy-ai-checker) also explicitly describes its output as statistical consistency, not proof of model identity.

Our offline negative controls used ModelTrace's unchanged algorithm, NumPy 2.3.3, and its pinned unified bank. No model was called for these controls:

| Input, three sequences of 310 integers each | Tool's top candidate | Displayed closed-set probability |
|---|---|---|
| Python PRNG, uniform 1–355, seed 20260909 | gpt-6-astra | 87.59% |
| Repeated number 42 | claude-opus-4-8 | 58.33% |
| Counting from 1 to 310 | gpt-5.4 | 99.94% |

These are out-of-distribution inputs, deliberately outside the model-generated challenge protocol. They demonstrate why the displayed percentage must not be interpreted as probability that a named model actually served a request. They do not measure the tool's accuracy on valid model outputs. A real three-probe run through the installed official Codex, requesting `gpt-6-astra` at the unchanged `max` effort, ranked `gpt-6-astra` first at 99.12%. Effective model metadata was absent for all three requests. This supports behavioral similarity in that experiment, not backend verification.

The separate research paper [One Token Is Enough](https://arxiv.org/abs/2607.10252) reports probabilistic identification/verification from repeated single-token samples; it does not supply an error-free per-turn model oracle. [The candy-eval discussion](https://github.com/router-for-me/CLIProxyAPI/discussions/3937) studies answer quality and repeated reasoning-token counts such as 516, rather than establishing a particular backend identity. Model Guard therefore does not turn vocabulary, numeric fingerprints, short reasoning, or a benchmark answer into a verified route.

## Community approaches considered

| Approach | Useful part | Boundary for this task |
|---|---|---|
| [sh-ai-x/codex-statusline](https://github.com/sh-ai-x/codex-statusline) | Configure stock model/context/usage footer items | A configured model is not backend evidence; no arbitrary command renderer |
| [mullller/codex-hud](https://github.com/mullller/codex-hud) | Use tmux to keep a HUD visible around stock Codex | Latest-session-file selection is insufficient for strict per-terminal routing attribution |
| [brandonwie/codex-hud](https://github.com/brandonwie/codex-hud) | Optional patched native footer and version checks | Maintaining a patched binary ties upgrades to custom runtime builds |
| [Every Code](https://github.com/just-every/code) | Community Codex fork; its author linked automatic route detection in #11189 | Replacing the user's Codex distribution would expand this plugin's maintenance scope |
| Capture full SSE/WS TRACE and inspect model fields | Useful for reproducing old reports | Can persist prompts and tool outputs; `response.model` is not the current client's effective-model authority |

The selected design uses tmux for display and official local app-server messages for session identity, without depending on a Codex source fork or choosing whichever session file was touched most recently. No source code was copied from these community projects.

Every Code was additionally inspected at `07533447f713d39763047543cc19e1015a3a6a1e`: its [stream parser](https://github.com/just-every/code/blob/07533447f713d39763047543cc19e1015a3a6a1e/code-rs/core/src/client.rs) reads `response.created.response.model`, and its [comparison](https://github.com/just-every/code/blob/07533447f713d39763047543cc19e1015a3a6a1e/code-rs/core/src/codex/streaming.rs) accepts any nonempty hyphen suffix of the requested model. This can conceal a meaningfully different suffixed identifier. We did not adopt that equality rule.

## What official Codex 0.153.4 exposes

The official [`tui.status_line` setting](https://learn.chatgpt.com/docs/config-file/config-reference) accepts built-in item identifiers. The exact release's [status item enum](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/tui/src/bottom_pane/status_line_setup.rs) has no external renderer or account-email item. A plugin cannot register a Claude-style native `statusLine.command`.

For routing, these are the relevant source boundaries:

- [Responses parser](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/codex-api/src/sse/responses.rs): effective model extraction checks `response.headers` first, then top-level event `headers`. Both accept case-insensitive `openai-model` / `x-openai-model`, including array-valued headers. It does **not** use `response.model` for effective identity.
- [WebSocket transport](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/codex-api/src/endpoint/responses_websocket.rs): handshake/model metadata becomes a `ServerModel` event. The handshake's model can be reused on that connection; this is a report, not a fresh attestation of every generated token.
- [Core session](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/session/mod.rs): matching server models are logged at INFO; differing models produce a warning and a reroute event. The warning prose/reason is cyber-specific even though the comparison is a generic mismatch. Model Guard therefore does not infer the cause or model strength from that prose.
- [Turn processing](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/session/turn.rs): model warnings can be suppressed after the first mismatch within a turn. Model Guard latches that mismatch through the turn; absence of another event is not proof of recovery.
- [Public model notifications](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/model.rs): `model/rerouted` identifies the thread, turn, requested and reported models. It provides mismatch evidence, not a positive confirmation stream for matching requests.

The choice of effective headers is deliberate: official [PR #12061](https://github.com/openai/codex/pull/12061), merged February 18, removed `response.model` checks to reduce false positives and use the correct model slug. Merely restoring that old check would not solve routing verification.

These findings are specific to the inspected release. Later versions may change log targets or protocol details. Unknown/missing fields must reduce the display to unverified or monitor-lost; they must not be filled from the selected model or an older turn.

## Runtime design

```text
your terminal
  └─ isolated tmux server (two footer rows)
       ├─ official Codex TUI
       │    ↕ private Unix WebSocket, JSON-RPC
       ├─ Model Guard adapter
       │    ↕ stdio, JSON-RPC
       └─ official Codex app-server → original provider, original TLS/auth
```

Only the original app-server connects to the model provider. The adapter does not intercept HTTPS, handle authorization headers or read `auth.json`. The Unix socket lives in a randomly named owner-only directory. Helpers use Python isolated mode so a workspace cannot shadow the installed package. No additional TCP listener is created by Model Guard.

The adapter forwards requests, notifications and server-initiated tool requests. Its additional operations are read-only `account/read` and, for ChatGPT accounts, `account/rateLimits/read`. Requests are correlated by id and authentication epoch; delayed reads and unscoped streaming quota updates cannot repopulate old account usage after an observed login change.

Structured stderr is consumed in memory with the filter `off,codex_core::session=info,codex_core::session::turn=trace`. The core turn TRACE scope supplies thread/turn/model span identifiers, while transport TRACE remains disabled. Only exact model-report records and sampling-boundary metadata enter state. Prompts, tool results, credentials, complete log lines and arbitrary response objects are not written to the plugin's state files.

The display is pinned to the TUI-selected thread. Child-thread events cannot take focus. A new sampling request clears positive confirmation; a mismatch remains visible until the turn finishes, and idle evidence is labeled as the last turn. Model selection for a future turn does not relabel an in-flight request. Heartbeats older than five seconds render red.

Resume/fork, explicit remote-server, profile-v2 and OSS/local-provider invocations delegate to stock Codex with a visible notice. Remote-workspace semantics otherwise change resume/fork directory selection, and the separate official app-server does not accept the TUI's profile-v2 loader flag. Noninteractive commands delegate unchanged.

## Strict standalone checks

`model-guard-codex check --json` checks this terminal's guarded session without making an inference request. Outside a guarded session, pass its runtime directory with `--session`; the command does not guess another terminal's session. `model-guard-codex probe --json` makes one separate ephemeral, read-only request using the official app-server's own authentication and the current workspace configuration. It consumes provider quota and does not certify an existing session. Optional `-m MODEL -r EFFORT` applies only to the probe.

Both commands return `0` only for matching effective model disclosure, `2` for a disclosed mismatch, `3` for unverified routing, and `4` for an unavailable observer or failed probe. JSON exports omit account identifiers and conversation text. `weights_verified` is always false: even matching provider metadata is not independent verification of weights.

## Validation

The suite drives the installed official binary against local Responses fixtures with no real login. It covers matching and mismatching effective model headers, metadata-free replies whose `response.model` deliberately claims GPT-4o, HTTP/SSE and WebSocket transport, per-thread/turn attribution, account changes, terminal-format injection, observer heartbeat expiry, and real tmux/TUI rendering with a resize to 80 columns.

The GPT-4o replies in these tests are explicitly **synthetic fixtures**. Passing the tests proves that the integration detects a disclosed mismatch; it is not evidence that OpenAI has routed this machine's traffic to GPT-4o.

## Live check on the development machine

A minimal real-account request on nomad-u selected `gpt-6-astra`. The adapter received account identity and quota data but no effective server-model report, so the route remained unverified. No downgrade was established. Account identifiers and tokens are deliberately omitted from this public record.

An additional default WebSocket probe confirmed that neither handshake model metadata nor a core effective-model event was present. A separate diagnostic using the official app-server with an invocation-only OpenAI provider alias and WebSockets disabled returned SSE `response.model=gpt-6-astra`, with no effective model report. The diagnostic did not change the user's provider/model configuration files. Raw transport data was parsed in memory; only allowlisted results were retained. The normal launcher continues to use the original provider and transport.
