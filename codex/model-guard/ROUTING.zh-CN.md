# Codex 路由检查：调研与实测

核实时间：2026-09-09。机器：nomad-u。官方 Codex 0.153.4，源码提交 `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`。[完整英文技术说明](ROUTING.md)。

## 结论

**有可行的辅助检测办法。1.5 版已经接入恰好 516 个推理 token 的被动监测和告警，统计指纹也能在缺少模型响应头时检查行为是否偏离基线。**逐请求准确指出未披露的 GPT-4o 身份仍未解决，但这不妨碍先把有用的异常信号显示出来。

服务端重路由确实有公开案例：[Codex #11189](https://github.com/openai/codex/issues/11189) 中有请求 5.3-Codex、收到 5.2 标识的复现及 OpenAI 维护者回应。但它不能证明当前存在统一的 GPT-4o 回退。

## 516：可以立即采用的被动信号

#30364 原始报告分析了 390,195 条 token-count 记录，发现 GPT-5.5 标签下的 516 峰值明显偏高。[作者的 Reddit 说明](https://www.reddit.com/r/codex/comments/1ujqo09/the_gpt55_516_reasoning_tokens_issue_is_not/)同时明确：统计异常本身尚未证明截断。[GitHub issue](https://github.com/openai/codex/issues/30364) 在本次检查时已关闭；关闭状态本身不说明原因，也不能证明所有服务部署已经恢复。

现成实现是 [bentoner/codex-516-hook](https://github.com/bentoner/codex-516-hook/tree/3729959d72544ef3f9db62b696306b1dbdae04e9)，通过 Stop 钩子读取已完成响应的推理用量并警告。作者报告：某个触发谜题在 Codex 订阅认证和 API-key 认证下各有 18/20 次命中 516，而直接调用 Responses API 为 0/20；另一个较难谜题的 6 次 516 响应中有 5 次答错。样本较小、任务特定，但足以支持把这个信号用于实用提示。[^hook]

同一项目也记录了重要的对照：1034／1552／2070／… 会出现在正确回答中。因此，**恰好 516 应比整个 `518n − 2` 序列获得更高告警权重**。自然结束也可能恰好落在 516；选工具的中间响应短，也不必然有错。推理 token 为正同样不能区分旗舰推理模型与较小的推理模型。

[NickalasLight 的分析仓库](https://github.com/NickalasLight/codex-reasoning-bug-512-token/tree/aaa5995d5ebcd8dabc64c95dcc32a3350183e357)提供用量统计脚本和前后对照资料。[后续 Reddit 帖](https://www.reddit.com/r/codex/comments/1upxyjl/psa_for_anyone_that_thinks_they_have_solved_the/)指出，糖果题改善并没有证明普通工作负载的平均推理改善。合理的做法是保留被动提示，同时用有代表性的真实任务评估任何修复。

### Model Guard 的实现规则

官方 `thread/tokenUsage/updated` 已提供 thread、turn、累计用量及上次响应的推理计数。插件直接观察现有消息，不定时额外发题。[该版本协议](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/thread.rs)与[核心用量逻辑](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/session/mod.rs)还说明，重复用量快照、上下文重算都不能当成新响应。

| 观察结果 | 显示或处理 |
|---|---|
| 完成的响应有合法推理计数 | 显示「上次推理 Nt」，包括回报的 0 |
| `high`／`xhigh`／`max`／`ultra` 下恰好 516 | 黄色「516 命中」；本轮后面有正常响应，也保留中间命中提示 |
| 上述强度下，最近 5 次有效观测至少 3 次命中 516 | 红色「疑似推理受限」，直接显示命中数／观测数 |
| 较低或未知强度下的 516 | 保留计数，不自动告警 |
| 更高的 `518n − 2` 档位 | JSON 记录 ladder_hits，不单独触发 516 告警 |
| 推理字段缺失或无效 | 显示 `?`，不补造计数或模型名 |

3/5 是产品层面的启发式阈值，没有声称经过误报率标定，也不意味着三次回答都错了。`samples` 包括 0，覆盖最多 20 次有效响应用量观测；`recent_samples` 最多为 5。单位是一次模型响应，包含工具调用中间轮次，不是用户发言次数。`turn_516` 保留本轮中间命中，不能把它误读为最终答案的推理计数。

只有累计 token 相比上次增加的量等于 `last.totalTokens` 时，才计入一次新响应。重复和乱序旧快照会忽略；附着历史会话后先建立累计基准，明确接受的回滚会重新建立基准。thread／turn 不符的数据丢弃。按模型、服务商、强度和服务档位区分统计；账号变更时清空，并隔离尚在执行的旧请求。因此监测中断后的某次响应可能被保守略过，这个计数器不用于对账。

`check --json` 在 `reasoning` 中导出这些信息，固定标明 `evidence: "heuristic"`。原有路由退出码语义独立：服务端披露一致时仍可能同时出现 `reasoning.alert: "suspect"`。监测中断或已披露的模型不一致具有显示优先级。该功能不向上下文注入提示、不强制续推理、不重试或切换模型。

### 本机复现

对 2026-09-08、2026-09-09 两个会话日期目录的 50 个文件做元数据审计，只计 `token_usage_record`，跨文件按响应 ID 去重，得到下表。模型列均为记录中的请求标签。

| 请求标签 | 强度 | 响应数 | 恰好 516 | 恰好 1034 | 恰好 1552 |
|---|---|---:|---:|---:|---:|
| gpt-6-astra | high | 964 | 101（10.48%） | 34 | 15 |
| gpt-6-astra | max | 1,224 | 127（10.38%） | 42 | 10 |

[汇总结果](research/reasoning-counts-20260909.json)不含账号、会话 ID、路径或对话正文。[独立读取脚本](research/reasoning_counts.py)只接受明确给出的文件或目录；对仍在写入的文件，读取范围限制在打开时的大小：

```sh
python3 research/reasoning_counts.py /明确指定的会话日期目录
```

这批自然工作负载混合了不同任务和工具轮次，没有逐题正确性标注，也没有独立的底层模型真值。比例表示 516 的出现率，**不是换模型的比例**。它验证了当前请求标签下确实存在该信号，值得显示；不能据此把 GPT-5.5 的因果解释直接套到 GPT-6。

随后通过原有官方登录、`gpt-6-astra / max` 发出的一次独立探针，成功读到 29 个推理 token、计数 1 次，仍未收到有效模型披露。自动化测试则让真实官方二进制经过 SSE、WebSocket 假服务端接收 `[516, 0, 516, 2000, 516]`，验证三次命中、五次观测和独立的路由结论。假服务端证明检测链路正确，本机会话汇总证明实际存在这个现象。

## 有实际潜力的统计指纹

统计检测可以检查端点行为是否与已知基线一致，不需要先看见服务端权重。候选库内分类、验证某个声明模型、检查同一端点相较昨天是否变化，是不同实验，不能共用未经验证的置信度解释。

### KBF：知识边界探针

[KBF](https://arxiv.org/abs/2605.29524) 的 2026 年 7 月修订版利用模型对冷门数值的稳定回忆，包括重复出现的错误值。论文报告在 16 个生产端点上检测出 155 组经济上有意义的替换。[^kbf][局限一节](https://arxiv.org/html/2605.29524v2#S4.SS7)明确把结论限定为统计不一致，并指出同模型对照数量有限、题目相关性会影响二项检验。

[源码与 16 套参考题](https://github.com/Ooo0ption/KBF/tree/481c78da14df4f2b02b43d344dae7199ae08cea0)提供自校准检验和保守的参考误差上界，包含 GPT-5.4、GPT-4.1 mini/nano，没有 GPT-6 Astra 或 GPT-4o 参考。[附录 C](https://arxiv.org/html/2605.29524v2#A3)还报告包括 Codex 在内的四项 agent 界面对照通过。这使它成为建立目标模型基线后值得采用的主动审计方案；GPT-5.4 题库不能直接改名为 GPT-6。

工程判断：使用新生成的私有题，并保留独立验证样本。自行建立的 Codex 基线能检测未来变化，但其最初的模型标签仍需要可信参照。本次核查了评分源码与题库清单，没有重跑论文全部 155 组实验。

### PAMELA 与 Verify LLM API

[One Token Is Enough](https://arxiv.org/html/2607.10252v1)研究 165 个模型、40 个任务／语言组合的单 token 分布，报告验证 AUC 为 0.971、等错误率为 7.3%；跨服务商 AUC 降至 0.880。家族分类是另一项较弱结果，准确率为 59.5%。[^pamela]这些数字支持统计验证有用，也说明不能只看最近的候选标签。

[Verify LLM API](https://github.com/udtu/verifyllmapi/tree/6f84113c49d503793f0aca69964cfad516121577)已有直接运行 Codex 的采样器：每次使用独立临时会话、思考强度 `none`，与 OpenRouter 来源的参考分布比较。[作者的 20 样本验收](https://verifyllmapi.com/blog/verify-llm-api-skill-test/)对未收录的 GPT-5.6 Sol 正确返回了无结论。快速阈值在用于选题、校准的数据上约有 11.8% 等错误率，并非独立留出验证；harness 和强度差异仍会影响分布。

它是能运行、成本有限、会表达不确定性的 Codex 采样方案。要给 Astra/max 的状态栏附上模型候选，需要补齐相同协议的参考和验证。独立发题得到的结果属于那些探针请求，不能追溯认证终端里所有历史请求。

### fpverify：序贯检测

[fpverify](https://github.com/Mohamed7415/fpverify/tree/bcd60d955c92efdc6419a628f10de07a6d123ee5)实现序贯下注检验、预算限制、提前结束、基线登记和未知候选处理。随附九模型参考来自 Cursor 的十题套卷。[协议实测](https://github.com/Mohamed7415/fpverify/blob/bcd60d955c92efdc6419a628f10de07a6d123ee5/experiments/frontier/PROTOCOL.md)显示，同一个模型在整套题和单独提问下，偏好的硬币面或数字会反转，直接证明了协议对齐的重要性。

其[校准源码](https://github.com/Mohamed7415/fpverify/blob/bcd60d955c92efdc6419a628f10de07a6d123ee5/fpverify/calibrate.py)比 README 的统一「1%」保证更谨慎：用后验预测模拟吸收有限参考样本误差与良性漂移。严格下注保证依赖合适的零假设分布，不能直接保证任意 Codex 部署的实际误报率为 1%。[对抗评估](https://github.com/Mohamed7415/fpverify/blob/bcd60d955c92efdc6419a628f10de07a6d123ee5/experiments/run_evaluation.py)使用模拟端点。序贯设计和主动放弃判定值得采用，置信度数字需要经过实际匹配参考的验证。

### 其他可借鉴的实现

| 来源 | 具体办法 | 对 Codex 的适用性 |
|---|---|---|
| [LLMmap，USENIX Security 2025](https://www.usenix.org/conference/usenixsecurity25/presentation/pasquini) | 学习式指纹，报告八次交互区分 42 个版本、准确率超过 95% | 少量查询识别的强原始证据；新模型需要补参考和训练 |
| [RouteLens](https://github.com/AI45Lab/RouteLens/tree/b6bbaff753999320c28f170513793473ab0bad29) | 自适应选题、总变差距离、置换检验、保存基线 | 基线管理与观测方式可借鉴；[最终 confidence](https://github.com/AI45Lab/RouteLens/blob/b6bbaff753999320c28f170513793473ab0bad29/apps/proxy/src/fingerprint/enhanced-audit.ts)是组合分数，没有完成模型身份概率标定 |
| [BazaarLink probe-engine](https://github.com/Bazaarlinkorg/LLMprobe-engine/tree/5c41136741ca52b5637879cca7bd0cae07404646) | 短选择题分布；绝对拟合下限及放弃判定机制 | 比强制选最近标签更谨慎；本次审计的公开 V3H 偏好参考有 GPT-5.6 系列，没有 Astra/4o 对照，已有簇准确率不能直接迁移 |
| [APIMaster 的 Astra 检测说明](https://apimaster.ai/blog/verify-gpt-6-api-real) | 带时间的行为验证记录和候选排序 | 已有商业方案，但公开数据缺完整题目／配置，未在本次独立复现其标定 |
| [codex-skill 的 routing verifier](https://github.com/Mauriciog87/codex-skill/blob/bcd48d3b8582f8999fb5c7899f782e3d7ccde83a/.agents/skills/sol-luna-orchestration/scripts/codex-app-server-client.mjs) | 核对 `thread/settings/updated` 是否接受指定执行配置 | 配置验证有用；代码中的 effectiveRouting 来自已接受设置，不是响应背后的有效模型 |

[Real Money, Fake Models](https://arxiv.org/abs/2603.01919)测量了 shadow API 的模型声明问题，支持用行为证据调查中间商。[^shadow]其市场样本不能用来估计官方 ChatGPT 登录 Codex 的替换率。

## 续推理代理与其他线索

[CodexCont](https://github.com/neteroster/CodexCont)和 [codexcomp](https://github.com/dzshzx/codexcomp)已有更强干预：检测选定的 `518n − 2` 计数，暂存答案，保留加密推理项、发起续推理，然后把多次上游响应合并。它们是具体可运行的修复实验，但会改变延迟、token 统计及答案／工具行为，其更宽的固定档位规则与 516 钩子的健康高档位对照存在冲突。Model Guard 采用被动检测；本次没有安装这些代理，也没有把它们当成已证明的通用修复。

[llmsort 作者的 Codex logprobs 实验](https://github.com/XyraSinclair/llmsort/blob/main/docs/LOGPROBS.md)报告在 `none` 强度下能读取已采样 token 的概率，但拿不到多个候选 token 的概率。相同协议下独立复现后，它可以丰富指纹；它不直接给出模型名，本次也尚未复现这项能力。

`system_fingerprint` 是[后端配置指纹](https://developers.openai.com/api/reference/resources/chat)，没有公开的模型权重查找表。功能支持情况、错误格式、延迟、用词、推理计数、加密推理项的存在都可以作为诊断线索，但单项不能确定具体模型。客户端 attestation 的方向也不同：是客户端向服务端证明其执行身份，不是服务端向用户证明生成模型。

## 主动审计应如何落地

主动审计应针对相同 Codex 版本、harness、思考强度、服务档位和提问协议，登记目标模型及合理的替代候选，支持拒绝未知模型，分别报告质量分、相对目标基线的偏离、候选排序，以及探针数量和时间。KBF 的稳定题是值得优先尝试的起点，序贯采样可控制开销。

验证集应包含独立留出的同模型样本、已知替换、良性配置变化、不同任务和混合路由。基线记录日期及更新策略；最终验收数据不能同时用于选题和调阈值。独立探针应标明有效范围，因为服务端可能对短探针和真正的编程任务采用不同路由。

目标 Astra 部署的这些参考与验证尚未建立时，当前已经落实的组合仍然有用：即时的已披露路由监测、被动 516 提示、滚动统计及可导出的比较依据。它为主动统计审计保留接口，同时如实区分观测、告警与具体模型身份。

## 最近“疑似 4o”案例的依据

[9 月 5 日原帖](https://linux.do/t/topic/2858863) 已由作者标注原方法有偏差、不再适用。[后续研究](https://linux.do/t/topic/2861622) 仍主要通过 SVG 用词和画面判断，回复中也有反例。[9 月 9 日所谓强力证据](https://linux.do/t/topic/2877589) 则从 Plan Mode 的表现推测模型。这些报告值得作为质量问题线索，但没有提供足以确认 GPT-4o 的服务端模型标识。

不能把“内嵌 SVG”“循环”、短回答、模型自称、知识截止日期或者某道题答错，直接映射成一个实际模型名。

## 社区现成方案

| 方案 | 实际作用 | 本次采用情况 |
|---|---|---|
| [codex-statusline](https://github.com/sh-ai-x/codex-statusline) | 配置官方内置状态项 | 模型选择值不能验证路由 |
| [mullller/codex-hud](https://github.com/mullller/codex-hud) | 通过 tmux 显示状态 | 借鉴显示方式；不用“最新会话文件”判断当前终端 |
| [brandonwie/codex-hud](https://github.com/brandonwie/codex-hud) | 可使用带补丁的原生页脚 | 本插件使用官方二进制 |
| [Every Code](https://github.com/just-every/code) | 从响应正文读取模型，比较并告警 | 它接受任意同前缀后缀；可能漏掉带后缀的异常标识，不沿用此规则 |
| [ModelTrace](https://github.com/xqy2006/ModelTrace) | 三轮数字输出指纹，推测库内候选模型 | 做了源码审计和实测；不作为确定性路由证据 |
| [hlwy-ai-checker](https://github.com/hanlinwenyuan/hlwy-ai-checker) | 与基准渠道比较统计指纹 | 作者也说明不能单独证明实际模型身份 |
| [糖果测试及 516 讨论](https://github.com/router-for-me/CLIProxyAPI/discussions/3937) | 检查推理表现、观察 token 数 | 1.5 已采纳 516 为独立启发式信号；不将其直接映射成模型名 |

ModelTrace 审计版本为 `60949ef522a84f66b1236b459308b48028d36949`。其候选库有 13 个模型，**没有 GPT-4o**；即使输入来自未知模型，它仍会选择一个已有候选。作者明确说明了这个边界。

我们用原版算法、NumPy 2.3.3、该版本的 unified bank 做了离线反例，每种输入三段、每段 310 个整数，全程没有调用模型：

| 输入 | 工具首选候选 | 库内概率 |
|---|---|---|
| Python 均匀伪随机数，种子 20260909 | gpt-6-astra | 87.59% |
| 全部为 42 | claude-opus-4-8 | 58.33% |
| 从 1 数到 310 | gpt-5.4 | 99.94% |

这些输入故意超出正常模型挑战协议，用于验证未知输入的处理；它们不是对正常测试准确率的测量。结果说明，库内概率不能当作“实际用了这个模型”的概率。相关论文 [One Token Is Enough](https://arxiv.org/abs/2607.10252) 也研究统计识别，并未提供无误差的逐轮身份判定。

## 本机实测

1. 默认 WebSocket 连接、请求 `gpt-6-astra`：没有拿到有效模型头或官方路由事件。
2. 单独做 SSE 诊断：响应正文是 `gpt-6-astra`，有效模型头仍缺失。只对该诊断进程设置临时服务商别名及传输选项，没有修改日常配置。
3. 通过官方 Codex 执行三轮 ModelTrace 数字挑战，保留日常 `max` 强度：首选候选为 `gpt-6-astra`，库内概率 99.12%；三轮都没有有效模型披露。这是行为相似结果，不能验证底层权重。

因此，本次没有证实本机被路由到 GPT-4o，也没有足够证据保证不存在隐藏路由。公开记录不包含账号、凭据、会话文本或原始传输日志。

## 插件怎样判定

官方 [PR #12061](https://github.com/openai/codex/pull/12061) 曾专门删除正文 `response.model` 的判断，原因是减少误报、使用正确模型标识。当前版本的有效模型证据来自 `openai-model` / `x-openai-model` 响应头、事件内的模型头，以及由这些字段产生的 `model/rerouted` 和结构化日志。

插件以这些证据为依据：公开标识一致才显示绿色，不同则整条变红并写出两个模型；缺失为黄色，监测断开或过期为红色。新请求清除上一请求的正向确认；本轮发生过不同模型的证据会保留，不因后续日志缺失而假定恢复。子线程不会替换当前终端的模型。

当前官方页脚不能注册外部命令渲染器，因此用独立 tmux 服务显示两行状态，通过本地 Unix socket 连接官方 app-server。只有官方进程连接原服务商；账号从 `account/read` 获取，不读登录文件。中间转发的会话数据只在内存中经过，插件状态文件只保留允许的元数据。

`resume`、`fork`、显式远端、profile 和本地 OSS 模型启动会提示没有监测横幅，并转交官方 CLI：目前的独立 app-server 方案无法完整保留这些启动方式的配置和目录选择语义。已有终端不会被改造。

## 独立检查

```sh
model-guard-codex check --json
model-guard-codex probe --json
```

`check` 检查当前被监测终端，额外模型用量为零；其他终端可用 `--session 路径` 明确指定，程序不会猜测应该检查哪个会话。

`probe` 发起一个独立、临时、只读的请求，消耗服务商用量，使用官方登录机制和当前工作目录配置。可用 `-m 模型 -r 强度` 仅调整探针。它不能替一个已经运行的会话证明路由。

退出码：`0` 服务端公开标识一致，`2` 不一致，`3` 未验证，`4` 监测不可用或探针失败。JSON 可用于留证，不含账号和对话内容；`weights_verified` 始终为 `false`，因为服务端声明仍不等于独立权重证明。

## 主要研究来源

各节同时链接了所审计的具体源码和原始社区报告；可固定版本的仓库链接已固定到提交。以下记录主要测量来源的作者和日期。

[^kbf]: Yijia Fang, Yiqing Feng, Bingyu Li and Mingxun Zhou. [KBF: Knowledge Boundary as Fingerprint for Language Model and Black-Box API Auditing](https://arxiv.org/abs/2605.29524v2). arXiv, revised 2026-07-25.
[^pamela]: Tomas Bruckner. [One Token Is Enough: Fingerprinting and Verifying Large Language Models from Single-Token Output Distributions](https://arxiv.org/abs/2607.10252). arXiv, 2026-07-11. [Dataset and reproduction archive](https://zenodo.org/records/21278557).
[^shadow]: Yage Zhang, Yukun Jiang, Zeyuan Chen, Michael Backes, Xinyue Shen and Yang Zhang. [Real Money, Fake Models: Deceptive Model Claims in Shadow APIs](https://arxiv.org/abs/2603.01919v2). arXiv, revised 2026-03-05.
[^hook]: bentoner. [codex-516-hook: measurements and implementation](https://github.com/bentoner/codex-516-hook/tree/3729959d72544ef3f9db62b696306b1dbdae04e9). Author measurements dated 2026-07-05; source inspected 2026-09-09.
