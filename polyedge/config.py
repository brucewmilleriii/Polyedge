"""Runtime settings, read from POLYEDGE_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else default


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


def _list(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name, "")
    return tuple(s.strip().lower() for s in raw.split(",") if s.strip())


@dataclass(frozen=True)
class Settings:
    # "paper" simulates fills against live order books; "live" sends real orders.
    mode: str = "paper"

    model: str = "claude-opus-5-5"
    effort: str = "medium"
    max_agent_turns: int = 30

    # Hard limits, enforced in code before any order is sent.
    max_order_usd: float = 10.0
    max_market_usd: float = 25.0
    max_total_usd: float = 100.0
    max_daily_loss_usd: float = 25.0
    max_orders_per_run: int = 3
    min_price: float = 0.03
    max_price: float = 0.97
    # Minimum gap between Claude's probability and the price paid, after fees.
    min_edge: float = 0.05
    # Empty means every category is allowed.
    categories: tuple[str, ...] = field(default_factory=tuple)

    paper_starting_cash: float = 500.0
    state_dir: Path = Path("state")
    kill_file: Path = Path("KILL")

    @property
    def live(self) -> bool:
        return self.mode == "live"

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.environ.get("POLYEDGE_MODE", "paper").strip().lower()
        if mode not in ("paper", "live"):
            raise ValueError(f"POLYEDGE_MODE must be 'paper' or 'live', got {mode!r}")
        return cls(
            mode=mode,
            model=os.environ.get("POLYEDGE_MODEL", cls.model),
            effort=os.environ.get("POLYEDGE_EFFORT", cls.effort),
            max_agent_turns=_int("POLYEDGE_MAX_AGENT_TURNS", cls.max_agent_turns),
            max_order_usd=_float("POLYEDGE_MAX_ORDER_USD", cls.max_order_usd),
            max_market_usd=_float("POLYEDGE_MAX_MARKET_USD", cls.max_market_usd),
            max_total_usd=_float("POLYEDGE_MAX_TOTAL_USD", cls.max_total_usd),
            max_daily_loss_usd=_float("POLYEDGE_MAX_DAILY_LOSS_USD", cls.max_daily_loss_usd),
            max_orders_per_run=_int("POLYEDGE_MAX_ORDERS_PER_RUN", cls.max_orders_per_run),
            min_price=_float("POLYEDGE_MIN_PRICE", cls.min_price),
            max_price=_float("POLYEDGE_MAX_PRICE", cls.max_price),
            min_edge=_float("POLYEDGE_MIN_EDGE", cls.min_edge),
            categories=_list("POLYEDGE_CATEGORIES"),
            paper_starting_cash=_float("POLYEDGE_PAPER_STARTING_CASH", cls.paper_starting_cash),
            state_dir=Path(os.environ.get("POLYEDGE_STATE_DIR", "state")),
        )

    def kill_switch_on(self) -> bool:
        return self.kill_file.exists() or os.environ.get("POLYEDGE_KILL", "") == "1"
