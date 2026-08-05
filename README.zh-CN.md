<div align="center">

<img src="assets/hero.svg" alt="model-guard 状态栏四种状态" width="880">

# 🚨 model-guard

**抓住 Claude Code 静默降级的状态栏——在它烧掉你的 session 之前。**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Made for Claude Code](https://img.shields.io/badge/made%20for-Claude%20Code-d97757)](https://claude.com/claude-code)
[![Deps](https://img.shields.io/badge/deps-bash%20%2B%20jq-4EAA25)](#安装)
[![Languages](https://img.shields.io/badge/band%20languages-8-8A2BE2)](#配置)

[English](README.md) · 简体中文

</div>

---

## 痛点

session 进行到一半撞上用量限额，Claude Code **静默**回退到更弱的模型——不闪、不响，只是你的结对程序员悄悄变笨了。你接着又聊了一个小时，纳闷代码怎么越写越糙，token 却一直在烧。

这个插件的由来就是这么一次真实事故：在被静默降级的模型上写废了半个 session，才注意到角落里那行小小的模型名。再也不想来第二次。

## 你会得到什么

每个 session 底部一条常驻、整行铺满的彩色横幅。不用去读它——你会**瞥见**它。

| 横幅 | 含义 |
|:---:|---|
| 🟩 `✔` | 模型与本机预期一致 |
| 🟦 `⬆` | 比默认**更强**——仅提示，不报警 |
| 🟥 `🚨` | **静默降级**——整条变红，提醒你 `/model` 切回 |
| 🟦 `●` | 未配置预期——中性展示 |

模型型号只是一半。红色**内嵌警示补丁**负责其余的静默降级：

- ⚡ **思考强度**低于你配置的 `effortLevel`
- 🧠 **扩展思考**被关闭
- ⏳ **5 小时限额窗口 ≥ 80%**——强制回退的前兆，在降级发生*之前*就预警

外加日常实用信息：当前模型与思考强度、上下文用量、当前登录账号（多账号切换党懂的）。

## 安装

```
/plugin marketplace add ventusff/claude-model-guard
/plugin install model-guard@claude-model-guard
/model-guard:setup
```

最后一步是**交互式**的——方向键选两个问题就完事。它会拷贝脚本、写配置、把 `statusLine` 合并进 `~/.claude/settings.json`（先做带时间戳的备份）。不需要从 README 复制粘贴任何命令。

<div align="center"><img src="assets/setup.svg" alt="交互式安装" width="880"></div>

> **为什么还要 setup 这一步？** Claude Code 插件目前无法自行注册主状态栏（插件的 `settings.json` 只支持 `agent` 和 `subagentStatusLine` 两个键）。`setup` 是唯一逃不掉的一步——而且有 session 启动提示兜底：没跑 setup 会提醒你，插件更新带来新脚本也会提醒你刷新。

**依赖：** bash 4+ 和 [`jq`](https://jqlang.github.io/jq/)。就这些——一个脚本，没有守护进程，不联网。

## 「降级」是怎么判定的

**预期模型**——命中即止：

1. `~/.claude/model-guard.conf` 的 `EXPECTED_MODEL`（`grep -Ei` pattern，手动覆盖）
2. `~/.claude/statusline-expected-model`（旧版覆盖文件）
3. `~/.claude/settings.json` 里钉住的 `model`（`opus[1m]` → `opus`；`default` 视为无预期）

**强度序：** `fable/mythos > opus > sonnet > haiku`。

- 实际模型**低于**预期 → 🟥 整行报警。
- **同档但型号不同** → 依然 🟥。无法证明它不更弱，就不猜——保守是设计原则。
- 实际**高于**预期 → 🟦 冷静的蓝色。白捡的升级不算急事。

## 配置

全部配置在 `~/.claude/model-guard.conf`（由 `setup` 创建，也可手改）：

| 键 | 默认 | 作用 |
|---|---|---|
| `LANGUAGE` | `auto` | 横幅语言。`auto` 跟随 Claude Code 的 `language` 设置，否则英文。可选：`en` `zh` `ja` `ko` `es` `fr` `de` `pt` |
| `SHOW_ACCOUNT` | `true` | 显示当前登录账号邮箱（实时读 `~/.claude.json`，换号自动跟随） |
| `SHOW_CONTEXT` | `true` | 显示上下文用量，如 `◔ 13%` |
| `LIMIT_WARN_AT` | `80` | 5 小时限额用量达到 N% 时红色补丁预警。`off` 关闭 |
| `EXPECTED_MODEL` | *(自动)* | 手动指定预期模型 pattern，如 `opus\|fable` |

随时重跑 `/model-guard:setup` 交互式改配置。

## 设计细节

<details>
<summary><b>为什么用 truecolor 而不是普通 ANSI 颜色？</b></summary>

终端主题会重映射 16 个基础 ANSI 颜色——「红底」可能被渲染成粉底，对比度恰好在你最需要报警醒目的时候塌掉。model-guard 输出 **truecolor** 转义序列（`COLORTERM` 不支持时回退到固定 256 色立方），完全绕过主题调色板。

三对前景/背景色均按 WCAG 对比度 ≥ 7:1（AAA）选定：

| 状态 | 颜色 | 对比度 |
|---|---|---|
| OK | `#000000` on `#3FB950` | 8.3 : 1 |
| ALARM | `#FFFFFF` on `#B00020` | 7.3 : 1 |
| INFO | `#FFFFFF` on `#0D47A1` | 8.6 : 1 |

不用闪烁（SGR 5）——跨终端渲染不可控。

</details>

<details>
<summary><b>横幅怎么做到任意终端宽度都整行铺满？</b></summary>

脚本在输出尾部垫约 300 个空格（报警态则是一串 🚨），超出终端宽度的部分被 TUI 截掉，所以色带永远铺满整行——不需要探测宽度。

</details>

<details>
<summary><b><code>setup</code> 到底动了什么？</b></summary>

- 拷贝状态栏脚本到 `~/.claude/model-guard.sh`
- 把你的选择写进 `~/.claude/model-guard.conf`
- 向 `~/.claude/settings.json` 合并一个 `statusLine` 块——先做带时间戳的备份，不碰其他任何键
- 如果你之前有别的状态栏，会被保存下来，**卸载时自动还原**

</details>

## 卸载

```
/model-guard:remove
```

注销状态栏（还原你之前的配置）、可选删除脚本和配置文件、保留 settings 备份。之后可在 `/plugin` 里移除插件本体。

## License

[MIT](LICENSE) © [ventusff](https://github.com/ventusff)
