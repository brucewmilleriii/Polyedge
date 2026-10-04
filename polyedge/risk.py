"""Hard trading limits. Every order passes through `RiskManager.check`.

These rules live in code, not in Claude's prompt, so a bad model decision can
lose at most what the limits allow.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any

from polyedge.brokers import OrderRequest, Position
from polyedge.config import Settings
from polyedge.market_data import MarketData, side_book, taker_fee_per_contract


@dataclass
class Decision:
    ok: bool
    reason: str = ""


def mark_value(positions: list[Position], md: MarketData) -> float:
    """Value positions at the best bid for their side (what you could sell for now)."""
    total = 0.0
    for p in positions:
        try:
            bid = side_book(md.book(p.slug), p.side).best_bid
        except Exception:
            bid = None
        total += (bid if bid is not None else p.avg_price) * p.qty
    return total


class RiskManager:
    def __init__(self, settings: Settings, broker: Any, md: MarketData) -> None:
        self.s = settings
        self.broker = broker
        self.md = md
        self.orders_this_run = 0
        self.path = settings.state_dir / "risk.json"

    # -- daily loss tracking ---------------------------------------------------

    def equity(self) -> float:
        return self.broker.total_cash() + mark_value(self.broker.positions(), self.md)

    def start_of_day_equity(self, equity_now: float) -> float:
        """Return today's opening equity, recording it on the first run of the day."""
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        state = json.loads(self.path.read_text()) if self.path.exists() else {}
        if state.get("day") != today:
            state = {"day": today, "start_equity": equity_now}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(state, indent=2))
        return float(state["start_equity"])

    def halted(self) -> Decision:
        if self.s.kill_switch_on():
            return Decision(False, "kill switch is on")
        eq = self.equity()
        start = self.start_of_day_equity(eq)
        if start - eq >= self.s.max_daily_loss_usd:
            return Decision(False, f"daily loss limit hit (down ${start - eq:.2f} today)")
        return Decision(True)

    # -- per-order checks --------------------------------------------------------

    def check(self, req: OrderRequest, probability: float | None) -> Decision:
        s = self.s
        if req.action not in ("buy", "sell") or req.side not in ("yes", "no"):
            return Decision(False, "action must be buy/sell and side must be yes/no")
        if not isinstance(req.contracts, int) or req.contracts < 1:
            return Decision(False, "contracts must be a positive whole number")
        if self.orders_this_run >= s.max_orders_per_run:
            return Decision(False, f"already placed {s.max_orders_per_run} orders this run")

        try:
            market = self.md.market(req.slug)
        except Exception as e:
            return Decision(False, f"could not load market {req.slug}: {e}")
        if not market or market.get("closed") or not market.get("active", True):
            return Decision(False, "market is not open")

        held = {(p.slug, p.side): p for p in self.broker.positions()}

        if req.action == "sell":
            pos = held.get((req.slug, req.side))
            if not pos or pos.qty < req.contracts:
                return Decision(False, "can only sell contracts you hold")
            if not 0.0 < req.price < 1.0:
                return Decision(False, "price must be between 0 and 1")
            return Decision(True)

        # Buys: every limit applies.
        halt = self.halted()
        if not halt.ok:
            return halt
        if s.categories and (market.get("category") or "").lower() not in s.categories:
            return Decision(False, f"category {market.get('category')!r} is not in the allowlist")
        if not s.min_price <= req.price <= s.max_price:
            return Decision(False, f"price must be between {s.min_price} and {s.max_price}")
        other = "no" if req.side == "yes" else "yes"
        if (req.slug, other) in held:
            return Decision(False, f"already holding {other.upper()} in this market")

        notional = req.price * req.contracts
        fees = taker_fee_per_contract(req.price) * req.contracts
        if notional > s.max_order_usd:
            return Decision(False, f"order is ${notional:.2f}, max per order is ${s.max_order_usd:.2f}")

        market_exposure = sum(p.cost for p in held.values() if p.slug == req.slug)
        market_exposure += self.broker.pending_buy_notional(req.slug)
        if market_exposure + notional > s.max_market_usd:
            return Decision(
                False,
                f"would put ${market_exposure + notional:.2f} in this market, max is ${s.max_market_usd:.2f}",
            )

        total_exposure = sum(p.cost for p in held.values()) + self.broker.pending_buy_notional()
        if total_exposure + notional > s.max_total_usd:
            return Decision(
                False,
                f"would bring total exposure to ${total_exposure + notional:.2f}, max is ${s.max_total_usd:.2f}",
            )

        if notional + fees > self.broker.cash():
            return Decision(False, "not enough cash")

        if probability is None or not 0.0 <= probability <= 1.0:
            return Decision(False, "a probability estimate between 0 and 1 is required for buys")
        edge = probability - req.price - taker_fee_per_contract(req.price)
        if edge < s.min_edge:
            return Decision(
                False,
                f"edge after fees is {edge:.3f}, below the {s.min_edge:.3f} minimum",
            )
        return Decision(True)

    def record_order(self) -> None:
        self.orders_this_run += 1
