"""Stats for the crypto Up/Down strategy, from state/crypto/.

    python -m polyedge crypto-report

Live trades are scored from journal order_status rows against outcomes in
markets.jsonl. The "what if" table uses every recorded market: at each
checkpoint, would buying the side priced in a band have won?
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from polyedge.market_data import taker_fee_per_contract

BANDS = ((0.85, 0.90), (0.90, 0.95), (0.95, 0.98))


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def live_trades(state_dir: Path) -> list[dict]:
    """One row per filled live order, with its outcome where known."""
    outcomes = {m["slug"]: m["outcome"] for m in _rows(state_dir / "markets.jsonl")}
    requests, trades = {}, []
    for r in _rows(state_dir / "journal.jsonl"):
        if r["kind"] == "order_request":
            requests[r["slug"]] = r
        elif r["kind"] == "order_status" and r.get("filled") and r["slug"] in requests:
            req = requests[r["slug"]]
            side = "up" if req["side"] == "yes" else "down"
            outcome = outcomes.get(r["slug"])
            qty, price = r["filled"], req["price"]
            pnl = None
            if outcome:
                pnl = (qty if outcome == side else 0.0) - qty * (price + taker_fee_per_contract(price))
            trades.append({"slug": r["slug"], "side": side, "price": price, "qty": qty,
                           "secs_left": req.get("secs_left"), "outcome": outcome, "pnl": pnl})
    return trades


def what_if(state_dir: Path, max_other_ask: float = 0.25) -> dict[tuple[int, tuple[float, float]], list[int]]:
    """(checkpoint, band) -> [markets where a side was in the band, how many of those won]."""
    out: dict = defaultdict(lambda: [0, 0])
    for m in _rows(state_dir / "markets.jsonl"):
        if not m.get("outcome"):
            continue
        for s in m["snaps"]:
            for side, ask, other in (("up", s.get("up_ask"), s.get("down_ask")),
                                     ("down", s.get("down_ask"), s.get("up_ask"))):
                if other is not None and other > max_other_ask:
                    continue  # both sides offered high: a wide book, not a favorite
                for band in BANDS:
                    if ask is not None and band[0] <= ask < band[1]:
                        cell = out[(s["at"], band)]
                        cell[0] += 1
                        cell[1] += m["outcome"] == side
    return out


def render(state_dir: Path) -> str:
    lines = ["# Crypto Up/Down report", ""]
    trades = live_trades(state_dir)
    done = [t for t in trades if t["pnl"] is not None]
    wins = sum(t["outcome"] == t["side"] for t in done)
    pnl = sum(t["pnl"] for t in done)
    lines.append(f"Live fills: {len(trades)} ({len(done)} settled, {wins} won, {len(done) - wins} lost). "
                 f"Settled P&L after fees: ${pnl:+.2f}.")
    lines += ["", "| Market | Side | Price | Qty | Secs left | Outcome | P&L |", "|---|---|---|---|---|---|---|"]
    for t in trades[-30:]:
        p = "" if t["pnl"] is None else f"{t['pnl']:+.2f}"
        lines.append(f"| {t['slug']} | {t['side']} | {t['price']} | {t['qty']:g} | {t['secs_left']} | {t['outcome'] or 'open'} | {p} |")
    lines += ["", "## What if: every recorded market", "",
              "Win rate of the side priced in each band at each checkpoint (seconds before close), "
              "skipping wide books where the other side is offered above 0.25. "
              "Break-even is roughly the band's price.", "",
              "| Secs left | " + " | ".join(f"{a:.2f}–{b:.2f}" for a, b in BANDS) + " |",
              "|---|" + "---|" * len(BANDS)]
    table = what_if(state_dir)
    for at in (120, 90, 60, 30, 15, 5):
        cells = []
        for band in BANDS:
            n, w = table.get((at, band), (0, 0))
            cells.append(f"{w}/{n} ({w / n:.0%})" if n else "–")
        lines.append(f"| {at} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
