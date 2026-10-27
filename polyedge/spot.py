"""Spot-price fair value for the crypto Up/Down windows.

Polymarket's Up/Down markets settle on a 60-second average, not a point price:
against Binance 1s data, "average of the last 60s before the window's end >=
average of the 60s before its start" matches 98.6% of logged outcomes, a point
price only 90.5%. So in the closing minute part of the settle is already known.

fair_up() models what is still to come as a random walk with volatility from
the last 15 one-minute returns, and maps the z-score through Phi(z / 1.3). The
1.3 was fitted on 30 days of 1s Binance data (Sep 27 - Oct 27, 2026; see
research/twap.py), where it is calibrated to within about half a point for all
four coins.
"""

from __future__ import annotations

import json
import math
import time
import urllib.request
from typing import Callable

SYMBOLS = {"btc": "BTCUSDT", "eth": "ETHUSDT", "sol": "SOLUSDT", "xrp": "XRPUSDT"}
KLINES_URL = "https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval=1s&limit=1000"
AVG_SECS = 60
VOL_MINUTES = 15
Z_SCALE = 1.3


def _get_json(url: str) -> list:
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def fair_up(prices: dict[int, float], window_start: int, window_end: int, now: float) -> float | None:
    """P(Up) from 1s closes keyed by unix second (each close is the price at the end of that second)."""
    last = max(prices)
    if last < now - 10:
        return None  # feed is stale
    def px(t: int) -> float | None:
        for k in range(t, t - 10, -1):  # forward-fill quiet seconds
            if k in prices:
                return prices[k]
        return None
    strike_pts = [px(t) for t in range(window_start - AVG_SECS, window_start)]
    vol_pts = [px(last - 60 * k) for k in range(VOL_MINUTES + 1)]
    if None in strike_pts or None in vol_pts:
        return None
    strike = sum(strike_pts) / AVG_SECS
    rets = [math.log(a / b) for a, b in zip(vol_pts, vol_pts[1:])]
    sig = math.sqrt(sum(r * r for r in rets) / len(rets) / 60)
    p = prices[last]
    left = window_end - 1 - last  # seconds still to come
    if left < 0:
        return None
    if left >= AVG_SECS:
        mu = p - strike
        var = (p * sig) ** 2 * ((left - AVG_SECS) + AVG_SECS / 3)
    else:
        seen = [px(t) for t in range(window_end - AVG_SECS, last + 1)]
        if None in seen:
            return None
        mu = (sum(seen) + left * p) / AVG_SECS - strike
        var = (p * sig) ** 2 * (left / 3) * (left / AVG_SECS) ** 2
    if var <= 0:
        return 1.0 if mu >= 0 else 0.0
    z = mu / math.sqrt(var) / Z_SCALE
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


class SpotFeed:
    """Recent 1s closes per coin from Binance's public market-data API, cached briefly."""

    def __init__(self, fetch: Callable[[str], list] = _get_json, clock: Callable[[], float] = time.time,
                 ttl: float = 2.0) -> None:
        self.fetch, self.clock, self.ttl = fetch, clock, ttl
        self._cache: dict[str, tuple[float, dict[int, float]]] = {}

    def prices(self, coin: str) -> dict[int, float]:
        hit = self._cache.get(coin)
        if hit and self.clock() - hit[0] < self.ttl:
            return hit[1]
        rows = self.fetch(KLINES_URL.format(sym=SYMBOLS[coin]))
        prices = {int(k[0]) // 1000: float(k[4]) for k in rows}
        self._cache[coin] = (self.clock(), prices)
        return prices

    def fair_up(self, coin: str, window_start: int, window_end: int) -> float | None:
        try:
            return fair_up(self.prices(coin), window_start, window_end, self.clock())
        except Exception:
            return None  # no spot view: the caller does not trade
