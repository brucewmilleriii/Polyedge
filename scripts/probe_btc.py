"""One-off: print how Polymarket US lists BTC Up/Down markets."""
import json
import time

from polymarket_us import PolymarketUS

c = PolymarketUS()
r = c.search.query({"query": "bitcoin up or down", "limit": 20, "status": "active"})
for ev in r.get("events", [])[:20]:
    ms = ev.get("markets") or []
    print("EVENT", ev.get("slug"), "|", ev.get("title"), "| markets", len(ms), "| series", ev.get("seriesSlug"), ev.get("endDate"))
first = None
for ev in r.get("events", []):
    for m in ev.get("markets") or []:
        first = first or m
if first:
    print("MARKET_KEYS", sorted(first.keys()))
    print("MARKET", json.dumps(first, default=str)[:3000])
    try:
        print("BOOK", json.dumps(c.markets.book(first["slug"]), default=str)[:1500])
    except Exception as e:
        print("BOOK_ERR", e)
ms = c.markets.list({"limit": 50, "active": True, "closed": False, "orderBy": ["endDate"], "orderDirection": "asc", "categories": ["crypto"]}).get("markets", [])
print("CRYPTO_SOONEST", len(ms))
for m in ms[:40]:
    print(" ", m.get("slug"), m.get("endDate"), m.get("startDate"), (m.get("question") or "")[:80], [(s.get("description"), s.get("price"), s.get("long")) for s in m.get("marketSides") or []])
print("NOW", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
