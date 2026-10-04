"""Public market data from the Polymarket US gateway (no keys needed).

Polymarket US quotes every order book in YES terms: a YES bid at 0.40 is the
same thing as a NO offer at 0.60. Everything Claude sees from this module is
expressed per side ("yes" or "no") as the price you would pay for that side,
so it never has to do the conversion itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TAKER_FEE_COEF = 0.0695


def taker_fee_per_contract(price: float, coef: float = TAKER_FEE_COEF) -> float:
    """Polymarket US taker fee: coef * p * (1 - p) per contract."""
    return coef * price * (1.0 - price)


def to_yes_price(side: str, price: float) -> float:
    """Convert a price for `side` into the YES-terms price the API expects."""
    return price if side == "yes" else round(1.0 - price, 6)


@dataclass
class Level:
    price: float
    qty: float


@dataclass
class SideBook:
    """Order book for one side of a market, in that side's own prices."""

    bids: list[Level]  # best (highest) first
    asks: list[Level]  # best (lowest) first

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2


def _levels(raw: list[dict[str, Any]] | None) -> list[Level]:
    out = []
    for lvl in raw or []:
        try:
            out.append(Level(float(lvl["px"]["value"]), float(lvl["qty"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def side_book(market_data: dict[str, Any], side: str) -> SideBook:
    """Build the book for `side` from the API's YES-terms book."""
    yes_bids = sorted(_levels(market_data.get("bids")), key=lambda l: -l.price)
    yes_asks = sorted(_levels(market_data.get("offers")), key=lambda l: l.price)
    if side == "yes":
        return SideBook(bids=yes_bids, asks=yes_asks)
    # Selling YES at p is buying NO at 1-p, and vice versa.
    return SideBook(
        bids=[Level(round(1 - l.price, 6), l.qty) for l in yes_asks],
        asks=[Level(round(1 - l.price, 6), l.qty) for l in yes_bids],
    )


class MarketData:
    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            from polymarket_us import PolymarketUS

            client = PolymarketUS()
        self.client = client

    def list_markets(
        self,
        category: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "active": True,
            "closed": False,
        }
        if category:
            params["categories"] = [category]
        markets = self.client.markets.list(params).get("markets", [])
        return [summarize_market(m) for m in markets]

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        events = self.client.search.query({"query": query, "limit": limit, "status": "active"})
        out = []
        for ev in events.get("events", []):
            out.append(
                {
                    "event": ev.get("title") or ev.get("slug"),
                    "markets": [summarize_market(m) for m in ev.get("markets", []) or []],
                }
            )
        return out

    def market(self, slug: str) -> dict[str, Any]:
        return self.client.markets.retrieve_by_slug(slug).get("market", {})

    def book(self, slug: str) -> dict[str, Any]:
        return self.client.markets.book(slug).get("marketData", {})

    def settlement(self, slug: str) -> float | None:
        try:
            return float(self.client.markets.settlement(slug)["settlement"])
        except Exception:
            return None


def summarize_market(m: dict[str, Any]) -> dict[str, Any]:
    """Trim a market object down to what Claude needs to pick candidates."""
    yes_price = None
    for s in m.get("marketSides", []) or []:
        if s.get("long"):
            try:
                yes_price = float(s.get("price"))
            except (TypeError, ValueError):
                pass
    return {
        "slug": m.get("slug"),
        "question": m.get("question") or m.get("title"),
        "category": m.get("category"),
        "end_date": m.get("endDate"),
        "yes_price": yes_price,
        "market_type": m.get("marketType"),
    }
