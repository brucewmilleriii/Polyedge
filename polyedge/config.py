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
    max_order_usd: float = 5.0
    max_market_usd: float = 10.0
    max_total_usd: float = 50.0
    max_daily_loss_usd: float = 100.0
    max_weekly_loss_usd: float = 100.0
    # Percentage caps from the PolyEdge prompt; the stricter of these and the
    # dollar caps applies.
    max_market_pct: float = 0.05
    max_cluster_pct: float = 0.15
    kelly_multiplier: float = 0.25
    # Pull Claude's probability this far toward the market mid before sizing
    # (0 = trust the market, 1 = trust Claude fully).
    shrink: float = 0.5
    max_orders_per_run: int = 3
    # Entry-price floor: longshots below this are where the crowd overpays.
    min_price: float = 0.15
    # Below the floor, a buy needs at least this much edge on the shrunk estimate.
    longshot_min_edge: float = 0.15
    # Nothing is bought above this: near-certain contracts risk a lot to win a little.
    max_price: float = 0.85

    # "favorite" strategy: quick-resolving heavy favorites, tracked separately.
    # Off by default; it buys at 0.90+, above the max_price ceiling.
    fav_enabled: bool = False
    fav_min_price: float = 0.90
    fav_max_hours: float = 48.0
    fav_min_edge: float = 0.02
    fav_min_depth_usd: float = 500.0
    fav_max_order_usd: float = 5.0
    fav_max_orders_per_run: int = 2
    fav_max_total_usd: float = 30.0
    # "crypto_updown": in the last crypto_window_secs of each crypto Up/Down window,
    # buy the side priced between crypto_min_price and crypto_max_price and hold.
    crypto_assets: tuple[str, ...] = ("btc", "eth", "sol", "xrp")
    crypto_horizons: tuple[str, ...] = ("5m",)
    crypto_min_price: float = 0.85
    crypto_max_price: float = 0.97
    crypto_max_order_usd: float = 10.0
    crypto_window_secs: float = 120.0
    crypto_min_secs_left: float = 5.0
    crypto_poll_secs: float = 2.0
    crypto_cancel_after_secs: float = 3.0
    crypto_run_minutes: float = 345.0
    # Minimum gap between Claude's probability and the price paid, after fees.
    min_edge: float = 0.05
    # Empty means every category is allowed.
    categories: tuple[str, ...] = field(default_factory=tuple)

    paper_starting_cash: float = 200.0
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
            max_weekly_loss_usd=_float("POLYEDGE_MAX_WEEKLY_LOSS_USD", cls.max_weekly_loss_usd),
            max_market_pct=_float("POLYEDGE_MAX_MARKET_PCT", cls.max_market_pct),
            max_cluster_pct=_float("POLYEDGE_MAX_CLUSTER_PCT", cls.max_cluster_pct),
            kelly_multiplier=_float("POLYEDGE_KELLY_MULTIPLIER", cls.kelly_multiplier),
            shrink=_float("POLYEDGE_SHRINK", cls.shrink),
            fav_enabled=os.environ.get("POLYEDGE_FAV_ENABLED", "") == "1",
            fav_min_price=_float("POLYEDGE_FAV_MIN_PRICE", cls.fav_min_price),
            longshot_min_edge=_float("POLYEDGE_LONGSHOT_MIN_EDGE", cls.longshot_min_edge),
            fav_max_hours=_float("POLYEDGE_FAV_MAX_HOURS", cls.fav_max_hours),
            fav_min_edge=_float("POLYEDGE_FAV_MIN_EDGE", cls.fav_min_edge),
            fav_max_orders_per_run=_int("POLYEDGE_FAV_MAX_ORDERS_PER_RUN", cls.fav_max_orders_per_run),
            fav_min_depth_usd=_float("POLYEDGE_FAV_MIN_DEPTH_USD", cls.fav_min_depth_usd),
            fav_max_order_usd=_float("POLYEDGE_FAV_MAX_ORDER_USD", cls.fav_max_order_usd),
            fav_max_total_usd=_float("POLYEDGE_FAV_MAX_TOTAL_USD", cls.fav_max_total_usd),
            max_orders_per_run=_int("POLYEDGE_MAX_ORDERS_PER_RUN", cls.max_orders_per_run),
            min_price=_float("POLYEDGE_MIN_PRICE", cls.min_price),
            max_price=_float("POLYEDGE_MAX_PRICE", cls.max_price),
            min_edge=_float("POLYEDGE_MIN_EDGE", cls.min_edge),
            categories=_list("POLYEDGE_CATEGORIES"),
            crypto_assets=_list("POLYEDGE_CRYPTO_ASSETS") or cls.crypto_assets,
            crypto_horizons=_list("POLYEDGE_CRYPTO_HORIZONS") or cls.crypto_horizons,
            crypto_min_price=_float("POLYEDGE_CRYPTO_MIN_PRICE", cls.crypto_min_price),
            crypto_max_price=_float("POLYEDGE_CRYPTO_MAX_PRICE", cls.crypto_max_price),
            crypto_max_order_usd=_float("POLYEDGE_CRYPTO_MAX_ORDER_USD", cls.crypto_max_order_usd),
            crypto_window_secs=_float("POLYEDGE_CRYPTO_WINDOW_SECS", cls.crypto_window_secs),
            crypto_min_secs_left=_float("POLYEDGE_CRYPTO_MIN_SECS_LEFT", cls.crypto_min_secs_left),
            crypto_poll_secs=_float("POLYEDGE_CRYPTO_POLL_SECS", cls.crypto_poll_secs),
            crypto_run_minutes=_float("POLYEDGE_CRYPTO_RUN_MINUTES", cls.crypto_run_minutes),
            paper_starting_cash=_float("POLYEDGE_PAPER_STARTING_CASH", cls.paper_starting_cash),
            state_dir=Path(os.environ.get("POLYEDGE_STATE_DIR", "state")),
        )

    def kill_switch_on(self) -> bool:
        return self.kill_file.exists() or os.environ.get("POLYEDGE_KILL", "") == "1"
