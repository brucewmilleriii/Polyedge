"""Read-only check of a Polymarket US account, run before switching to live mode.

It confirms the API keys authenticate and previews (never places) a 1-contract
YES order and a 1-contract NO order, so the response shows how the exchange
reads the price on a NO order. Results go to state/live_check.json.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any

from polyedge.brokers import INTENTS
from polyedge.config import Settings
from polyedge.market_data import MarketData, side_book


def _pick_market(md: MarketData) -> tuple[str, Any]:
    """A liquid open market with a YES price between 0.2 and 0.8, so YES and NO prices differ clearly."""
    for offset in range(0, 200, 50):
        for m in md.list_markets(limit=50, offset=offset):
            slug = m.get("slug")
            if not slug or m.get("yes_price") is None or not 0.2 <= m["yes_price"] <= 0.8:
                continue
            raw = md.book(slug)
            yes = side_book(raw, "yes")
            if yes.best_bid and yes.best_ask and yes.best_ask - yes.best_bid <= 0.03:
                return slug, raw
    raise RuntimeError("no suitable market found")


def _preview(client: Any, slug: str, intent: str, yes_terms_price: float) -> dict[str, Any]:
    try:
        resp = client.orders.preview(
            {
                "request": {
                    "marketSlug": slug,
                    "intent": intent,
                    "type": "ORDER_TYPE_LIMIT",
                    "price": {"value": f"{yes_terms_price:.3f}", "currency": "USD"},
                    "quantity": 1,
                    "tif": "TIME_IN_FORCE_GOOD_TILL_CANCEL",
                    "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
                }
            }
        )
        return {"ok": True, "response": resp}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def main() -> None:
    from polymarket_us import PolymarketUS

    settings = Settings.from_env()
    key_id, secret = os.environ.get("POLYMARKET_KEY_ID"), os.environ.get("POLYMARKET_SECRET_KEY")
    out: dict[str, Any] = {"checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    if not key_id or not secret:
        out["auth"] = "POLYMARKET_KEY_ID or POLYMARKET_SECRET_KEY is not set"
        _save(settings, out)
        return

    client = PolymarketUS(key_id=key_id, secret_key=secret)
    try:
        balances = client.account.balances().get("balances", [])
        positions = client.portfolio.positions().get("positions") or {}
        orders = client.orders.list().get("orders", [])
        out["auth"] = "ok"
        out["account"] = {
            "funded": any(float(b.get("currentBalance") or 0) > 0 for b in balances),
            "positions": len(positions),
            "open_orders": len(orders),
        }
    except Exception as e:
        out["auth"] = f"failed: {type(e).__name__}: {e}"
        _save(settings, out)
        return

    md = MarketData()
    slug, raw = _pick_market(md)
    yes, no = side_book(raw, "yes"), side_book(raw, "no")
    out["market"] = {"slug": slug, "yes_bid": yes.best_bid, "yes_ask": yes.best_ask, "no_bid": no.best_bid, "no_ask": no.best_ask}
    # Resting (non-marketable) prices well below the market, so nothing could fill even if previews were orders.
    yes_px = round(max(0.01, yes.best_bid - 0.10), 3)
    no_px = round(max(0.01, no.best_bid - 0.10), 3)
    out["previews"] = {
        "buy_yes": {"sent_yes_terms_price": yes_px, **_preview(client, slug, INTENTS[("buy", "yes")], yes_px)},
        # Polyedge's convention: a NO price p is sent as YES-terms price 1 - p.
        "buy_no_as_yes_terms": {
            "no_price": no_px,
            "sent_yes_terms_price": round(1 - no_px, 3),
            **_preview(client, slug, INTENTS[("buy", "no")], round(1 - no_px, 3)),
        },
        # The alternative reading: the NO price sent as-is.
        "buy_no_as_no_terms": {
            "no_price": no_px,
            "sent_price": no_px,
            **_preview(client, slug, INTENTS[("buy", "no")], no_px),
        },
    }
    _save(settings, out)


def _save(settings: Settings, out: dict[str, Any]) -> None:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(out, indent=2, default=str)
    (settings.state_dir / "live_check.json").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
