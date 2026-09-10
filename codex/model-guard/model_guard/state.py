"""Allowlisted routing metadata of the visible thread. Conversation text never enters state."""

from dataclasses import asdict, dataclass, field
import re
import time
import unicodedata

from .reasoning import Reasoning


MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}\Z")
REPORT = re.compile(
    r"server reported model (\S+) (?:\(matches requested model\)|while requested model was (\S+))\Z"
)
DISCLOSURE_SOURCES = ("server-model-log", "model/rerouted", "model/routing/updated")
SEPARATORS = "-.:_@"
SIZE_TIERS = {"mini", "nano", "lite", "small", "fast", "flash", "turbo"}


def model_id(value):
    return value if isinstance(value, str) and MODEL.fullmatch(value) else None


def label(value, limit=120):
    """Strip control/format characters, including terminal escapes and bidi controls."""
    if not isinstance(value, str):
        return ""
    return "".join(c for c in value if unicodedata.category(c)[0] != "C")[:limit]


def number(value):
    return value if type(value) in (int, float) and 0 <= value < 10**15 else None


def label_consistent(requested, body_label):
    """Whether a response body's model label describes the requested model.

    Equal identifiers agree, and so does one identifier extending the other at
    a separator (`gpt-6-astra` and `gpt-6-astra-2026-09-01`, or the bare family
    `gpt-6`). A size tier appended to the requested model names a different
    model. Everything else, including another family, differs. The native TUI
    applies the same rule.
    """
    requested, body_label = requested.casefold(), body_label.casefold()
    if requested == body_label:
        return True

    def extension(short, long):
        if long.startswith(short) and len(long) > len(short) and long[len(short)] in SEPARATORS:
            return long[len(short) + 1:]
        return None

    rest = extension(requested, body_label)
    if rest is not None:
        return not SIZE_TIERS.intersection(re.split(f"[{re.escape(SEPARATORS)}]", rest))
    return extension(body_label, requested) is not None


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
    body_label: str | None = None
    label_mismatch: str | None = None
    label_mismatch_requested: str | None = None
    context: int | None = None
    sampling: bool = False
    turn_effort: str = ""
    turn_tier: str = ""
    turn_provider: str = "unknown"
    reasoning: Reasoning = field(default_factory=Reasoning)
    show_turn_settings: bool = False
    native_routing: bool = False

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
                self.forget_evidence()
            self.show_turn_settings = False
            self.reasoning.activate((self.requested, self.provider, self.effort, self.tier))

    def forget_evidence(self):
        self.observed = self.source = self.observed_at = None
        self.mismatch = self.mismatch_source = self.mismatch_at = self.mismatch_requested = None
        self.body_label = self.label_mismatch = self.label_mismatch_requested = None

    def begin_turn(self, turn_id):
        if self.turn_id != turn_id:
            self.turn_id = turn_id
            self.requested = self.configured or self.requested
            self.forget_evidence()
            self.sampling = False
            self.turn_effort, self.turn_tier = self.effort, self.tier
            self.turn_provider = self.provider
            self.reasoning.activate(self.reasoning_scope())
            self.reasoning.begin_turn()
            self.show_turn_settings = True
        self.running = True

    def reasoning_scope(self):
        return self.requested, self.turn_provider, self.turn_effort, self.turn_tier

    def begin_request(self, requested):
        """A new sampling request invalidates the previous request's disclosures."""
        self.requested = model_id(requested) or self.requested
        self.observed = self.source = self.observed_at = None
        self.body_label = None
        self.reasoning.activate(self.reasoning_scope())

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

    def observe_label(self, body_label, expected=None):
        body_label = model_id(body_label)
        if body_label is None:
            return
        self.body_label = body_label
        expected = model_id(expected) or self.requested
        if expected and not label_consistent(expected, body_label):
            self.label_mismatch, self.label_mismatch_requested = body_label, expected


@dataclass
class State:
    threads: dict = field(default_factory=dict)
    selected: str | None = None
    pending: dict = field(default_factory=dict)
    early_logs: dict = field(default_factory=dict)
    health: str = "starting"

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
        if method in ("thread/start", "thread/resume", "thread/fork", "thread/rollback"):
            rid = msg.get("id")
            if type(rid) in (str, int) and len(self.pending) < 128:
                # The TUI also starts hidden feature threads (for example titles).
                # Their model, effort and usage never describe the visible task.
                source = params.get("threadSource")
                self.pending[rid] = (method, source is None or source == "user")
        if method in ("turn/start", "thread/settings/update"):
            thread = self.threads.get(params.get("threadId"))
            if thread:
                self.selected = thread.id
        # Do not adopt proposed settings until the server accepts them.

    def server(self, msg):
        rid = msg.get("id")
        pending = self.pending.pop(rid, None) if type(rid) in (str, int) else None
        result = msg.get("result")
        if pending and isinstance(result, dict):
            method, visible = pending
            thread_data = result.get("thread") or {}
            source = thread_data.get("threadSource")
            if not visible or (source is not None and source != "user"):
                return
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
        elif method == "model/routing/updated":
            if params.get("turnId") != thread.turn_id or not thread.running:
                return
            thread.native_routing = True
            thread.turn_provider = label(params.get("modelProvider"), 60)
            thread.turn_effort = label(params.get("reasoningEffort"), 20)
            thread.turn_tier = label(params.get("serviceTier"), 20)
            thread.begin_request(params.get("requestedModel"))
            thread.observe(params.get("serverModel"), "model/routing/updated", params.get("requestedModel"))
            thread.observe_label(params.get("responseLabel"), params.get("requestedModel"))
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
            thread.reasoning.observe(usage, thread.reasoning_scope())

    def log(self, record):
        """Consume the stock app-server's structured session tracing, never assistant text.

        A native build discloses routing through `model/routing/updated`; these
        records are the fallback for a stock executable.
        """
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
        if not thread or thread.native_routing:
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
                clean = {"target": target, "fields": {"message": message},
                         "span": {"name": "try_run_sampling_request" if sampling_start else ""},
                         "spans": [{k: fields.get(k) for k in ("thread_id", "turn_id", "model")}]}
                records = self.early_logs.setdefault((thread.id, turn), [])
                records.append(clean)
                del records[:-8]
            return
        if sampling_start:
            thread.sampling = True
            thread.begin_request(fields.get("model"))
            return
        if match:
            expected = match[2] or fields.get("model")
            thread.observe(match[1], "server-model-log", expected)

    def snapshot(self):
        thread = self.threads.get(self.selected)
        thread_data = asdict(thread) if thread else None
        if thread_data:
            thread_data["reasoning"] = thread.reasoning.summary()
            if thread.show_turn_settings:
                thread_data.update(provider=thread.turn_provider, effort=thread.turn_effort, tier=thread.turn_tier)
        return {"schema": 2, "health": self.health, "updated_at": time.time(), "thread": thread_data}
