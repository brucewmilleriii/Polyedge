"""Score the bot's actual live fills with the TWAP spot model at the moment of each order."""
import json, datetime as dt, sys
import numpy as np
sys.path.insert(0, "research")
from twap import dataset, fit, feats, z_twap, W, COINS
from model import sigma_at
fee = lambda p: 0.0695 * p * (1 - p)
models, spot = {}, {}
for c in COINS:
    S, Z, T, Y, sp = dataset(c); models[c] = fit(Z, T, Y); spot[c] = sp
outcomes = {r["slug"]: r["outcome"] for r in map(json.loads, open("state/crypto/markets.jsonl"))}
reqs, filled = {}, {}
for e in map(json.loads, open("state/crypto/journal.jsonl")):
    if e["kind"] == "order_request": reqs[e["slug"]] = e
    if e["kind"] in ("order_result", "order_status") and float(e.get("filled") or 0) > 0: filled[e["slug"]] = float(e["filled"])
rows = []
for slug, q in filled.items():
    e = reqs[slug]; out = outcomes.get(slug)
    if not out: continue
    coin = "btc" if slug.startswith("cpc-btc") else slug[3:6]
    t0, px, cs = spot[coin]
    ts = int(dt.datetime.fromisoformat(e["ts"]).timestamp())
    end = ts + int(round(e["secs_left"]))
    end = int(round(end / 300) * 300) - t0
    j = ts - t0 - 1
    if j >= len(px): continue
    sig = sigma_at(px, np.array([j]))[0]
    z, _ = z_twap(cs, px, end - W, end, j, sig)
    pf = models[coin].predict_proba(feats(np.array([z]), np.array([end - 1 - j])))[0, 1]
    side = "up" if e["side"] == "yes" else "down"
    pm = pf if (z >= 0) == (side == "up") else 1 - pf
    won = out == side; p = e["price"]
    rows.append((pm, won, p, slug, e["secs_left"]))
rows.sort()
for pm, won, p, slug, sl in rows:
    print(f"model {pm:.4f}  ask {p:.2f}  {'WON ' if won else 'LOST'}  {sl:6.1f}s  {slug}")
for thr in (0, 0.9, 0.95, 0.97, 0.98, 0.99, 0.995):
    k = [r for r in rows if r[0] >= thr]
    pnl = sum((1 - r[2] if r[1] else -r[2]) - fee(r[2]) for r in k)
    print(f"model>={thr}: n={len(k)} won={sum(r[1] for r in k)} pnl per contract {pnl:+.2f}")
