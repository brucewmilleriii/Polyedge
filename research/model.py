"""Fit P(favorite wins | |z|, secs_left, coin) on spot history; join to logged Polymarket snapshots."""
import json, datetime as dt
import numpy as np
from sklearn.linear_model import LogisticRegression
import sys; sys.path.insert(0, "research")
from backtest import load, COINS, W, fee

VOL_MIN = 15  # sigma from 1-minute returns over the last 15 minutes

def sigma_at(px, i):
    """per-sqrt-second vol from 1-min log returns ending at index i (vectorised over i)."""
    lp = np.log(px)
    pts = lp[i[:, None] - 60 * np.arange(VOL_MIN + 1)[None, :]]
    r = np.diff(pts, axis=1)
    return np.sqrt((r ** 2).mean(axis=1) / 60)

def feats(z, tl):
    az = np.abs(z)
    return np.column_stack([az, np.sqrt(az), np.log(tl)])

def dataset(coin, split_ts=None):
    t0, px = load(coin)
    first = ((t0 + 60 * VOL_MIN + 120) // W + 1) * W
    starts = np.arange(first, t0 + len(px) - W, W)
    i = starts - t0
    K = px[i - 1]; F = px[i + W - 1]; up = F >= K
    rows = []
    for tl in range(5, 151, 5):
        j = i + W - 1 - tl
        p = px[j]; sig = sigma_at(px, j)
        z = np.log(p / K) / (np.maximum(sig, 1e-9) * np.sqrt(tl))
        win = np.where(z >= 0, up, ~up)
        rows.append((starts, z, np.full(len(z), tl), win))
    S, Z, T, Y = (np.concatenate(x) for x in zip(*rows))
    keep = Z != 0
    return S[keep], Z[keep], T[keep], Y[keep], (t0, px)

def fit(Z, T, Y):
    m = LogisticRegression(C=10, max_iter=1000)
    m.fit(feats(Z, T), Y)
    return m

if __name__ == "__main__":
    split = dt.datetime(2026, 10, 21, tzinfo=dt.timezone.utc).timestamp()
    models, spot = {}, {}
    for coin in COINS:
        S, Z, T, Y, sp = dataset(coin)
        tr = S < split
        m = fit(Z[tr], T[tr], Y[tr])
        p = m.predict_proba(feats(Z[~tr], T[~tr]))[:, 1]
        print(f"\n{coin}: test calibration (Oct 21+), favorite side")
        for lo, hi in ((.8, .9), (.9, .95), (.95, .97), (.97, .98), (.98, .99), (.99, .995), (.995, 1)):
            k = (p >= lo) & (p < hi)
            if k.sum(): print(f"  model {lo:.3f}-{hi:.3f}: n={k.sum():5d} predicted {p[k].mean():.4f} actual {Y[~tr][k].mean():.4f}")
        models[coin] = fit(Z, T, Y); spot[coin] = sp
    # Join with logged Polymarket snapshots.
    out = []
    for line in open("state/crypto/markets.jsonl"):
        r = json.loads(line)
        if not r["outcome"]: continue
        t0, px = spot[r["asset"]]
        end = int(dt.datetime.fromisoformat(r["window_end"]).timestamp())
        K = px[end - W - 1 - t0]
        for s in r["snaps"]:
            tl = s["secs_left"]; j = int(round(end - tl)) - t0 - 1
            if j >= len(px) or tl < 2: continue
            sig = sigma_at(px, np.array([j]))[0]
            z = np.log(px[j] / K) / (sig * np.sqrt(tl))
            pf = models[r["asset"]].predict_proba(feats(np.array([z]), np.array([tl])))[0, 1]
            p_up = pf if z >= 0 else 1 - pf
            out.append(dict(slug=r["slug"], asset=r["asset"], at=s["at"], tl=tl, z=z, p_up=p_up,
                            up_ask=s["up_ask"], down_ask=s["down_ask"], outcome=r["outcome"]))
    json.dump(out, open("research/joined.json", "w"))
    print("\njoined snapshots:", len(out))
