"""BTC Up/Down closing-minutes strategy. Plain code, no Claude calls.

Polymarket US lists a BTC "Up or Down" market for every 5-minute window
(also 15m, 1h and 1d). Each settles Up if the BRTI price at the window's end is
at or above the price at its start. In the last couple of minutes the side BTC
is currently on is usually priced high. This loop watches the current window
and, inside the final `window_secs`, buys whichever side's best ask is between
`min_price` and `max_price`, then holds to settlement.

    python -m polyedge crypto   # loops for POLYEDGE_CRYPTO_RUN_MINUTES
"""

from __future__ import annotations

import datetime as dt
import time
from typing import Any, Callable

from polyedge.brokers import OrderRequest
from polyedge.config import Settings
from polyedge.journal import Journal
from polyedge.market_data import MarketData, side_book, taker_fee_per_contract
from polyedge.risk import RiskManager

HORIZON_SECS = {"5m": 300, "15m": 900, "1h": 3600}


def market_slug(asset: str, horizon: str, window_start: dt.datetime) -> str:
    """e.g. cpc-btc-updown-5m-2026-10-27-0335z for the window starting 03:35 UTC."""
    return f"cpc-{asset}-updown-{horizon}-{window_start:%Y-%m-%d-%H%M}z"


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


def pick_side(raw_book: dict[str, Any], min_price: float, max_price: float) -> tuple[str, float] | None:
    """The side ("yes" = Up, "no" = Down) whose best ask is in [min_price, max_price]."""
    for side in ("yes", "no"):
        ask = side_book(raw_book, side).best_ask
        if ask is not None and min_price <= ask <= max_price:
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
    ) -> None:
        self.s = settings
        self.md = md
        self.broker = broker
        self.risk = risk
        self.journal = journal
        self.clock = clock
        self.sleep = sleep
        self.done: set[str] = set()  # markets already traded or skipped for good
        self.trades: list[dict[str, Any]] = []
        self._last_halt = ""

    def step(self) -> None:
        """Check each horizon's current window once."""
        now = self.clock()
        for horizon in self.s.crypto_horizons:
            start, end = current_window(horizon, now)
            slug = market_slug(self.s.crypto_asset, horizon, start)
            if slug in self.done:
                continue
            secs_left = end.timestamp() - now
            if not self.s.crypto_min_secs_left < secs_left <= self.s.crypto_window_secs:
                continue
            self.try_trade(slug, end)

    def try_trade(self, slug: str, expected_end: dt.datetime) -> dict[str, Any] | None:
        s = self.s
        try:
            market = self.md.market(slug)
        except Exception as e:
            self.journal.log("crypto_skip", slug=slug, reason=f"could not load market: {e}")
            self.done.add(slug)
            return None
        if not market or market.get("closed") or not market.get("active", True):
            self.done.add(slug)
            return None
        secs_left = window_end(market, expected_end).timestamp() - self.clock()
        if secs_left <= s.crypto_min_secs_left:
            self.done.add(slug)
            return None
        if any(p.slug == slug for p in self.broker.positions()):
            self.done.add(slug)
            return None

        pick = pick_side(self.md.book(slug), s.crypto_min_price, s.crypto_max_price)
        if pick is None:
            return None  # keep watching this window; the price may still cross the threshold
        side, ask = pick

        halt = self.risk.halted()
        if not halt.ok:
            if halt.reason != self._last_halt:
                self.journal.log("halted", reason=halt.reason)
                self._last_halt = halt.reason
            return None

        contracts = int(s.crypto_max_order_usd // ask)
        notional = ask * contracts
        fee = taker_fee_per_contract(ask) * contracts
        exposure = sum(p.cost for p in self.broker.positions()) + self.broker.pending_buy_notional()
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
            secs_left=round(secs_left, 1), strategy_note="closing-minutes favorite",
        )
        self.done.add(slug)
        try:
            result = self.broker.place(req)
        except Exception as e:
            self.journal.log("order_error", slug=slug, error=str(e))
            return None
        self.journal.log("order_result", slug=slug, **result)
        if result.get("resting") and result.get("order_id"):
            # Only take what is on offer now; never leave a bid behind near the close.
            self.sleep(s.crypto_cancel_after_secs)
            try:
                self.broker.cancel(result["order_id"], slug)
                self.journal.log("order_cancelled", slug=slug, order_id=result["order_id"])
            except Exception as e:
                self.journal.log("cancel_error", slug=slug, order_id=result["order_id"], error=str(e))
        trade = {"slug": slug, "side": side, "price": ask, "contracts": contracts, **result}
        self.trades.append(trade)
        print(f"{dt.datetime.now(dt.timezone.utc):%H:%M:%S} bought {side} {slug} @ {ask} x{contracts}: {result}")
        return trade

    def run(self, minutes: float) -> list[dict[str, Any]]:
        until = self.clock() + minutes * 60
        last_sync = 0.0
        while self.clock() < until:
            try:
                self.step()
                if self.clock() - last_sync > 60:
                    for e in self.broker.sync():
                        self.journal.log("sync", event=e)
                    last_sync = self.clock()
            except Exception as e:  # keep the loop alive through API hiccups
                self.journal.log("crypto_error", error=str(e))
            self.sleep(self.s.crypto_poll_secs)
        for e in self.broker.sync():
            self.journal.log("sync", event=e)
        return self.trades
