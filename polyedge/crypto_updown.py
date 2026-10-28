"""Crypto Up/Down closing-minutes strategy. Plain code, no Claude calls.

Polymarket US lists "Up or Down" markets for BTC, ETH, SOL and XRP for every
5-minute window (also 15m, 1h and 1d). Each settles Up if the BRTI price at the window's end is
at or above the price at its start. In the last couple of minutes the side BTC
is currently on is usually priced high. This loop watches the current window
and, inside the final `window_secs`, buys whichever side's best ask is between
`min_price` and `max_price`, then holds to settlement. With the spot gate on
(`crypto_min_fair` > 0) it buys only when the spot-price fair value of that side
(polyedge/spot.py) is at least `crypto_min_fair` and above the ask plus fee.

Every watched market, traded or not, is also recorded to markets.jsonl with
its prices at fixed points before the close and how it settled, so the
thresholds can be checked against real outcomes.

    python -m polyedge crypto   # loops for POLYEDGE_CRYPTO_RUN_MINUTES
"""

from __future__ import annotations

import datetime as dt
import json
import time
from typing import Any, Callable

from polyedge.brokers import OrderRequest
from polyedge.config import Settings
from polyedge.journal import Journal
from polyedge.market_data import MarketData, side_book, taker_fee_per_contract
from polyedge.risk import RiskManager
from polyedge.spot import SpotFeed

HORIZON_SECS = {"5m": 300, "15m": 900, "1h": 3600}
# Seconds before the close at which each watched market's prices are recorded.
CHECKPOINTS = (120, 90, 60, 30, 15, 5)


def market_slug(asset: str, horizon: str, window_start: dt.datetime) -> str:
    """e.g. cpc-btc-updown-5m-2026-10-27-0335z, or cpceth-eth-updown-5m-... for other coins."""
    prefix = "cpc" if asset == "btc" else f"cpc{asset}"
    return f"{prefix}-{asset}-updown-{horizon}-{window_start:%Y-%m-%d-%H%M}z"


def current_window(horizon: str, now: float) -> tuple[dt.datetime, dt.datetime]:
    secs = HORIZON_SECS[horizon]
    start = int(now // secs) * secs
    to_dt = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc)
    return to_dt(start), to_dt(start + secs)


def window_end(market: dict[str, Any], fallback: dt.datetime) -> dt.datetime:
    raw = (market.get("assetPriceTerms") or {}).get("windowEnd")
    if not raw:
        return fallback
    return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))


def pick_side(
    raw_book: dict[str, Any], min_price: float, max_price: float, max_other_ask: float = 1.0
) -> tuple[str, float] | None:
    """The side ("yes" = Up, "no" = Down) whose best ask is in [min_price, max_price].

    The other side must be cheap too (its ask at most max_other_ask, or no offers at
    all): when both sides are offered high the book is just wide quotes, not a favorite.
    """
    for side, other in (("yes", "no"), ("no", "yes")):
        ask = side_book(raw_book, side).best_ask
        other_ask = side_book(raw_book, other).best_ask
        if ask is None or not min_price <= ask <= max_price:
            continue
        if other_ask is not None and other_ask > max_other_ask:
            continue
        return side, ask
    return None


class CryptoTrader:
    def __init__(
        self,
        settings: Settings,
        md: MarketData,
        broker: Any,
        risk: RiskManager,
        journal: Journal,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        spot: Any | None = None,
    ) -> None:
        self.s = settings
        self.md = md
        self.broker = broker
        self.risk = risk
        self.journal = journal
        self.clock = clock
        self.sleep = sleep
        self.spot = spot if spot is not None else SpotFeed(clock=clock)
        self.done: set[str] = set()  # markets already traded or skipped for good
        self.trades: list[dict[str, Any]] = []
        # slug -> {"asset", "end", "snaps", "side"} until its outcome is recorded.
        self.watch: dict[str, dict[str, Any]] = {}
        self.markets_path = settings.state_dir / "markets.jsonl"
        # Markets this loop has ordered in. The exposure cap counts only these, so
        # positions bought by hand in the same account do not block the bot.
        self.own_slugs = self._load_own_slugs()
        self._last_halt = ""
        self._markets: dict[str, dict[str, Any]] = {}  # slug -> market, loaded once per window
        self._next_settle_check: dict[str, float] = {}
        # Filled trades until paid out. Settled Up/Down positions drop out of
        # broker.positions() before the payout reaches cash (about 30 min later),
        # so without this both the loss stop and the exposure cap would miss them.
        self.inflight: list[dict[str, Any]] = []
        self.outcomes: dict[str, str | None] = {}  # slug -> "up"/"down" once settled
        self._last_account_log = 0.0

    def inflight_value(self, held: set[str] | None = None) -> tuple[float, float]:
        """(value, cost) of filled trades not shown in broker positions and not yet paid."""
        now = self.clock()
        self.inflight = [t for t in self.inflight if now < t["pay_at"] + 120]
        if held is None:
            held = {p.slug for p in self.broker.positions()}
        value = cost = 0.0
        for t in self.inflight:
            if t["slug"] in held:
                continue
            outcome = self.outcomes.get(t["slug"])
            won = outcome == ("up" if t["side"] == "yes" else "down")
            value += t["qty"] if won else (0.0 if outcome else t["cost"])
            cost += t["cost"]
        return value, cost

    def step(self) -> None:
        """Check each horizon's current window once."""
        now = self.clock()
        for asset in self.s.crypto_assets:
            for horizon in self.s.crypto_horizons:
                start, end = current_window(horizon, now)
                slug = market_slug(asset, horizon, start)
                secs_left = end.timestamp() - now
                if not 0 < secs_left <= max(self.s.crypto_window_secs, CHECKPOINTS[0]):
                    continue
                # One book read per market per step, shared by the snapshot and the trade check.
                try:
                    raw = self.md.book(slug)
                except Exception as e:
                    if "rate limited" in str(e) or "1015" in str(e):
                        raise
                    continue  # this coin has no market for the window; the others still run
                fair = self.spot.fair_up(asset, int(start.timestamp()), int(end.timestamp()))
                self.snapshot(slug, asset, end, secs_left, raw, fair)
                if slug in self.done:
                    continue
                if not self.s.crypto_min_secs_left < secs_left <= self.s.crypto_window_secs:
                    continue
                trade = self.try_trade(slug, end, raw, fair)
                if trade and slug in self.watch:
                    self.watch[slug]["side"] = trade["side"]
        self.record_outcomes()

    def snapshot(
        self, slug: str, asset: str, end: dt.datetime, secs_left: float, raw: dict[str, Any],
        fair_up: float | None = None,
    ) -> None:
        w = self.watch.setdefault(slug, {"asset": asset, "end": end.timestamp(), "snaps": [], "side": None})
        # Only the nearest checkpoint: one seen late is not back-filled with today's prices.
        due = [c for c in CHECKPOINTS if secs_left <= c]
        if not due or min(due) in {s["at"] for s in w["snaps"]}:
            return
        due = [min(due)]
        up, down = side_book(raw, "yes"), side_book(raw, "no")
        for c in due:
            w["snaps"].append(
                {"at": c, "secs_left": round(secs_left, 1), "up_bid": up.best_bid, "up_ask": up.best_ask,
                 "down_ask": down.best_ask, "fair_up": None if fair_up is None else round(fair_up, 4)}
            )

    def record_outcomes(self, give_up_after: float = 900) -> None:
        """Write each watched market to markets.jsonl once it has settled."""
        now = self.clock()
        for slug, w in list(self.watch.items()):
            if now < max(w["end"] + 30, self._next_settle_check.get(slug, 0)):
                continue
            self._next_settle_check[slug] = now + 20
            settle = self.md.settlement(slug)
            if settle is None and now < w["end"] + give_up_after:
                continue
            outcome = None if settle is None else ("up" if settle >= 0.5 else "down")
            self.outcomes[slug] = outcome
            row = {
                "slug": slug, "asset": w["asset"],
                "window_end": dt.datetime.fromtimestamp(w["end"], dt.timezone.utc).isoformat(),
                "outcome": outcome, "traded": w["side"] and ("up" if w["side"] == "yes" else "down"),
                "snaps": sorted(w["snaps"], key=lambda x: -x["at"]),
            }
            self.markets_path.parent.mkdir(parents=True, exist_ok=True)
            with self.markets_path.open("a") as f:
                f.write(json.dumps(row) + "\n")
            del self.watch[slug]
            self._next_settle_check.pop(slug, None)
            self._markets.pop(slug, None)

    def try_trade(
        self, slug: str, expected_end: dt.datetime, raw: dict[str, Any], fair_up: float | None = None
    ) -> dict[str, Any] | None:
        s = self.s
        if slug not in self._markets:
            market = self.md.market(slug)  # an error here is retried on the next step
            if not market or market.get("closed") or not market.get("active", True):
                self.done.add(slug)
                return None
            if any(p.slug == slug for p in self.broker.positions()):
                self.done.add(slug)  # already holding it, e.g. after a restart
                return None
            self._markets[slug] = market
        secs_left = window_end(self._markets[slug], expected_end).timestamp() - self.clock()
        if secs_left <= s.crypto_min_secs_left:
            self.done.add(slug)
            return None

        pick = pick_side(raw, s.crypto_min_price, s.crypto_max_price, s.crypto_max_other_ask)
        if pick is None:
            return None  # keep watching this window; the price may still cross the threshold
        side, ask = pick
        fair = None if fair_up is None else (fair_up if side == "yes" else 1 - fair_up)
        if s.crypto_min_fair > 0 and (
            fair is None or fair < s.crypto_min_fair or fair - ask - taker_fee_per_contract(ask) < s.crypto_min_fair_edge
        ):
            return None  # spot does not back the favorite (yet); keep watching

        held = {p.slug for p in self.broker.positions()}
        pending_value, pending_cost = self.inflight_value(held)
        halt = self.risk.halted(extra=pending_value)
        if not halt.ok:
            if halt.reason != self._last_halt:
                self.journal.log("halted", reason=halt.reason)
                self._last_halt = halt.reason
            return None

        contracts = int(s.crypto_max_order_usd // ask)
        notional = ask * contracts
        fee = taker_fee_per_contract(ask) * contracts
        exposure = (
            sum(p.cost for p in self.broker.positions() if p.slug in self.own_slugs)
            + self.broker.pending_buy_notional(slug)  # the loop's other bids are cancelled within seconds
            + pending_cost
        )
        reason = None
        if contracts < 1:
            reason = f"${s.crypto_max_order_usd:.2f} buys no contracts at {ask}"
        elif exposure + notional > s.max_total_usd:
            reason = f"would bring total exposure to ${exposure + notional:.2f}, max is ${s.max_total_usd:.2f}"
        elif notional + fee > self.broker.cash():
            reason = "not enough cash"
        if reason:
            self.journal.log("crypto_skip", slug=slug, side=side, price=ask, reason=reason)
            self.done.add(slug)
            return None

        req = OrderRequest(
            slug, "buy", side, ask, contracts, category="crypto", strategy="crypto_updown", probability=ask
        )
        self.journal.log(
            "order_request", **{k: v for k, v in vars(req).items()}, approved=True,
            secs_left=round(secs_left, 1), fair=None if fair is None else round(fair, 4),
            strategy_note="closing-minutes favorite",
        )
        self.done.add(slug)
        self.own_slugs.add(slug)
        try:
            result = self.broker.place(req)
        except Exception as e:
            self.journal.log("order_error", slug=slug, error=str(e))
            return None
        self.journal.log("order_result", slug=slug, **result)
        if result.get("resting") and result.get("order_id"):
            # Only take what is on offer now; never leave a bid behind near the close.
            self.sleep(s.crypto_cancel_after_secs)
            if hasattr(self.broker, "order_status"):
                # Fills can arrive after the create call returns; record what actually happened.
                try:
                    status = self.broker.order_status(result["order_id"])
                    self.journal.log("order_status", slug=slug, order_id=result["order_id"], **status)
                    result = {**result, "filled": status["filled"], "resting": status["leaves"],
                              "avg_price": status.get("avg_price")}
                except Exception as e:
                    self.journal.log("status_error", slug=slug, order_id=result["order_id"], error=str(e))
            if result.get("resting"):
                try:
                    self.broker.cancel(result["order_id"], slug)
                    self.journal.log("order_cancelled", slug=slug, order_id=result["order_id"])
                except Exception as e:
                    self.journal.log("cancel_error", slug=slug, order_id=result["order_id"], error=str(e))
        filled = float(result.get("filled") or 0)
        if filled > 0:
            fill_px = ask
            if result.get("avg_price") is not None:
                fill_px = result["avg_price"] if side == "yes" else 1 - result["avg_price"]
            pay_at = self._pay_at(self._markets.get(slug, {}), expected_end)
            self.inflight.append({
                "slug": slug, "side": side, "qty": filled, "pay_at": pay_at,
                "cost": filled * (fill_px + taker_fee_per_contract(fill_px)),
            })
        trade = {"slug": slug, "side": side, "price": ask, "contracts": contracts, **result}
        self.trades.append(trade)
        print(f"{dt.datetime.now(dt.timezone.utc):%H:%M:%S} bought {side} {slug} @ {ask} x{contracts}: {result}")
        return trade

    def _load_own_slugs(self) -> set[str]:
        slugs: set[str] = set()
        path = getattr(self.journal, "path", None)
        if path and path.exists():
            for line in path.read_text().splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("kind") == "order_request" and row.get("strategy") == "crypto_updown":
                    slugs.add(row["slug"])
        return slugs

    @staticmethod
    def _pay_at(market: dict[str, Any], expected_end: dt.datetime) -> float:
        raw = market.get("endDate")
        if raw:
            try:
                return dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
        return window_end(market, expected_end).timestamp() + 1800

    def log_account(self, every: float = 300) -> None:
        """Journal cash and unpaid trades now and then, so payouts can be checked."""
        if self.clock() - self._last_account_log < every:
            return
        self._last_account_log = self.clock()
        value, cost = self.inflight_value()
        self.journal.log(
            "account", cash=round(self.broker.total_cash(), 2), unpaid_value=round(value, 2),
            unpaid_cost=round(cost, 2), unpaid_trades=len(self.inflight),
        )

    def run(self, minutes: float) -> list[dict[str, Any]]:
        until = self.clock() + minutes * 60
        last_sync = 0.0
        while self.clock() < until:
            try:
                self.step()
                self.log_account()
                if self.clock() - last_sync > 60:
                    for e in self.broker.sync():
                        self.journal.log("sync", event=e)
                    last_sync = self.clock()
            except Exception as e:  # keep the loop alive through API hiccups
                msg = str(e)
                limited = "rate limited" in msg or "1015" in msg or "429" in msg
                self.journal.log("crypto_error", error="rate limited" if limited else msg[:500])
                if limited:
                    self.sleep(20)
            self.sleep(self.s.crypto_poll_secs)
        for e in self.broker.sync():
            self.journal.log("sync", event=e)
        self.record_outcomes(give_up_after=0)
        return self.trades
