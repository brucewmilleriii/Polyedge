"""Download 1-second Binance klines for the Up/Down coins (run on a GitHub runner).

Saves research/data/<coin>_1s.npz: t0 (unix secs of the first sample), tick, and
d = int32 diffs of close/tick per second (gaps forward-filled), so
close = (cumsum(d) + base) * tick.
"""
import datetime as dt, io, json, sys, time, urllib.request, zipfile
from pathlib import Path
import numpy as np

COINS = {"btc": ("BTCUSDT", 0.01), "eth": ("ETHUSDT", 0.01), "sol": ("SOLUSDT", 0.01), "xrp": ("XRPUSDT", 0.0001)}
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
OUT = Path("research/data"); OUT.mkdir(parents=True, exist_ok=True)

def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except Exception as e:
            if getattr(e, "code", None) == 404: return None
            print("retry", url, e); time.sleep(2 ** i)
    return None

today = dt.datetime.now(dt.timezone.utc).date()
for coin, (sym, tick) in COINS.items():
    rows = {}
    for k in range(DAYS, 0, -1):
        day = today - dt.timedelta(days=k)
        raw = get(f"https://data.binance.vision/data/spot/daily/klines/{sym}/1s/{sym}-1s-{day}.zip")
        if not raw: print("missing", sym, day); continue
        z = zipfile.ZipFile(io.BytesIO(raw)); txt = z.read(z.namelist()[0]).decode()
        for line in txt.splitlines():
            p = line.split(",")
            t = int(p[0]); t = t // 1000000 if t > 1e14 else t // 1000   # us or ms
            rows[t] = float(p[4])
        print(sym, day, len(rows), flush=True)
    # Today so far, from the REST API (1000 rows per call).
    start = int(dt.datetime.combine(today, dt.time(), dt.timezone.utc).timestamp()) * 1000
    now = int(time.time() * 1000)
    while start < now:
        raw = get(f"https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval=1s&startTime={start}&limit=1000")
        if not raw: print("rest failed", sym); break
        ks = json.loads(raw)
        if not ks: break
        for k in ks: rows[k[0] // 1000] = float(k[4])
        start = ks[-1][0] + 1000
    ts = sorted(rows); t0, t1 = ts[0], ts[-1]
    ticks = np.full(t1 - t0 + 1, -1, dtype=np.int64)
    for t in ts: ticks[t - t0] = round(rows[t] / tick)
    idx = np.where(ticks >= 0, np.arange(len(ticks)), 0); np.maximum.accumulate(idx, out=idx); ticks = ticks[idx]
    d = np.diff(ticks, prepend=0).astype(np.int64)
    np.savez_compressed(OUT / f"{coin}_1s.npz", t0=t0, tick=tick, d=d)
    print(coin, "saved", len(ticks), "secs", dt.datetime.utcfromtimestamp(t0), "->", dt.datetime.utcfromtimestamp(t1), flush=True)
