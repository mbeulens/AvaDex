"""Token accounting across every Ava request a run makes.

Ava's /api/v1/messages returns an Anthropic-style `usage` block per response;
this sums it over the whole agent turn (tool round-trips and compaction calls
included) and remembers which models actually answered — Ava falls back to its
default model when the requested one isn't installed.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0
    models: list[str] = field(default_factory=list)
    last_model: str = ""
    _uncounted: int = 0

    def record(self, response) -> None:
        usage = response.usage or {}
        inp = int(usage.get("input_tokens") or 0)
        out = int(usage.get("output_tokens") or 0)
        self.requests += 1
        self.input_tokens += inp
        self.output_tokens += out
        # Every request carries a system prompt, so 0 input tokens means the
        # server didn't count rather than that the request was free.
        if inp == 0:
            self._uncounted += 1
        if response.model:
            self.last_model = response.model
            if response.model not in self.models:
                self.models.append(response.model)

    @property
    def complete(self) -> bool:
        """True when every request reported real token counts."""
        return self.requests > 0 and self._uncounted == 0

    def as_dict(self) -> dict:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}
