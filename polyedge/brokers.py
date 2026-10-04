"""Paper and live brokers behind one interface.

Both brokers take orders as (slug, action, side, price, contracts) where
`price` is what one contract of `side` costs. The live broker converts that to
the YES-terms price and order intent the Polymarket US API expects.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from polyedge.market_data import MarketData, side_book, taker_fee_per_contract, to_yes_price


@dataclass
class OrderRequest:
    slug: str
    action: str  # "buy" or "sell"
    side: str  # "yes" or "no"
    price: float  # price per contract of `side`
    contracts: int


@dataclass
class Position:
    slug: str
    side: str
    qty: float
    cost: float  # total cost basis including fees

    @property
    def avg_price(self) -> float:
        return self.cost / self.qty if self.qty else 0.0


INTENTS = {
    ("buy", "yes"): "ORDER_INTENT_BUY_LONG",
    ("sell", "yes"): "ORDER_INTENT_SELL_LONG",
    ("buy", "no"): "ORDER_INTENT_BUY_SHORT",
    ("sell", "no"): "ORDER_INTENT_SELL_SHORT",
}


class PaperBroker:
    """Simulates fills against the live order book and keeps a local ledger."""

    def __init__(self, md: MarketData, state_dir: Path, starting_cash: float) -> None:
        self.md = md
        self.path = state_dir / "paper.json"
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
        else:
            self.state = {"cash": starting_cash, "realized_pnl": 0.0, "positions": {}, "orders": []}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=2, sort_keys=True))

    # -- reads ---------------------------------------------------------------

    def cash(self) -> float:
        """Cash available for new orders (excludes cash reserved by resting buys)."""
        reserved = sum(o["price"] * o["contracts"] for o in self.state["orders"] if o["action"] == "buy")
        return self.state["cash"] - reserved

    def total_cash(self) -> float:
        return self.state["cash"]

    def pending_buy_notional(self, slug: str | None = None) -> float:
        return sum(
            o["price"] * o["contracts"]
            for o in self.state["orders"]
            if o["action"] == "buy" and (slug is None or o["slug"] == slug)
        )

    def positions(self) -> list[Position]:
        out = []
        for key, p in self.state["positions"].items():
            slug, side = key.rsplit("|", 1)
            if p["qty"] > 0:
                out.append(Position(slug, side, p["qty"], p["cost"]))
        return out

    def open_orders(self) -> list[dict[str, Any]]:
        return list(self.state["orders"])

    # -- writes --------------------------------------------------------------

    def place(self, req: OrderRequest) -> dict[str, Any]:
        book = side_book(self.md.book(req.slug), req.side)
        if req.action == "buy":
            filled, spent = self._take(book.asks, req.price, req.contracts, buying=True)
            if filled:
                self._add_position(req.slug, req.side, filled, spent)
                self.state["cash"] -= spent
        else:
            held = self._held(req.slug, req.side)
            if req.contracts > held:
                raise ValueError(f"cannot sell {req.contracts}, only {held} held")
            filled, proceeds = self._take(book.bids, req.price, req.contracts, buying=False)
            if filled:
                self._reduce_position(req.slug, req.side, filled, proceeds)
                self.state["cash"] += proceeds

        remaining = req.contracts - filled
        order_id = None
        if remaining > 0:
            order_id = f"paper-{uuid.uuid4().hex[:10]}"
            self.state["orders"].append({**asdict(req), "contracts": remaining, "id": order_id, "created": time.time()})
        self.save()
        return {"order_id": order_id, "filled": filled, "resting": remaining, "paper": True}

    def cancel(self, order_id: str, slug: str) -> None:
        self.state["orders"] = [o for o in self.state["orders"] if o["id"] != order_id]
        self.save()

    def sync(self) -> list[str]:
        """Fill resting orders the market has crossed and settle closed markets."""
        events: list[str] = []
        still_open = []
        for o in self.state["orders"]:
            try:
                book = side_book(self.md.book(o["slug"]), o["side"])
            except Exception:
                still_open.append(o)
                continue
            # A resting limit fills (as maker, no fee) once the other side reaches it.
            if o["action"] == "buy" and book.best_ask is not None and book.best_ask <= o["price"]:
                self._add_position(o["slug"], o["side"], o["contracts"], o["price"] * o["contracts"])
                self.state["cash"] -= o["price"] * o["contracts"]
                events.append(f"filled resting buy {o['contracts']} {o['side']} {o['slug']} @ {o['price']}")
            elif o["action"] == "sell" and book.best_bid is not None and book.best_bid >= o["price"]:
                qty = min(o["contracts"], self._held(o["slug"], o["side"]))
                if qty:
                    self._reduce_position(o["slug"], o["side"], qty, o["price"] * qty)
                    self.state["cash"] += o["price"] * qty
                    events.append(f"filled resting sell {qty} {o['side']} {o['slug']} @ {o['price']}")
            else:
                still_open.append(o)
        self.state["orders"] = still_open

        for pos in self.positions():
            market = self._safe_market(pos.slug)
            if not market or not market.get("closed"):
                continue
            settle = self.md.settlement(pos.slug)
            if settle is None:
                continue
            payout_per = settle if pos.side == "yes" else 1.0 - settle
            self._reduce_position(pos.slug, pos.side, pos.qty, payout_per * pos.qty)
            self.state["cash"] += payout_per * pos.qty
            self.state["orders"] = [o for o in self.state["orders"] if o["slug"] != pos.slug]
            events.append(f"settled {pos.qty} {pos.side} {pos.slug} at {payout_per:.2f}")
        self.save()
        return events

    # -- helpers -------------------------------------------------------------

    def _take(self, levels, limit: float, qty: int, buying: bool) -> tuple[int, float]:
        filled, money = 0, 0.0
        for lvl in levels:
            if (buying and lvl.price > limit) or (not buying and lvl.price < limit):
                break
            take = int(min(qty - filled, lvl.qty))
            fee = taker_fee_per_contract(lvl.price) * take
            money += lvl.price * take + (fee if buying else -fee)
            filled += take
            if filled >= qty:
                break
        return filled, money

    def _held(self, slug: str, side: str) -> float:
        return self.state["positions"].get(f"{slug}|{side}", {}).get("qty", 0)

    def _add_position(self, slug: str, side: str, qty: float, cost: float) -> None:
        p = self.state["positions"].setdefault(f"{slug}|{side}", {"qty": 0, "cost": 0.0})
        p["qty"] += qty
        p["cost"] += cost

    def _reduce_position(self, slug: str, side: str, qty: float, proceeds: float) -> None:
        key = f"{slug}|{side}"
        p = self.state["positions"][key]
        basis = p["cost"] * qty / p["qty"]
        p["qty"] -= qty
        p["cost"] -= basis
        self.state["realized_pnl"] += proceeds - basis
        if p["qty"] <= 0:
            del self.state["positions"][key]

    def _safe_market(self, slug: str) -> dict[str, Any] | None:
        try:
            return self.md.market(slug)
        except Exception:
            return None


class LiveBroker:
    """Sends real orders to Polymarket US. Requires API keys."""

    def __init__(self, md: MarketData, key_id: str, secret_key: str, client: Any | None = None) -> None:
        if client is None:
            from polymarket_us import PolymarketUS

            client = PolymarketUS(key_id=key_id, secret_key=secret_key)
        self.md = md
        self.client = client

    def _usd_balance(self) -> dict[str, Any]:
        balances = self.client.account.balances().get("balances", [])
        return next((b for b in balances if b.get("currency", "USD") == "USD"), {})

    def cash(self) -> float:
        b = self._usd_balance()
        return float(b.get("buyingPower", b.get("currentBalance", 0.0)))

    def total_cash(self) -> float:
        return float(self._usd_balance().get("currentBalance", 0.0))

    def pending_buy_notional(self, slug: str | None = None) -> float:
        total = 0.0
        for o in self.open_orders():
            if slug is not None and o.get("marketSlug") != slug:
                continue
            intent = o.get("intent", "")
            if intent not in ("ORDER_INTENT_BUY_LONG", "ORDER_INTENT_BUY_SHORT"):
                continue
            yes_px = float((o.get("price") or {}).get("value", 0))
            px = yes_px if intent == "ORDER_INTENT_BUY_LONG" else 1 - yes_px
            total += px * float(o.get("leavesQuantity") or o.get("quantity") or 0)
        return total

    def positions(self) -> list[Position]:
        out = []
        resp = self.client.portfolio.positions()
        for slug, p in (resp.get("positions") or {}).items():
            net = float(p.get("netPositionDecimal") or p.get("netPosition") or 0)
            if net == 0:
                continue
            cost = abs(float((p.get("cost") or {}).get("value", 0)))
            # Positive net is YES (long); negative net is NO (short).
            out.append(Position(slug, "yes" if net > 0 else "no", abs(net), cost))
        return out

    def open_orders(self) -> list[dict[str, Any]]:
        return self.client.orders.list().get("orders", [])

    def place(self, req: OrderRequest) -> dict[str, Any]:
        resp = self.client.orders.create(
            {
                "marketSlug": req.slug,
                "intent": INTENTS[(req.action, req.side)],
                "type": "ORDER_TYPE_LIMIT",
                "price": {"value": f"{to_yes_price(req.side, req.price):.3f}", "currency": "USD"},
                "quantity": req.contracts,
                "tif": "TIME_IN_FORCE_GOOD_TILL_CANCEL",
                "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
            }
        )
        filled = sum(float(e.get("lastShares") or 0) for e in resp.get("executions", []) or [])
        return {"order_id": resp.get("id"), "filled": filled, "resting": req.contracts - filled, "paper": False}

    def cancel(self, order_id: str, slug: str) -> None:
        self.client.orders.cancel(order_id, {"marketSlug": slug})

    def sync(self) -> list[str]:
        return []

    def save(self) -> None:
        pass
