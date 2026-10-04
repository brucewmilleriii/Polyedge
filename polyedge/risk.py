"""Hard trading limits. Every order passes through `RiskManager.check`.

These rules live in code, not in Claude's prompt, so a bad model decision can
lose at most what the limits allow. Where the system prompt and the configured
limits disagree, the stricter of the two is enforced here.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any

from polyedge.brokers import OrderRequest, Position
from polyedge.config import Settings
from polyedge.market_data import MarketData, side_book, taker_fee_per_contract

# Minimum edge after fees by stated confidence, from the PolyEdge v2.1 prompt.
CONFIDENCE_MIN_EDGE = {"high": 0.05, "medium": 0.08, "low": 0.12}


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


def kelly_fraction(probability: float, price: float) -> float:
    """Full-Kelly share of bankroll for a contract paying $1 bought at `price`."""
    if price >= 1.0:
        return 0.0
    return max(0.0, (probability - price) / (1.0 - price))


def _parse_time(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


class RiskManager:
    def __init__(self, settings: Settings, broker: Any, md: MarketData) -> None:
        self.s = settings
        self.broker = broker
        self.md = md
        self.orders_this_run = 0
        self.path = settings.state_dir / "risk.json"
        self._event_cache: dict[str, str] = {}

    # -- loss tracking -----------------------------------------------------------

    def equity(self) -> float:
        return self.broker.total_cash() + mark_value(self.broker.positions(), self.md)

    def _period_start(self, key: str, period: str, equity_now: float) -> float:
        state = json.loads(self.path.read_text()) if self.path.exists() else {}
        entry = state.get(key) or {}
        if entry.get("period") != period:
            state[key] = {"period": period, "start_equity": equity_now}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(state, indent=2))
            return equity_now
        return float(entry["start_equity"])

    def start_of_day_equity(self, equity_now: float) -> float:
        """Today's opening equity (UTC), recorded on the first run of the day."""
        today = dt.datetime.now(dt.timezone.utc).date()
        return self._period_start("day", today.isoformat(), equity_now)

    def start_of_week_equity(self, equity_now: float) -> float:
        """This ISO week's opening equity, recorded on the first run of the week."""
        year, week, _ = dt.datetime.now(dt.timezone.utc).date().isocalendar()
        return self._period_start("week", f"{year}-W{week:02d}", equity_now)

    def halted(self) -> Decision:
        if self.s.kill_switch_on():
            return Decision(False, "kill switch is on")
        eq = self.equity()
        day_start = self.start_of_day_equity(eq)
        if day_start - eq >= self.s.max_daily_loss_usd:
            return Decision(False, f"daily loss limit hit (down ${day_start - eq:.2f} today)")
        week_start = self.start_of_week_equity(eq)
        if week_start - eq >= self.s.max_weekly_loss_usd:
            return Decision(False, f"weekly loss limit hit (down ${week_start - eq:.2f} this week)")
        return Decision(True)

    # -- per-order checks --------------------------------------------------------

    def _event_of(self, slug: str) -> str:
        if slug not in self._event_cache:
            try:
                market = self.md.market(slug)
            except Exception:
                market = {"slug": slug}
            self._event_cache[slug] = self.md.event_slug_for({"slug": slug, **market})
        return self._event_cache[slug]

    def check(
        self,
        req: OrderRequest,
        probability: float | None,
        confidence: str = "low",
        thesis_broken: bool = False,
    ) -> Decision:
        s = self.s
        if req.action not in ("buy", "sell") or req.side not in ("yes", "no"):
            return Decision(False, "action must be buy/sell and side must be yes/no")
        if req.strategy not in ("edge", "favorite"):
            return Decision(False, "strategy must be edge or favorite")
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
        self._event_cache[req.slug] = self.md.event_slug_for({"slug": req.slug, **market})

        held = {(p.slug, p.side): p for p in self.broker.positions()}

        if req.action == "sell":
            pos = held.get((req.slug, req.side))
            if not pos or pos.qty < req.contracts:
                return Decision(False, "can only sell contracts you hold")
            if not thesis_broken:
                return Decision(False, "positions are held to resolution unless the thesis is broken")
            if not 0.0 < req.price < 1.0:
                return Decision(False, "price must be between 0 and 1")
            return Decision(True)

        # Buys: every limit applies.
        halt = self.halted()
        if not halt.ok:
            return halt
        if s.categories and (market.get("category") or "").lower() not in s.categories:
            return Decision(False, f"category {market.get('category')!r} is not in the allowlist")
        if req.price > s.max_price:
            return Decision(False, f"price must be at most {s.max_price}")
        other = "no" if req.side == "yes" else "yes"
        if (req.slug, other) in held:
            return Decision(False, f"already holding {other.upper()} in this market")
        if probability is None or not 0.0 <= probability <= 1.0:
            return Decision(False, "a probability estimate between 0 and 1 is required for buys")

        fee = taker_fee_per_contract(req.price)
        notional = req.price * req.contracts
        if notional > s.max_order_usd:
            return Decision(False, f"order is ${notional:.2f}, max per order is ${s.max_order_usd:.2f}")

        book = side_book(self.md.book(req.slug), req.side)
        if req.strategy == "favorite":
            d = self._check_favorite(req, probability, fee, notional, market, book, held)
        else:
            d = self._check_edge(req, probability, confidence, fee, notional, book)
        if not d.ok:
            return d
        return self._check_exposure(req, notional, fee, held)

    def _check_edge(self, req, probability, confidence, fee, notional, book) -> Decision:
        s = self.s
        if req.price < s.min_price:
            return Decision(False, f"price is below the {s.min_price} entry floor for the edge strategy")
        if confidence not in CONFIDENCE_MIN_EDGE:
            return Decision(False, "confidence must be high, medium or low")
        edge = probability - req.price - fee
        min_edge = max(s.min_edge, CONFIDENCE_MIN_EDGE[confidence])
        if edge < min_edge:
            return Decision(
                False,
                f"edge after fees is {edge:.3f}, below the {min_edge:.3f} minimum for {confidence} confidence",
            )
        # Size on a probability pulled toward the market, since the market is usually closer to right.
        mid = book.mid if book.mid is not None else req.price
        p_used = mid + s.shrink * (probability - mid)
        kelly_cap = s.kelly_multiplier * kelly_fraction(p_used, req.price + fee) * self.equity()
        if notional > kelly_cap:
            return Decision(
                False,
                f"order is ${notional:.2f}; {s.kelly_multiplier:.2f}x Kelly on your probability shrunk "
                f"toward the mid ({p_used:.3f}) allows ${kelly_cap:.2f} "
                f"(at most {int(kelly_cap // req.price)} contracts at this price)",
            )
        return Decision(True)

    def _check_favorite(self, req, probability, fee, notional, market, book, held) -> Decision:
        s = self.s
        if req.price < s.fav_min_price:
            return Decision(False, f"favorite strategy needs a price of at least {s.fav_min_price}")
        if probability < req.price + fee:
            return Decision(False, "favorite strategy still needs your probability above price plus fee")
        end = _parse_time(market.get("endDate"))
        if end is None:
            return Decision(False, "market has no end date")
        days = (end - dt.datetime.now(dt.timezone.utc)).total_seconds() / 86400
        if days > s.fav_max_days:
            return Decision(False, f"resolves in {days:.1f} days, favorite strategy allows {s.fav_max_days:g}")
        if book.best_ask is not None:
            depth = sum(l.price * l.qty for l in book.asks if l.price <= book.best_ask + 0.02)
            if depth < s.fav_min_depth_usd:
                return Decision(False, f"only ${depth:.0f} offered near the best ask, need ${s.fav_min_depth_usd:.0f}")
        if notional > s.fav_max_order_usd:
            return Decision(False, f"favorite orders are capped at ${s.fav_max_order_usd:.2f}")
        fav_exposure = sum(p.cost for p in held.values() if p.strategy == "favorite")
        fav_exposure += sum(
            o["price"] * o["contracts"]
            for o in self.broker.open_orders()
            if o.get("strategy") == "favorite" and o.get("action") == "buy"
        )
        if fav_exposure + notional > s.fav_max_total_usd:
            return Decision(False, f"favorite strategy exposure would exceed ${s.fav_max_total_usd:.2f}")
        return Decision(True)

    def _check_exposure(self, req, notional, fee, held) -> Decision:
        s = self.s
        equity = self.equity()
        market_cap = min(s.max_market_usd, s.max_market_pct * equity)
        market_exposure = sum(p.cost for p in held.values() if p.slug == req.slug)
        market_exposure += self.broker.pending_buy_notional(req.slug)
        if market_exposure + notional > market_cap:
            return Decision(
                False,
                f"would put ${market_exposure + notional:.2f} in this market, max is ${market_cap:.2f}",
            )

        event = self._event_of(req.slug)
        cluster_cap = s.max_cluster_pct * equity
        cluster_exposure = sum(p.cost for p in held.values() if self._event_of(p.slug) == event)
        cluster_exposure += sum(
            self.broker.pending_buy_notional(slug)
            for slug in {o.get("slug") or o.get("marketSlug") for o in self.broker.open_orders()}
            if slug and self._event_of(slug) == event
        )
        if cluster_exposure + notional > cluster_cap:
            return Decision(
                False,
                f"would put ${cluster_exposure + notional:.2f} in event {event}, max is ${cluster_cap:.2f}",
            )

        total_exposure = sum(p.cost for p in held.values()) + self.broker.pending_buy_notional()
        if total_exposure + notional > s.max_total_usd:
            return Decision(
                False,
                f"would bring total exposure to ${total_exposure + notional:.2f}, max is ${s.max_total_usd:.2f}",
            )

        if notional + fee * req.contracts > self.broker.cash():
            return Decision(False, "not enough cash")
        return Decision(True)

    def record_order(self) -> None:
        self.orders_this_run += 1
