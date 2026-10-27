"""Command line entry point.

    python -m polyedge run      # one trading run (paper unless POLYEDGE_MODE=live)
    python -m polyedge crypto   # BTC Up/Down closing-minutes loop (no Claude calls)
    python -m polyedge crypto-report  # stats for the crypto loop, from state/crypto/
    python -m polyedge status   # print portfolio, P&L and recent decisions
    python -m polyedge dashboard [--out FILE]  # write the dashboard page from state/
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from polyedge.brokers import LiveBroker, PaperBroker
from polyedge.config import Settings
from polyedge.journal import Journal
from polyedge.market_data import MarketData
from polyedge.risk import RiskManager


def build(settings: Settings):
    md = MarketData()
    if settings.live:
        key_id = os.environ.get("POLYMARKET_KEY_ID")
        secret = os.environ.get("POLYMARKET_SECRET_KEY")
        if not key_id or not secret:
            sys.exit("Live mode needs POLYMARKET_KEY_ID and POLYMARKET_SECRET_KEY.")
        broker = LiveBroker(md, key_id, secret)
    else:
        broker = PaperBroker(md, settings.state_dir, settings.paper_starting_cash)
    return md, broker, RiskManager(settings, broker, md)


def cmd_run(settings: Settings) -> None:
    from polyedge.agent import Toolbox, run_agent, run_context

    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    md, broker, risk = build(settings)
    journal = Journal(settings.state_dir, run_id, settings.mode)

    events = broker.sync()
    for e in events:
        journal.log("sync", event=e)
    _write_performance(settings, broker)

    halt = risk.halted()
    if not halt.ok:
        journal.log("halted", reason=halt.reason)
        print(f"Not trading: {halt.reason}.")
        _write_last_run(settings, run_id, f"Halted: {halt.reason}")
        return

    last_path = settings.state_dir / "last_run.md"
    last_run = last_path.read_text() if last_path.exists() else ""
    summary = run_agent(
        settings, Toolbox(settings, md, broker, risk, journal), run_context(settings, events, last_run)
    )
    journal.log("summary", text=summary)
    _write_last_run(settings, run_id, summary)
    _write_performance(settings, broker)
    print(summary)


def cmd_crypto(settings: Settings) -> None:
    from dataclasses import replace

    from polyedge.crypto_updown import CryptoTrader

    # Separate state folder so this loop and the scheduled Claude runs never write the same files.
    settings = replace(settings, state_dir=settings.state_dir / "crypto")
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    md, broker, risk = build(settings)
    journal = Journal(settings.state_dir, run_id, settings.mode)
    journal.log("crypto_start", horizons=list(settings.crypto_horizons), minutes=settings.crypto_run_minutes)
    trades = CryptoTrader(settings, md, broker, risk, journal).run(settings.crypto_run_minutes)
    journal.log("crypto_end", trades=len(trades))
    print(f"{len(trades)} trades this run.")


def _write_performance(settings: Settings, broker) -> None:
    """Per-category and per-strategy paper P&L and Brier score, for review outside the agent."""
    from polyedge.agent import track_record

    settings.state_dir.mkdir(parents=True, exist_ok=True)
    (settings.state_dir / "performance.json").write_text(json.dumps(track_record(broker), indent=2, sort_keys=True))


def _write_last_run(settings: Settings, run_id: str, text: str) -> None:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    (settings.state_dir / "last_run.md").write_text(f"# Run {run_id} ({settings.mode})\n\n{text}\n")


def cmd_status(settings: Settings) -> None:
    md, broker, risk = build(settings)
    equity = risk.equity()
    print(f"Mode: {settings.mode}")
    print(f"Cash available: ${broker.cash():.2f}")
    print(f"Equity (positions at best bid): ${equity:.2f}")
    if not settings.live:
        start = settings.paper_starting_cash
        print(f"Paper P&L since start: ${equity - start:+.2f} ({(equity - start) / start:+.1%})")
        print(f"Realized P&L: ${broker.state['realized_pnl']:+.2f}")
        from polyedge.agent import track_record

        for key, row in track_record(broker).items():
            print(f"  {key}: P&L ${row['realized_pnl']:+.2f}, resolved {row['resolved']}, "
                  f"hit rate {row['hit_rate']}, Brier {row['brier']}")
    print("Positions:")
    for p in broker.positions():
        print(f"  {p.slug} {p.side.upper()} x{p.qty:g} @ {p.avg_price:.3f}")
    journal = settings.state_dir / "journal.jsonl"
    if journal.exists():
        rows = [json.loads(l) for l in journal.read_text().splitlines() if l.strip()]
        usage = [r for r in rows if r["kind"] == "usage"]
        if usage:
            cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
            day = [u for u in usage if u["ts"] >= cutoff]
            print(
                f"Claude API spend (estimate): ${sum(u['est_cost_usd'] for u in day):.2f} over {len(day)} runs "
                f"in the last 24h, ${sum(u['est_cost_usd'] for u in usage):.2f} total"
            )
        reqs = [r for r in rows if r["kind"] == "order_request"]
        print(f"Order requests: {len(reqs)} ({sum(r['approved'] for r in reqs)} approved)")
        for r in reqs[-5:]:
            verdict = "ok" if r["approved"] else f"rejected: {r['reject_reason']}"
            print(f"  {r['ts']} {r['action']} {r['side']} {r['slug']} @ {r['price']} x{r['contracts']} ({verdict})")


def main() -> None:
    parser = argparse.ArgumentParser(prog="polyedge")
    parser.add_argument("command", choices=["run", "crypto", "crypto-report", "status", "dashboard"])
    parser.add_argument("--out", default="dashboard.html", help="dashboard output file")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "crypto-report":
        from polyedge.crypto_report import render

        print(render(settings.state_dir / "crypto"), end="")
        return
    if args.command == "dashboard":
        from pathlib import Path

        from polyedge.dashboard import render

        print(render(settings, Path(args.out)))
        return
    {"run": cmd_run, "crypto": cmd_crypto, "status": cmd_status}[args.command](settings)


if __name__ == "__main__":
    main()
