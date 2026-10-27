"""One-off: print how Polymarket US lists 5-minute crypto Up/Down markets."""
from polymarket_us import PolymarketUS

c = PolymarketUS()
for q in ["ethereum up or down", "eth up or down", "solana up or down", "xrp up or down", "up or down 5m"]:
    r = c.search.query({"query": q, "limit": 20, "status": "active"})
    for ev in r.get("events", [])[:20]:
        ms = ev.get("markets") or []
        print(q, "|", ev.get("slug"), "|", ev.get("title"), "|", [m.get("slug") for m in ms][:2])
