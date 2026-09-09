"""Allowlisted runtime metadata. Conversation text and credentials never enter state."""

from dataclasses import asdict, dataclass, field
import re
import time
import unicodedata

from .reasoning import Reasoning, alert_text, usage_text


MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}\Z")
REPORT = re.compile(
    r"server reported model (\S+) (?:\(matches requested model\)|while requested model was (\S+))\Z"
)


def model_id(value):
    return value if isinstance(value, str) and MODEL.fullmatch(value) else None


def label(value, limit=120):
    """Strip control/format characters, including terminal escapes and bidi controls."""
    if not isinstance(value, str):
        return ""
    return "".join(c for c in value if unicodedata.category(c)[0] != "C")[:limit]


def number(value):
    return value if type(value) in (int, float) and 0 <= value < 10**15 else None


@dataclass
class Thread:
    id: str
    configured: str | None = None
    requested: str | None = None
    provider: str = "unknown"
    effort: str = ""
    tier: str = ""
    turn_id: str | None = None
    running: bool = False
    observed: str | None = None
    source: str | None = None
    observed_at: float | None = None
    mismatch: str | None = None
    mismatch_source: str | None = None
    mismatch_at: float | None = None
    mismatch_requested: str | None = None
    context: int | None = None
    sampling: bool = False
    turn_effort: str = ""
    turn_tier: str = ""
    turn_provider: str = "unknown"
    reasoning: Reasoning = field(default_factory=Reasoning)
    usage_suspended: bool = False
    show_turn_settings: bool = False

    def settings(self, data):
        requested = model_id(data.get("model"))
        if requested:
            self.configured = requested
        if isinstance(data.get("modelProvider"), str):
            self.provider = label(data["modelProvider"], 60)
        effort = data.get("effort", data.get("reasoningEffort"))
        if "effort" in data or "reasoningEffort" in data:
            self.effort = label(effort, 20)
        if "serviceTier" in data:
            self.tier = label(data["serviceTier"], 20)
        if not self.running:
            if self.configured and self.configured != self.requested:
                self.requested = self.configured
                self.observed = self.source = self.observed_at = self.mismatch = None
                self.mismatch_source = self.mismatch_at = None
                self.mismatch_requested = None
            self.show_turn_settings = False
            self.reasoning.activate((self.requested, self.provider, self.effort, self.tier))

    def begin_turn(self, turn_id):
        if self.turn_id != turn_id:
            self.turn_id = turn_id
            self.requested = self.configured or self.requested
            self.observed = self.source = self.observed_at = self.mismatch = None
            self.mismatch_source = self.mismatch_at = None
            self.mismatch_requested = None
            self.sampling = False
            self.turn_effort, self.turn_tier = self.effort, self.tier
            self.turn_provider = self.provider
            self.reasoning.activate(self.reasoning_scope())
            self.reasoning.begin_turn()
            self.usage_suspended = False
            self.show_turn_settings = True
        self.running = True

    def reasoning_scope(self):
        return self.requested, self.turn_provider, self.turn_effort, self.turn_tier

    def observe(self, actual, source, expected=None):
        actual = model_id(actual)
        if actual is None:
            return
        self.observed, self.source, self.observed_at = actual, source, time.time()
        expected = model_id(expected) or self.requested
        if expected and actual.casefold() != expected.casefold():
            self.mismatch = actual
            self.mismatch_source, self.mismatch_at = source, self.observed_at
            self.mismatch_requested = expected


@dataclass
class State:
    threads: dict = field(default_factory=dict)
    selected: str | None = None
    account: dict | None = None
    limits: dict = field(default_factory=dict)
    pending: dict = field(default_factory=dict)
    early_logs: dict = field(default_factory=dict)
    auth_epoch: int = 0
    limits_at: float = 0
    health: str = "starting"
    language: str = "en"
    show_account: bool = True

    def thread(self, tid):
        if not isinstance(tid, str) or len(tid) > 120:
            return None
        if tid not in self.threads:
            # Only threads selected by the TUI are registered; agent notifications cannot
            # change focus or grow this map indefinitely.
            if len(self.threads) >= 32:
                key = next(k for k in self.threads if k != self.selected)
                del self.threads[key]
            self.threads[tid] = Thread(tid)
        return self.threads[tid]

    def client(self, msg):
        method, params = msg.get("method"), msg.get("params") or {}
        if not isinstance(params, dict):
            return
        if method in ("thread/start", "thread/resume", "thread/fork", "thread/rollback", "account/read"):
            rid = msg.get("id")
            if type(rid) in (str, int) and len(self.pending) < 128:
                self.pending[rid] = (method, self.auth_epoch)
        if method in ("turn/start", "thread/settings/update"):
            thread = self.threads.get(params.get("threadId"))
            if thread:
                self.selected = thread.id
        # Do not adopt proposed settings until the server accepts them.

    def server(self, msg):
        rid = msg.get("id")
        pending = self.pending.pop(rid, None) if type(rid) in (str, int) else None
        method = pending[0] if pending else None
        result = msg.get("result")
        if method and isinstance(result, dict):
            if method == "account/read":
                if pending[1] == self.auth_epoch:
                    self.set_account(result.get("account"))
            else:
                thread_data = result.get("thread") or {}
                thread = self.thread(thread_data.get("id"))
                if thread:
                    self.selected = thread.id
                    if method != "thread/start":
                        thread.reasoning.attach()
                    thread.settings(result)
                    self.health = "connected"
        method, params = msg.get("method"), msg.get("params") or {}
        if not isinstance(params, dict):
            return
        if method == "account/updated":
            self.auth_epoch += 1
            self.account = None
            self.limits = {}
            self.reset_reasoning()
            return
        if method == "account/rateLimits/updated":
            # Streaming updates carry no account/turn id and can belong to an
            # in-flight request before login changed. Use account/rateLimits/read.
            return
        thread = self.threads.get(params.get("threadId"))
        if not thread:
            return
        if method == "thread/settings/updated":
            thread.settings(params.get("threadSettings") or {})
        elif method == "turn/started":
            tid = (params.get("turn") or {}).get("id")
            if isinstance(tid, str):
                thread.begin_turn(tid)
                for record in self.early_logs.pop((thread.id, tid), []):
                    self.log(record)
        elif method == "turn/completed":
            if thread.turn_id == (params.get("turn") or {}).get("id"):
                thread.running = thread.sampling = False
        elif method == "model/rerouted":
            if params.get("turnId") == thread.turn_id:
                thread.observe(params.get("toModel"), "model/rerouted", params.get("fromModel"))
        elif method == "thread/tokenUsage/updated":
            if params.get("turnId") != thread.turn_id or not thread.running:
                return
            usage = params.get("tokenUsage") or {}
            window = number(usage.get("modelContextWindow"))
            used = number((usage.get("last") or {}).get("totalTokens"))
            if window and used is not None:
                thread.context = min(100, round(100 * used / window))
            if not thread.usage_suspended:
                thread.reasoning.observe(usage, thread.reasoning_scope())

    def log(self, record):
        """Only consume authenticated child-process tracing, never assistant text."""
        target = record.get("target", "")
        if not isinstance(target, str) or not target.startswith("codex_core::session"):
            return
        spans = record.get("spans") or []
        if isinstance(record.get("span"), dict):
            spans = [*spans, record["span"]]
        fields = {}
        for span in spans:
            if isinstance(span, dict):
                fields.update(span)
        thread = self.threads.get(fields.get("thread_id"))
        # Requiring both identifiers prevents a delayed record or agent response
        # from being attributed to the visible turn.
        if not thread:
            return
        message = (record.get("fields") or {}).get("message")
        if not isinstance(message, str):
            return
        sampling_start = message == "new" and (record.get("span") or {}).get("name") == "try_run_sampling_request"
        match = REPORT.fullmatch(message)
        if not sampling_start and not match:
            return
        if fields.get("turn_id") != thread.turn_id:
            # stdout notifications and stderr records are independent pipes.
            # Retain only allowlisted metadata until the turn/started event lands.
            turn = fields.get("turn_id")
            if isinstance(turn, str) and len(turn) < 120:
                if len(self.early_logs) >= 16:
                    self.early_logs.pop(next(iter(self.early_logs)))
                clean = {"target": target, "fields": {"message": message}, "span": {"name": "try_run_sampling_request" if sampling_start else ""}, "spans": [{k: fields.get(k) for k in ("thread_id", "turn_id", "model")} ]}
                records = self.early_logs.setdefault((thread.id, turn), [])
                records.append(clean)
                del records[:-8]
            return
        if sampling_start:
            thread.sampling = True
            thread.requested = model_id(fields.get("model")) or thread.requested
            thread.observed = thread.source = thread.observed_at = None
            thread.reasoning.activate(thread.reasoning_scope())
            return
        if match:
            expected = match[2] or fields.get("model")
            thread.observe(match[1], "server-model-log", expected)

    def set_account(self, account):
        clean = None
        if isinstance(account, dict):
            kind = account.get("type")
            if kind in ("chatgpt", "apiKey", "amazonBedrock"):
                clean = {"type": kind}
                if kind == "chatgpt":
                    clean.update(email=label(account.get("email")), plan=label(account.get("planType"), 30))
        if clean != self.account:
            self.auth_epoch += 1
            self.limits = {}
            self.reset_reasoning()
        self.account = clean

    def reset_reasoning(self):
        for thread in self.threads.values():
            thread.reasoning.reset()
            # A running response can still belong to the previous login.
            thread.usage_suspended = thread.running

    def set_limits(self, limits):
        if not isinstance(limits, dict):
            return
        self.limits_at = time.time()
        fresh = {}
        for name in ("primary", "secondary"):
            value = limits.get(name)
            if not isinstance(value, dict):
                continue
            used, minutes = number(value.get("usedPercent")), number(value.get("windowDurationMins"))
            if used is not None and minutes:
                fresh[name] = {"used": min(100, used), "minutes": minutes}
        self.limits = fresh

    def snapshot(self):
        thread = self.threads.get(self.selected)
        thread_data = asdict(thread) if thread else None
        if thread_data:
            thread_data["reasoning"] = thread.reasoning.summary()
            if thread.show_turn_settings:
                thread_data.update(provider=thread.turn_provider, effort=thread.turn_effort, tier=thread.turn_tier)
        account = self.account
        # account/read is for the server's OpenAI account. It isn't evidence of the
        # identity billed by an arbitrary custom provider.
        if thread_data and thread_data["provider"] != "openai":
            account = None
        return {
            "schema": 1, "health": self.health, "updated_at": time.time(),
            "thread": thread_data,
            "account": account if self.show_account else None, "account_hidden": not self.show_account,
            "limits": self.limits if account and time.time() - self.limits_at <= 60 else {},
        }


def render(snapshot, language="en", row=None):
    """Return plain content plus a semantic color. Route information always comes first."""
    zh = language == "zh"
    t = snapshot.get("thread") or {}
    actual, wanted = t.get("observed"), t.get("requested") or "?"
    health = snapshot.get("health")
    if health not in ("connected", "starting"):
        return "alarm", ("监测中断" if zh else "MONITOR LOST") + " | " + str(health)
    if t.get("mismatch"):
        color, title = "alarm", "路由变化" if zh else "ROUTE DIFF"
        wanted = t.get("mismatch_requested") or wanted
        route = f"{wanted} → {t['mismatch']}"
        if actual != t["mismatch"]:
            route += (" (本轮曾出现；当前=" if zh else " (earlier this turn; current=") + (actual or "?") + ")"
    elif actual:
        color, title = "ok", "服务端回报" if zh else "SERVER"
        route = actual
    else:
        color, title = "unknown", "路由未验证" if zh else "ROUTE UNVERIFIED"
        route = wanted + " → ?"
    parts = [title + " " + route]
    if actual and not t.get("running"):
        parts[0] += " (上轮)" if zh else " (last turn)"
    signal = t.get("reasoning") or {}
    warning = alert_text(signal, zh)
    if warning and not t.get("mismatch"):
        parts[0] = warning + " | " + parts[0]
        color = "alarm" if signal["alert"] == "suspect" else "unknown"
    effort, tier = t.get("effort"), t.get("tier")
    if effort:
        parts.append(effort + (" / " + tier if tier else ""))
    model_parts = len(parts)
    if t:
        parts.append(usage_text(signal, zh))
    account = snapshot.get("account")
    if account:
        if account["type"] == "chatgpt":
            parts.append((account.get("email") or "ChatGPT") + " · " + account.get("plan", ""))
        else:
            parts.append("API key" if account["type"] == "apiKey" else "Amazon Bedrock")
    elif t and snapshot.get("account_hidden"):
        parts.append(t.get("provider", "?"))
    elif t:
        parts.append(("账号未知" if zh else "account unknown") + " · " + t.get("provider", "?"))
    if t.get("context") is not None:
        parts.append(("上下文 " if zh else "ctx ") + f"{t['context']}%")
    for limit in snapshot.get("limits", {}).values():
        minutes = limit["minutes"]
        window = f"{minutes / 1440:g}d" if minutes >= 1440 else f"{minutes / 60:g}h"
        parts.append(f"{window} {limit['used']:g}% " + ("已用" if zh else "used"))
    if row == 0:
        parts = parts[:model_parts]
    elif row == 1:
        parts = parts[model_parts:] or [("等待会话" if zh else "Waiting for session")]
    return color, " | ".join(label(p, 300) for p in parts)


# Truecolor / xterm-256 pairs each provide at least 7:1 contrast.
COLORS = {
    "ok": ("#000000", "#3FB950", "colour16", "colour77"),
    "alarm": ("#FFFFFF", "#B00020", "colour231", "colour124"),
    "unknown": ("#000000", "#FFB300", "colour16", "colour214"),
}


def fit(text, width):
    result, cells = [], 0
    for char in text:
        size = 0 if unicodedata.combining(char) else (2 if unicodedata.east_asian_width(char) in "WF" else 1)
        if cells + size > width:
            break
        result.append(char)
        cells += size
    return "".join(result) + " " * max(0, width - cells)


def tmux_band(snapshot, language="en", truecolor=True, row=0, width=120):
    color, content = render(snapshot, language, row)
    thread = snapshot.get("thread") or {}
    if row == 0 and color == "alarm" and thread.get("mismatch") and len(content) >= width:
        content = ("本轮路由变化 → " if language == "zh" else "TURN DIFF → ") + thread["mismatch"] + " | req " + (thread.get("mismatch_requested") or thread.get("requested") or "?")
    fg, bg, fg256, bg256 = COLORS[color]
    if not truecolor:
        fg, bg = fg256, bg256
    # tmux formats are executable: '#' must never arrive from runtime metadata.
    # Fullwidth replacement preserves readability without recursive expansion.
    content = content.replace("#", "＃")
    return f"#[fg={fg},bg={bg},bold]" + fit(" " + content, width), f"fg={fg},bg={bg}"
