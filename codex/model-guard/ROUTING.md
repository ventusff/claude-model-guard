# Codex routing: research and evidence

Verified on Linux (`nomad-u`), 2026-09-09, using official Codex **0.153.4** and the matching source commit **3d2ee51ca2d5db578f328aa75e20aa22c0197c9a**.

[中文调研结论](ROUTING.zh-CN.md)

## What can be known

Practical client-side detection is possible. Model Guard combines disclosed routing with passive reasoning-usage signals, and statistical probes can detect inconsistency even when effective-model headers are absent. The useful distinction is between the requested model, the model identifier disclosed by the server, and the undisclosed implementation behind that identifier. A client can compare the first two. Without an independent attestation mechanism it cannot establish which weights actually generated a reply if the provider withholds or rewrites metadata. Model Guard reports this boundary in the UI: missing evidence is amber, never an assumed match.

An original community report reproduced `gpt-5.3-codex` requests returning a `gpt-5.2` identifier; an OpenAI collaborator confirmed that some cyber-safety cases were rerouted and discussed adding notifications. This establishes that rerouting can occur. It does not establish a universal GPT-4o fallback or a reliable behavioral fingerprint. [Original report and maintainer discussion](https://github.com/openai/codex/issues/11189).

A newer reporter observed missing server-model information while requesting `gpt-5.6-sol`. This is a useful example of the observability gap, not independent proof of a route change. [Report #34988](https://github.com/openai/codex/issues/34988).

**Version 1.5 adopts exact-516 reasoning telemetry as a practical warning signal.** Statistical fingerprinting is a viable complementary audit method. Neither mechanism currently establishes an undisclosed GPT-4o identity for every individual request; this narrower limitation does not make anomaly detection useless.

## Passive 516 detection

The original #30364 report analyzed 390,195 token-count records and found a disproportionate exact-516 spike under the GPT-5.5 label. Its [author's Reddit explanation](https://www.reddit.com/r/codex/comments/1ujqo09/the_gpt55_516_reasoning_tokens_issue_is_not/) explicitly distinguishes the measured anomaly from proving truncation. The [GitHub issue](https://github.com/openai/codex/issues/30364) is closed as of this inspection; closure alone supplies no explanation of the phenomenon or evidence that every affected deployment was fixed.

An existing implementation is [bentoner/codex-516-hook](https://github.com/bentoner/codex-516-hook/tree/3729959d72544ef3f9db62b696306b1dbdae04e9). It reads completed response usage and warns through a Stop hook. The author reports 18/20 exact-516 runs through Codex with each of subscription and API-key authentication, versus 0/20 on a bare Responses request, for one trigger puzzle. A harder puzzle had wrong answers in 5 of 6 observed exact-516 runs. These are small, task-specific author measurements, but they provide a concrete reason to monitor the signal.[^hook]

That project's controls also matter: 1034/1552/2070/… occurred in correct runs. Exact 516 gets greater operational weight than the broader `518n − 2` ladder. A natural response can also land on 516, and a tool-selection response can be short without being defective. Counts identify suspicious execution behavior; they do not name a replacement model. A positive reasoning count also cannot distinguish a flagship reasoning model from a smaller reasoning model.

[NickalasLight's analysis repository](https://github.com/NickalasLight/codex-reasoning-bug-512-token/tree/aaa5995d5ebcd8dabc64c95dcc32a3350183e357) supplies scripts and before/after evidence. Its [Reddit follow-up](https://www.reddit.com/r/codex/comments/1upxyjl/psa_for_anyone_that_thinks_they_have_solved_the/) explains that improving the candy puzzle did not establish improved mean reasoning on ordinary workloads. This is a reason to measure representative tasks alongside a trigger puzzle, while retaining the passive warning itself.

### Model Guard's rule

The native app-server's `thread/tokenUsage/updated` notification includes thread, turn, cumulative usage and the last response's reasoning count. Model Guard observes this existing stream; no periodic challenge requests are added. The [release's protocol](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/thread.rs) and [core usage handling](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/session/mod.rs) also explain why repeated snapshots and context recomputations must not be counted as new responses.

| Observation | Display / treatment |
|---|---|
| Completed response reports a valid reasoning count | Show `last reasoning Nt`, including a reported zero |
| Exact 516 under `high`, `xhigh`, `max` or `ultra` | Amber `516 WATCH`, retained for the turn even if a later response has another count |
| At least 3 exact-516 hits among the last 5 valid response observations at those efforts | Red `REASONING SUSPECT`, with the numerator and denominator |
| Exact 516 at lower or unknown effort | Show and count it; no automatic 516 warning |
| Higher `518n − 2` values | Count as ladder hits in JSON; no 516 alert from these alone |
| Missing or invalid reasoning field | Show `?`; never synthesize 516 or infer a model |

The 3-of-5 threshold is a product heuristic. It has no claimed false-positive probability and is not evidence that three answers were wrong. `samples` counts up to 20 valid response observations, including zero; `recent_samples` counts up to five. These are model responses, including tool rounds, rather than user turns. `turn_516` retains intermediate hits, which should not be confused with the count of the final answer.

The observer accepts a sample only when cumulative token usage advances by `last.totalTokens`. Repeated snapshots do not advance the count; an initial historical snapshot establishes a watermark. Stale lower totals are ignored; accepted rollback operations reestablish the watermark. Thread/turn mismatches are rejected. Model, provider, requested effort and service tier define the measurement bucket; account changes clear it and quarantine an in-flight response until a new turn. Consequently this conservative counter can omit an observation after interrupted coverage. It is not a billing ledger.

`check --json` exports these fields under `reasoning`, with `evidence: "heuristic"`. Its existing route exit codes retain their meaning: a disclosed match may coexist with `reasoning.alert: "suspect"`. A monitor failure or disclosed mismatch takes visual priority. No prompt injection, forced continuation, model selection or retry is triggered by this feature.

### Local reproduction

A metadata-only audit of 50 session files in the 2026-09-08 and 2026-09-09 date directories counted `token_usage_record` entries, deduplicated by response ID across files. The source records' requested labels produced the following aggregate:

| Requested label | Effort | Responses | Exact 516 | Exact 1034 | Exact 1552 |
|---|---|---:|---:|---:|---:|
| gpt-6-astra | high | 964 | 101 (10.48%) | 34 | 15 |
| gpt-6-astra | max | 1,224 | 127 (10.38%) | 42 | 10 |

The [aggregate artifact](research/reasoning-counts-20260909.json) contains no account identity, session ID, path or conversation text. Its [standalone reader](research/reasoning_counts.py) accepts explicitly supplied files or directories and reads each active file only through its initial size:

```sh
python3 research/reasoning_counts.py /explicit/path/to/session/date/directory
```

These natural workloads contain different tasks and tool rounds, without correctness annotations or independent backend ground truth. The percentages measure exact-516 incidence, **not substitution rates**. They establish that the signal exists under current requested labels and is worth exposing; they do not validate a GPT-5.5-specific causal explanation for GPT-6.

A subsequent separate live probe through the unchanged official login, model `gpt-6-astra`, effort `max`, reported 29 reasoning tokens and one counted response. Effective model disclosure remained absent. The integration tests also drive the real official binary through SSE and WebSocket fixtures with `[516, 0, 516, 2000, 516]`, verifying three hits, five observations and an independent routing verdict. Fixture data demonstrates the detector's plumbing, while the session aggregate demonstrates the real phenomenon.

## Statistical fingerprints with practical potential

The relevant question is whether an endpoint's behavior is consistent with a reference under an understood measurement protocol. A detector can answer that probabilistically without observing server weights. Closed-set ranking, verification against one claimed model, and change detection against yesterday's endpoint are different experiments and require different validation.

### KBF: knowledge-boundary probes

[KBF](https://arxiv.org/abs/2605.29524), revised July 2026, uses stable numerical recall near a model's knowledge boundary, including repeatable wrong values. It reports detecting 155 economically relevant substitutions across 16 production endpoints.[^kbf] The [paper's operational limitations](https://arxiv.org/html/2605.29524v2#S4.SS7) explicitly limit the result to statistical inconsistency, note small control counts, and acknowledge correlated probes in its binomial model.

The [released code and 16 probe sets](https://github.com/Ooo0ption/KBF/tree/481c78da14df4f2b02b43d344dae7199ae08cea0) support a self-calibrated binomial test with a conservative reference-error bound. They include GPT-5.4 and GPT-4.1 mini/nano, but no GPT-6 Astra or GPT-4o reference. The author also reports four successful agent-interface controls, including Codex, in [Appendix C](https://arxiv.org/html/2605.29524v2#A3). This makes KBF a strong candidate for an active Codex audit after enrollment of the intended model; the published GPT-5.4 baseline must not be relabeled GPT-6.

Engineering assessment: prefer private, freshly generated probes and independently held-out repetitions. A local Codex baseline can detect later change, but its initial model label still needs a trusted reference. This audit inspected the scoring code and reference inventory; it did not reproduce the paper's 155-endpoint-pair experiment.

### PAMELA and Verify LLM API

[One Token Is Enough](https://arxiv.org/html/2607.10252v1) studies repeated single-token distributions across 165 models and 40 task/language cells. It reports verification AUC 0.971 and equal-error rate 7.3%; the cross-provider AUC is lower at 0.880. Family classification is a separate, weaker result at 59.5%.[^pamela] These measurements support useful statistical verification and also show why an in-library nearest label is not sufficient validation.

[Verify LLM API](https://github.com/udtu/verifyllmapi/tree/6f84113c49d503793f0aca69964cfad516121577) packages a direct Codex runner. It uses independent ephemeral executions with reasoning `none`, compares against an OpenRouter-derived reference and exposes the actual distance. The author's [20-sample Codex acceptance run](https://verifyllmapi.com/blog/verify-llm-api-skill-test/) correctly ended inconclusive for an unenrolled GPT-5.6 Sol label. The quick threshold has about 11.8% equal-error rate on the data used for selection/calibration, not an independent holdout; wrapper and reasoning differences remain confounders.

This is a working sampling approach for Codex, with finite cost and explicit uncertainty. An Astra/max status band would need its own protocol-matched references and validation before assigning a model name. An active probe's result also applies to those probe requests, not retrospectively to every request in the terminal.

### fpverify: sequential monitoring

[fpverify](https://github.com/Mohamed7415/fpverify/tree/bcd60d955c92efdc6419a628f10de07a6d123ee5) provides sequential betting tests, a budget, early stopping, reference enrollment, and unknown-candidate handling. Its bundled nine-model library was collected through Cursor with an entire ten-question battery. Its [protocol measurements](https://github.com/Mohamed7415/fpverify/blob/bcd60d955c92efdc6419a628f10de07a6d123ee5/experiments/frontier/PROTOCOL.md) show the same model's preferred coin side or number can reverse between a battery and an isolated question. That is direct evidence that protocol matching matters.

The [calibration code](https://github.com/Mohamed7415/fpverify/blob/bcd60d955c92efdc6419a628f10de07a6d123ee5/fpverify/calibrate.py) is more qualified than the README's blanket 1% guarantee: finite-reference uncertainty and benign drift are handled by posterior-predictive simulation. The exact betting guarantee requires an appropriate null distribution; it does not establish a 1% operational false-alarm rate for arbitrary Codex deployments. Its [red-team evaluation](https://github.com/Mohamed7415/fpverify/blob/bcd60d955c92efdc6419a628f10de07a6d123ee5/experiments/run_evaluation.py) uses simulated endpoints. Adopt the sequential design and explicit abstention after measuring real matched references; do not import its confidence claims unchanged.

### Other implementations

| Source | Concrete method | Assessment for Codex |
|---|---|---|
| [LLMmap, USENIX Security 2025](https://www.usenix.org/conference/usenixsecurity25/presentation/pasquini) | Reports over 95% identification across 42 versions with eight interactions; learned fingerprints | Strong original evidence for few-query identification within its evaluated population; newer models need reference/training updates |
| [RouteLens](https://github.com/AI45Lab/RouteLens/tree/b6bbaff753999320c28f170513793473ab0bad29) | Adaptive probe selection, total variation distances, permutation tests, stored endpoint baselines | Useful enrollment and observability design; its [final confidence calculation](https://github.com/AI45Lab/RouteLens/blob/b6bbaff753999320c28f170513793473ab0bad29/apps/proxy/src/fingerprint/enhanced-audit.ts) is a score combination, not a calibrated posterior of model identity |
| [BazaarLink probe-engine](https://github.com/Bazaarlinkorg/LLMprobe-engine/tree/5c41136741ca52b5637879cca7bd0cae07404646) | Short-choice distributions; absolute-fit and abstention gates for sibling-model clusters | More careful than forced nearest-label classification; public V3H bias references inspected here contain GPT-5.6 variants but no Astra/4o pair, so the published cluster accuracy does not validate that pair |
| [APIMaster's Astra verifier description](https://apimaster.ai/blog/verify-gpt-6-api-real) | Dated behavioral verification records with ranked candidates | An existing commercial option, but the public feed omits the complete prompt/configuration protocol; no independent calibration reproduced here |
| [codex-skill's routing verifier](https://github.com/Mauriciog87/codex-skill/blob/bcd48d3b8582f8999fb5c7899f782e3d7ccde83a/.agents/skills/sol-luna-orchestration/scripts/codex-app-server-client.mjs) | Verifies accepted `thread/settings/updated` against a selected execution profile | Useful configuration assurance; the inspected `effectiveRouting` value comes from accepted settings, not the effective backend response |

Related original work, [Real Money, Fake Models](https://arxiv.org/abs/2603.01919), measures misleading model claims at shadow APIs.[^shadow] It supports investigating intermediaries with behavioral evidence; its sampled market cannot be used to infer a substitution rate for official ChatGPT-authenticated Codex.

## Continuation proxies and secondary evidence

[CodexCont](https://github.com/neteroster/CodexCont) and [codexcomp](https://github.com/dzshzx/codexcomp) implement a stronger intervention than a warning: detect selected `518n − 2` counts, hold tentative output, preserve encrypted reasoning and request continuation, then combine multiple upstream rounds. They are concrete existing mitigation experiments. They can change latency, token accounting and answer/tool behavior, and their broader ladder rule conflicts with the 516 hook's healthy higher-rung controls. Model Guard adopts passive detection; these proxies have not been installed or represented as a demonstrated general fix.

The [llmsort author's Codex logprobs experiment](https://github.com/XyraSinclair/llmsort/blob/main/docs/LOGPROBS.md) reports access to sampled-token logprobs at reasoning `none`, but no top alternatives on the ChatGPT backend. That can enrich a fingerprint if independently reproduced under the same protocol. It does not reveal a model name, and the result has not been reproduced in this investigation.

`system_fingerprint` is a [backend-configuration fingerprint](https://developers.openai.com/api/reference/resources/chat), not a public model-weight lookup. Capability errors, latency, vocabulary, reasoning-token counts and encrypted-reasoning presence can all supply diagnostics, but none individually resolves a named backend. Client attestation is similarly directional: the client authenticates its execution to the service; it is not server-to-user attestation of the model that generated an answer.

## Active audit design

A useful next active audit should enroll the expected model and plausible substitutes under the same Codex version, harness, effort, service tier and prompt protocol; include unknown-model rejection; then report separately: the quality score, discrepancy from the expected reference, ranked candidates, and the number/time of probe requests. KBF-style stable probes are a promising starting point, while sequential sampling can limit cost.

Validation must include held-out reference runs, known substitutions, benign configuration changes, different task prompts, and mixtures of substituted traffic. Baselines need a date and a refresh policy. Probe selection and threshold fitting must not use the final evaluation split. Independent probes should carry an explicit validity window because a router can treat simple probes differently from an actual coding task.

Until those references and tests exist for the intended Astra deployment, the implemented combination is useful and concrete: immediate disclosed-route monitoring, passive exact-516 warnings, a rolling history and an export that can support comparative quality investigations. It leaves a clear place for an active statistical audit without presenting an uncalibrated candidate score as fact.

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

The separate research paper [One Token Is Enough](https://arxiv.org/abs/2607.10252) reports probabilistic identification/verification from repeated single-token samples; it does not supply an error-free per-turn model oracle. [The candy-eval discussion](https://github.com/router-for-me/CLIProxyAPI/discussions/3937) studies answer quality and repeated reasoning-token counts such as 516, rather than establishing a particular backend identity. Model Guard presents exact-516 observations as a separate heuristic and keeps the strict routing verdict independent. A quality anomaly can warrant investigation without identifying a particular replacement model.

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

## Principal research sources

The sections above link the exact inspected source files and original community reports, pinning repositories where available. The following citations retain authorship and dates for the principal measurements.

[^kbf]: Yijia Fang, Yiqing Feng, Bingyu Li and Mingxun Zhou. [KBF: Knowledge Boundary as Fingerprint for Language Model and Black-Box API Auditing](https://arxiv.org/abs/2605.29524v2). arXiv, revised 2026-07-25.
[^pamela]: Tomas Bruckner. [One Token Is Enough: Fingerprinting and Verifying Large Language Models from Single-Token Output Distributions](https://arxiv.org/abs/2607.10252). arXiv, 2026-07-11. [Dataset and reproduction archive](https://zenodo.org/records/21278557).
[^shadow]: Yage Zhang, Yukun Jiang, Zeyuan Chen, Michael Backes, Xinyue Shen and Yang Zhang. [Real Money, Fake Models: Deceptive Model Claims in Shadow APIs](https://arxiv.org/abs/2603.01919v2). arXiv, revised 2026-03-05.
[^hook]: bentoner. [codex-516-hook: measurements and implementation](https://github.com/bentoner/codex-516-hook/tree/3729959d72544ef3f9db62b696306b1dbdae04e9). Author measurements dated 2026-07-05; source inspected 2026-09-09.
