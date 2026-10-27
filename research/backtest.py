"""Spot-based fair value for 5-min Up/Down windows, and how it compares to Polymarket asks.

python research/backtest.py   (needs research/data/<coin>_1s.npz from fetch_spot.py)
"""
import json, math
from pathlib import Path
import numpy as np

COINS = ("btc", "eth", "sol", "xrp")
W = 300
VOL_LOOKBACK = 900  # seconds of 1s returns used for sigma
fee = lambda p: 0.0695 * p * (1 - p)

def load(coin):
    z = np.load(f"research/data/{coin}_1s.npz")
    ticks = np.cumsum(z["d"])
    return int(z["t0"]), ticks * float(z["tick"])

def windows(coin):
    """Per window: start, strike, final, price path at each second, sigma (per sqrt sec)."""
    t0, px = load(coin)
    lp = np.log(px)
    r = np.diff(lp, prepend=lp[0])
    c2 = np.cumsum(r * r)
    first = ((t0 + VOL_LOOKBACK) // W + 1) * W
    starts = np.arange(first, t0 + len(px) - W, W)
    i = starts - t0
    strike = px[i - 1]                       # price at the window's start
    final = px[i + W - 1]                    # price at its end
    paths = px[i[:, None] + np.arange(W)[None, :]]   # close of each second in the window
    sig = np.sqrt((c2[i - 1] - c2[i - 1 - VOL_LOOKBACK]) / VOL_LOOKBACK)
    return starts, strike, final, paths, sig, (t0, px, c2)

def zscore(price, strike, sig, secs_left):
    return np.log(price / strike) / (np.maximum(sig, 1e-9) * np.sqrt(np.maximum(secs_left, 1)))

if __name__ == "__main__":
    out = {}
    for coin in COINS:
        if not Path(f"research/data/{coin}_1s.npz").exists(): continue
        starts, K, F, P, sig, _ = windows(coin)
        up = F >= K
        print(f"\n== {coin}: {len(starts)} windows, up {up.mean():.3f}")
        for tl in (120, 90, 60, 45, 30, 15):
            p = P[:, W - tl - 1]
            z = zscore(p, K, sig, tl)
            fav_up = z > 0
            win = np.where(fav_up, up, ~up)
            az = np.abs(z)
            line = []
            for lo, hi in ((1, 1.5), (1.5, 2), (2, 2.5), (2.5, 3), (3, 4), (4, 99)):
                m = (az >= lo) & (az < hi)
                if m.sum() >= 20:
                    line.append(f"|z| {lo}-{hi}: {win[m].mean():.4f} (n={m.sum()})")
            print(f" {tl:>3}s left  " + "  ".join(line))
