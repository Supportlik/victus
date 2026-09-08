"""Per-run budget: tokens, dollars and images (SPEC R40).

The runner charges every model turn; when a limit is crossed the run stops
gracefully with status ``budget_exceeded`` and the remaining days stay locked
until their lock expires (they are picked up by the next run).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from victus.config.server import AgentBudget


@dataclass(slots=True)
class Budget:
    max_input_tokens: int
    max_output_tokens: int
    max_usd: float
    max_images: int
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    images: int = 0
    _reasons: list[str] = field(default_factory=list)

    @classmethod
    def from_config(cls, cfg: AgentBudget) -> Budget:
        return cls(
            max_input_tokens=cfg.max_input_tokens,
            max_output_tokens=cfg.max_output_tokens,
            max_usd=cfg.max_usd_per_run,
            max_images=cfg.max_images_per_run,
        )

    def charge(self, *, input_tokens: int = 0, output_tokens: int = 0, usd: float = 0.0) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.usd += usd

    def take_images(self, wanted: int) -> int:
        """Reserve up to ``wanted`` images; returns how many fit into the budget."""
        room = max(0, self.max_images - self.images)
        taken = min(room, wanted)
        self.images += taken
        return taken

    @property
    def exceeded(self) -> str | None:
        """Why the budget is exhausted, or None while there is room left."""
        if self.input_tokens >= self.max_input_tokens:
            return f"input tokens {self.input_tokens} >= {self.max_input_tokens}"
        if self.output_tokens >= self.max_output_tokens:
            return f"output tokens {self.output_tokens} >= {self.max_output_tokens}"
        if self.usd >= self.max_usd:
            return f"cost {self.usd:.2f} USD >= {self.max_usd:.2f} USD"
        return None

    def snapshot(self) -> dict[str, float | int]:
        return {
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_usd": self.max_usd,
            "max_images": self.max_images,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd": round(self.usd, 4),
            "images": self.images,
        }
