"""Build the dashboard page from the committed state/ files.

    python -m polyedge dashboard [--out dashboard.html]

Reads only local files (no API calls), so it is safe to run anywhere. Account
balances from the live check are reduced to a funded yes/no.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from polyedge.config import Settings

TEMPLATE = Path(__file__).with_name("dashboard_template.html")
PLACEHOLDER = "/*__POLYEDGE_DATA__*/null"


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _track_record(state: dict[str, Any]) -> dict[str, Any]:
    from polyedge.agent import track_record

    class _Broker:
        pass

    b = _Broker()
    b.state = state
    return track_record(b)


def snapshot(settings: Settings) -> dict[str, Any]:
    sd = settings.state_dir
    paper = _load(sd / "paper.json", {"cash": settings.paper_starting_cash, "positions": {}, "orders": []})
    rows = []
    journal = sd / "journal.jsonl"
    if journal.exists():
        rows = [json.loads(line) for line in journal.read_text().splitlines() if line.strip()]

    positions = []
    for key, p in (paper.get("positions") or {}).items():
        if p.get("qty", 0) <= 0:
            continue
        slug, side = key.rsplit("|", 1)
        positions.append(
            {
                "slug": slug,
                "side": side,
                "qty": p["qty"],
                "cost": round(p["cost"], 2),
                "avg_price": round(p["cost"] / p["qty"], 4),
                "category": p.get("category", ""),
                "strategy": p.get("strategy", "edge"),
                "probability": p.get("probability"),
            }
        )

    runs: dict[str, dict[str, Any]] = {}
    for r in rows:
        run = runs.setdefault(r["run"], {"run": r["run"], "ts": r["ts"], "requests": 0, "approved": 0})
        run["ts"] = max(run["ts"], r["ts"])
        if r["kind"] == "order_request":
            run["requests"] += 1
            run["approved"] += 1 if r.get("approved") else 0
        elif r["kind"] == "usage":
            run["cost"] = r.get("est_cost_usd")
            run["web_searches"] = r.get("web_searches")
            run["api_calls"] = r.get("api_calls")
        elif r["kind"] == "summary":
            run["summary"] = r.get("text", "")
        elif r["kind"] == "halted":
            run["halted"] = r.get("reason")

    live = _load(sd / "live_check.json", {})
    last_run = sd / "last_run.md"
    s = settings
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "mode": s.mode,
        "model": s.model,
        "schedule": "every 2 hours (cron 7 */2 * * *)",
        "starting_cash": s.paper_starting_cash,
        "cash": round(paper.get("cash", 0.0), 2),
        "realized_pnl": round(paper.get("realized_pnl", 0.0), 2),
        "positions": positions,
        "open_orders": [
            {k: o.get(k) for k in ("slug", "action", "side", "price", "contracts", "strategy", "category")}
            for o in paper.get("orders", [])
        ],
        "resolved": paper.get("resolved", []),
        "track_record": _track_record(paper),
        "requests": [
            {
                k: r.get(k)
                for k in (
                    "ts", "run", "slug", "action", "side", "price", "contracts", "probability",
                    "confidence", "strategy", "category", "approved", "reject_reason", "rationale",
                )
            }
            for r in rows
            if r["kind"] == "order_request"
        ],
        "fills": [r for r in rows if r["kind"] == "order_result"],
        "runs": sorted(runs.values(), key=lambda x: x["ts"]),
        "last_run_md": last_run.read_text() if last_run.exists() else "",
        "risk": _load(sd / "risk.json", {}),
        "live_check": {
            "checked_at": live.get("checked_at"),
            "auth": live.get("auth"),
            "funded": bool((live.get("account") or {}).get("funded")),
        },
        "limits": {
            "max_order_usd": s.max_order_usd,
            "max_market_usd": s.max_market_usd,
            "max_total_usd": s.max_total_usd,
            "max_daily_loss_usd": s.max_daily_loss_usd,
            "max_weekly_loss_usd": s.max_weekly_loss_usd,
            "max_market_pct": s.max_market_pct,
            "max_cluster_pct": s.max_cluster_pct,
            "kelly_multiplier": s.kelly_multiplier,
            "shrink": s.shrink,
            "max_orders_per_run": s.max_orders_per_run,
            "min_price": s.min_price,
            "longshot_min_edge": s.longshot_min_edge,
            "max_price": s.max_price,
            "fav_min_price": s.fav_min_price,
            "fav_max_hours": s.fav_max_hours,
            "fav_min_edge": s.fav_min_edge,
            "fav_max_order_usd": s.fav_max_order_usd,
            "fav_max_orders_per_run": s.fav_max_orders_per_run,
            "fav_max_total_usd": s.fav_max_total_usd,
        },
    }


def render(settings: Settings, out: Path) -> Path:
    data = json.dumps(snapshot(settings)).replace("</", "<\\/")
    out.write_text(TEMPLATE.read_text().replace(PLACEHOLDER, data))
    return out
