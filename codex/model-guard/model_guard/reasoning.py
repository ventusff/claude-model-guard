"""Passive reasoning-usage signals; these are heuristics, not model identity."""

from dataclasses import dataclass, field
import time


HIGH_EFFORTS = {"high", "xhigh", "max", "ultra"}
WINDOW = 20


def token_count(value):
    return value if type(value) is int and 0 <= value < 10**15 else None


@dataclass
class Reasoning:
    scope: tuple | None = None
    samples: list = field(default_factory=list)
    total: int | None = 0
    last_tokens: int | None = None
    observed_at: float | None = None
    turn_samples: int = 0
    turn_hits: int = 0

    def reset(self):
        # Keep the cumulative watermark: changing settings must not count a
        # replay of the preceding request as the new model's first response.
        self.scope = None
        self.samples.clear()
        self.last_tokens = self.observed_at = None
        self.turn_samples = self.turn_hits = 0

    def begin_turn(self):
        self.turn_samples = self.turn_hits = 0

    def attach(self):
        self.reset()
        self.total = None

    def activate(self, scope):
        if self.scope != scope:
            self.reset()
            self.scope = scope

    def observe(self, usage, scope):
        """Count a new completion only when cumulative usage advances by `last`.

        Public tokenUsage notifications also repeat on rate-limit updates and
        context recomputation. Neither is a new model response. The first
        snapshot of an attached history establishes a watermark only.
        """
        if not isinstance(usage, dict):
            return
        last, cumulative = usage.get("last"), usage.get("total")
        if not isinstance(last, dict) or not isinstance(cumulative, dict):
            return
        total = token_count(cumulative.get("totalTokens"))
        size = token_count(last.get("totalTokens"))
        if total is None or not size or total == self.total:
            return
        previous = self.total
        if previous is not None and total < previous:
            # Out-of-order snapshots aren't evidence of a rollback. Only an
            # accepted lifecycle response may reset this watermark via attach.
            return
        self.total = total
        if previous is None or total - previous != size:
            return
        self.activate(scope)
        tokens = token_count(last.get("reasoningOutputTokens"))
        output = token_count(last.get("outputTokens"))
        self.last_tokens = None
        self.observed_at = time.time()
        if tokens is None or output is None or tokens > output or output > size:
            return
        self.last_tokens = tokens
        self.samples.append(tokens)
        del self.samples[:-WINDOW]
        self.turn_samples += 1
        self.turn_hits += tokens == 516

    def summary(self):
        recent = self.samples[-5:]
        high = self.scope is not None and self.scope[2] in HIGH_EFFORTS
        alert = "none"
        # Product thresholds, not a calibrated false-positive probability.
        if high and len(recent) == 5 and recent.count(516) >= 3:
            alert = "suspect"
        elif high and self.turn_hits:
            alert = "watch"
        return {
            "source": "thread/tokenUsage/updated",
            "evidence": "heuristic",
            "last_tokens": self.last_tokens,
            "observed_at": self.observed_at,
            "effort": self.scope[2] if self.scope else None,
            "window_size": WINDOW,
            "samples": len(self.samples),
            "exact_516": self.samples.count(516),
            "ladder_hits": sum(n >= 516 and (n + 2) % 518 == 0 for n in self.samples),
            "recent_samples": len(recent),
            "recent_516": recent.count(516),
            "turn_samples": self.turn_samples,
            "turn_516": self.turn_hits,
            "alert": alert,
        }


def alert_text(signal, zh=False):
    if signal.get("alert") == "suspect":
        title = "疑似推理受限" if zh else "REASONING SUSPECT"
        return f"{title} · 516 {signal['recent_516']}/{signal['recent_samples']}"
    if signal.get("alert") == "watch":
        return ("516 命中 · 本轮 " if zh else "516 WATCH · turn ") + str(signal["turn_516"])
    return ""


def usage_text(signal, zh=False):
    value = signal.get("last_tokens")
    result = ("上次推理 " if zh else "last reasoning ") + (f"{value}t" if value is not None else "?")
    if signal.get("samples"):
        result += f" · 516 {signal['exact_516']}/{signal['samples']}"
    return result
