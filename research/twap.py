"""Model the settlement as a 60-second average ending at each window boundary.

Matching Polymarket's logged outcomes against Binance: a point price at the
boundary agrees 90.5% of the time, a 60s average 98.6%. So the strike is the
average over [start-60, start) and the settle is the average over [end-60, end).
"""
import json, datetime as dt, sys
import numpy as np
from sklearn.linear_model import LogisticRegression
sys.path.insert(0, "research")
from backtest import load, COINS, W, fee
from model import sigma_at

AVG = 60

def z_twap(cs, px, s, e, j, sig):
    """z of (settle avg - strike avg) at index j (last seen second), window [s, e)."""
    K = (cs[s] - cs[s - AVG]) / AVG
    tl = np.asarray(e - 1 - j)           # seconds still to come
    p = px[j]
    known = cs[j + 1] - cs[np.minimum(e - AVG, j + 1)]  # seconds already inside the averaging window
    late = tl < AVG
    mu = np.where(late, (known + np.minimum(tl, AVG) * p) / AVG - K, p - K)
    var = (p * sig) ** 2 * np.where(late, (tl / 3) * (tl / AVG) ** 2, (tl - AVG) + AVG / 3)
    return mu / np.sqrt(np.maximum(var, 1e-18)), K

def feats(z, tl):
    az = np.abs(z)
    return np.column_stack([az, np.sqrt(az), np.log(tl)])

def dataset(coin):
    t0, px = load(coin)
    cs = np.concatenate([[0.0], np.cumsum(px)])  # cs[k] = sum px[:k]
    first = ((t0 + 1200) // W + 1) * W
    starts = np.arange(first, t0 + len(px) - W, W) - t0
    ends = starts + W
    settle = (cs[ends] - cs[ends - AVG]) / AVG
    strike = (cs[starts] - cs[starts - AVG]) / AVG
    up = settle >= strike
    S, Z, T, Y = [], [], [], []
    for tl in list(range(2, 61, 2)) + list(range(65, 151, 5)):
        j = ends - 1 - tl
        sig = sigma_at(px, j)
        z, _ = z_twap(cs, px, starts, ends, j, sig)
        S.append(starts + t0); Z.append(z); T.append(np.full(len(z), tl)); Y.append(np.where(z >= 0, up, ~up))
    S, Z, T, Y = map(np.concatenate, (S, Z, T, Y))
    k = np.isfinite(Z) & (Z != 0)
    return S[k], Z[k], T[k], Y[k], (t0, px, cs)

def fit(Z, T, Y):
    return LogisticRegression(C=10, max_iter=2000).fit(feats(Z, T), Y)

if __name__ == "__main__":
    split = dt.datetime(2026, 10, 21, tzinfo=dt.timezone.utc).timestamp()
    models, spot = {}, {}
    for coin in COINS:
        S, Z, T, Y, sp = dataset(coin)
        tr = S < split
        m = fit(Z[tr], T[tr], Y[tr])
        p = m.predict_proba(feats(Z[~tr], T[~tr]))[:, 1]
        print(f"\n{coin}: test calibration (Oct 21+)")
        for lo, hi in ((.8, .9), (.9, .95), (.95, .97), (.97, .98), (.98, .99), (.99, .995), (.995, .999), (.999, 1)):
            k = (p >= lo) & (p < hi)
            if k.sum(): print(f"  model {lo:.3f}-{hi:.3f}: n={k.sum():5d} predicted {p[k].mean():.4f} actual {Y[~tr][k].mean():.4f}")
        models[coin] = fit(Z, T, Y); spot[coin] = sp
    out = []
    for line in open("state/crypto/markets.jsonl"):
        r = json.loads(line)
        if not r["outcome"]: continue
        t0, px, cs = spot[r["asset"]]
        e = int(dt.datetime.fromisoformat(r["window_end"]).timestamp()) - t0
        for snap in r["snaps"]:
            tl = snap["secs_left"]; j = int(round(e - tl)) - 1
            tli = e - 1 - j
            if tli < 2: continue
            sig = sigma_at(px, np.array([j]))[0]
            z, _ = z_twap(cs, px, e - W, e, j, sig)
            pf = models[r["asset"]].predict_proba(feats(np.array([z]), np.array([tli])))[0, 1]
            out.append(dict(slug=r["slug"], asset=r["asset"], at=snap["at"], tl=tl, z=float(z),
                            p_up=float(pf if z >= 0 else 1 - pf), up_ask=snap["up_ask"],
                            down_ask=snap["down_ask"], up_bid=snap["up_bid"], outcome=r["outcome"]))
    json.dump(out, open("research/joined_twap.json", "w"))
    print("\njoined snapshots:", len(out))
