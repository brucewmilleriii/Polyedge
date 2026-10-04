"""The Claude trading loop: Claude researches and proposes, code checks and executes."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import anthropic

from polyedge.brokers import OrderRequest
from polyedge.config import Settings
from polyedge.journal import Journal
from polyedge.market_data import MarketData, side_book, taker_fee_per_contract
from polyedge.risk import CONFIDENCE_MIN_EDGE, RiskManager

PROMPT_FILE = Path(__file__).parent / "prompts" / "polyedge_v2_1.md"

RUNNER_NOTES = """

---

## Operating environment (added by the Polyedge runner)

This is an unattended, scheduled run (roughly every 30 minutes). No human will reply, so \
do not wait for instructions: work through your pipeline on markets you find with the \
tools, act through place_order, and finish with your Quick Scan Table, a Full Trade Thesis \
for each order you placed, and a No-Trade Declaration for anything you passed on. Runs are \
frequent, so keep each one focused: re-check what changed since the last run summary and \
your open positions first, then look at a few new candidates rather than the whole board.

- Venue: Polymarket US (CFTC-regulated). Contracts pay $1 if their side wins. Markets \
settle under the exchange's rules rather than UMA, but still skip ambiguous resolution wording.
- Prices from get_market are per contract of the named side (yes or no). Taker fee per \
contract is 0.0695 x p x (1 - p).
- Tools: get_portfolio, list_markets, search_markets, get_market, check_event_consistency, \
place_order, cancel_order, web_search.

### House rules (from research on what persistently profitable Polymarket accounts do)
- Don't buy longshots. Anything under 15 cents needs at least 15 points of edge on the \
shrunk estimate; when a longshot looks overpriced, the trade is usually buying the NO side.
- Every run, scan linked markets for inconsistencies: mutually exclusive outcomes whose \
prices sum far from 100% (use check_event_consistency), a state race against the \
national one, a game against its series, and "by date A" against "by date B" ladders \
(the later date can never be less likely). Before trading one leg, confirm the two \
markets' resolution wording actually lines up. These gaps are an edge a slower, \
reasoning trader can capture.
- Hold to resolution by default. Selling is allowed only with thesis_broken set to true, \
when new information has actually invalidated the reason you bought.
- Avoid markets that resolve on one person's decision or a surprise announcement \
(strikes, arrests, appointments, award picks, "will X say Y"). Insiders dominate them.
- Use your track record. get_portfolio reports paper P&L and calibration by category \
and by strategy. Be more selective in categories where you are losing.
- Your probability is shrunk halfway toward the market mid before anything else: \
p_used = mid + 0.5 x (your probability - mid). The edge minimums and quarter-Kelly sizing \
both use p_used, so a 10-point disagreement with the market counts as a 5-point edge.

### Two strategies, tracked separately
- strategy "edge": the main pipeline above.
- strategy "favorite": YES or NO priced 0.90 to 0.97 that resolves within 48 hours on a \
deep book, where heavy favorites tend to be slightly underpriced. Needs at least 2 points \
of edge after fees on the shrunk estimate instead of the confidence tiers. At most $5 per \
order and 2 favorite orders per run, and they count toward every other cap. No live \
in-game sports markets. Still apply the no-ambiguity check.

### Limits
- place_order enforces hard limits in code; get_portfolio lists their current values. Where \
your sizing rules and those limits differ, the stricter one applies. Limits include \
per-order, per-market and total dollar caps, a per-event cluster cap, daily and weekly \
loss stops, the Kelly cap, and minimum edge after fees measured against the price you pay \
(high 5, medium 8, low 12 points). A rejection for size (Kelly, per-order, per-market, \
event or total caps) is the sizing rule doing its job: resubmit once at or below the \
allowed size it names. A rejection for eligibility (edge, price floor, confidence, \
category, loss stop, hold rule) means skip the trade; do not tweak inputs to get it through.
- Only limit orders exist here. For an emergency exit, sell at or below the best bid.
- The run context states whether this is paper or live mode.
"""

SYSTEM_PROMPT = PROMPT_FILE.read_text() + RUNNER_NOTES


def tool_defs(settings: Settings) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = [
        {
            "name": "get_portfolio",
            "description": "Cash, open positions (with current best bid), open orders and today's P&L.",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            "strict": True,
        },
        {
            "name": "list_markets",
            "description": (
                "List open markets with their current YES price. Page through with offset. "
                "category filters by Polymarket category, for example sports, politics, economics, crypto."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Empty string for all categories."},
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                },
                "required": ["category", "limit", "offset"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "name": "search_markets",
            "description": "Search open events and their markets by keyword.",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "name": "get_market",
            "description": (
                "Full market details: rules, end date, and the top of the order book for both the "
                "yes and no sides, quoted as the price per contract of that side."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"slug": {"type": "string"}},
                "required": ["slug"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "name": "place_order",
            "description": (
                "Place a limit order. price is per contract of `side` (0-1). For buys, probability is "
                "your estimate that `side` wins, and rationale explains the edge in one or two "
                "sentences. Hard risk limits are checked before anything is sent; a rejection "
                "explains which limit applied."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "action": {"type": "string", "enum": ["buy", "sell"]},
                    "side": {"type": "string", "enum": ["yes", "no"]},
                    "price": {"type": "number"},
                    "contracts": {"type": "integer"},
                    "probability": {"type": "number", "description": "Chance `side` wins, 0-1. Ignored for sells."},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "strategy": {"type": "string", "enum": ["edge", "favorite"]},
                    "thesis_broken": {
                        "type": "boolean",
                        "description": "Sells only: true when new information invalidated the reason you bought.",
                    },
                    "rationale": {"type": "string"},
                },
                "required": [
                    "slug", "action", "side", "price", "contracts", "probability",
                    "confidence", "strategy", "thesis_broken", "rationale",
                ],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "name": "check_event_consistency",
            "description": (
                "For an event with several outcome markets, return each market's best YES bid and ask "
                "and their sums. If the outcomes are mutually exclusive and exhaustive, the asks should "
                "sum to about 1 or more and the bids to about 1 or less; a sum of asks well under 1 or "
                "of bids well over 1 means some outcome is mispriced. event_slug comes from "
                "search_markets."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"event_slug": {"type": "string"}},
                "required": ["event_slug"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "name": "cancel_order",
            "description": "Cancel one of your open orders.",
            "input_schema": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}, "slug": {"type": "string"}},
                "required": ["order_id", "slug"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {"type": "web_search_20260209", "name": "web_search", "max_uses": 8},
    ]
    return tools


class Toolbox:
    def __init__(self, settings: Settings, md: MarketData, broker: Any, risk: RiskManager, journal: Journal):
        self.s = settings
        self.md = md
        self.broker = broker
        self.risk = risk
        self.journal = journal

    def run(self, name: str, args: dict[str, Any]) -> Any:
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            raise ValueError(f"unknown tool {name}")
        return fn(**args)

    def t_get_portfolio(self) -> dict[str, Any]:
        positions = []
        for p in self.broker.positions():
            try:
                bid = side_book(self.md.book(p.slug), p.side).best_bid
            except Exception:
                bid = None
            positions.append(
                {
                    "slug": p.slug,
                    "side": p.side,
                    "contracts": p.qty,
                    "avg_price": round(p.avg_price, 4),
                    "best_bid_now": bid,
                }
            )
        equity = self.risk.equity()
        start = self.risk.start_of_day_equity(equity)
        return {
            "mode": self.s.mode,
            "cash_available": round(self.broker.cash(), 2),
            "equity": round(equity, 2),
            "pnl_today": round(equity - start, 2),
            "positions": positions,
            "open_orders": self.broker.open_orders(),
            "track_record": track_record(self.broker),
            "limits": {
                "max_order_usd": self.s.max_order_usd,
                "max_market_usd": self.s.max_market_usd,
                "max_total_usd": self.s.max_total_usd,
                "max_daily_loss_usd": self.s.max_daily_loss_usd,
                "max_weekly_loss_usd": self.s.max_weekly_loss_usd,
                "max_market_pct_of_equity": self.s.max_market_pct,
                "max_event_cluster_pct_of_equity": self.s.max_cluster_pct,
                "kelly_multiplier": self.s.kelly_multiplier,
                "orders_left_this_run": self.s.max_orders_per_run - self.risk.orders_this_run,
                "min_edge_after_fees": {k: max(v, self.s.min_edge) for k, v in CONFIDENCE_MIN_EDGE.items()},
                "price_range": [self.s.min_price, self.s.max_price],
                "categories": list(self.s.categories) or "all",
            },
        }

    def t_list_markets(self, category: str, limit: int, offset: int) -> list[dict[str, Any]]:
        if not category and len(self.s.categories) == 1:
            category = self.s.categories[0]
        return self.md.list_markets(category=category, limit=max(1, min(limit, 50)), offset=max(0, offset))

    def t_search_markets(self, query: str) -> list[dict[str, Any]]:
        return self.md.search(query)

    def t_get_market(self, slug: str) -> dict[str, Any]:
        m = self.md.market(slug)
        raw_book = self.md.book(slug)
        books = {}
        for side in ("yes", "no"):
            b = side_book(raw_book, side)
            books[side] = {
                "bids": [[l.price, l.qty] for l in b.bids[:5]],
                "asks": [[l.price, l.qty] for l in b.asks[:5]],
                "taker_fee_at_best_ask": round(taker_fee_per_contract(b.best_ask), 4) if b.best_ask else None,
            }
        return {
            "slug": slug,
            "question": m.get("question") or m.get("title"),
            "description": (m.get("description") or "")[:2000],
            "category": m.get("category"),
            "end_date": m.get("endDate"),
            "game_start_time": m.get("gameStartTime"),
            "state": raw_book.get("state"),
            "tick_size": m.get("orderPriceMinTickSize"),
            "book": books,
        }

    def t_place_order(
        self,
        slug: str,
        action: str,
        side: str,
        price: float,
        contracts: int,
        probability: float,
        confidence: str,
        strategy: str,
        thesis_broken: bool,
        rationale: str,
    ) -> dict[str, Any]:
        try:
            category = (self.md.market(slug).get("category") or "").lower()
        except Exception:
            category = ""
        req = OrderRequest(
            slug=slug,
            action=action,
            side=side,
            price=round(float(price), 3),
            contracts=int(contracts),
            category=category,
            strategy=strategy,
            probability=probability if action == "buy" else None,
        )
        decision = self.risk.check(req, probability, confidence, thesis_broken=thesis_broken)
        self.journal.log(
            "order_request",
            slug=slug,
            action=action,
            side=side,
            price=req.price,
            contracts=req.contracts,
            probability=probability,
            confidence=confidence,
            strategy=strategy,
            category=category,
            thesis_broken=thesis_broken,
            rationale=rationale,
            approved=decision.ok,
            reject_reason=decision.reason or None,
        )
        if not decision.ok:
            return {"status": "rejected", "reason": decision.reason}
        result = self.broker.place(req)
        self.risk.record_order(req.strategy)
        self.journal.log("order_result", slug=slug, **result)
        return {"status": "accepted", **result}

    def t_check_event_consistency(self, event_slug: str) -> dict[str, Any]:
        ev = self.md.event(event_slug)
        rows = []
        for m in (ev.get("markets") or [])[:25]:
            if m.get("closed"):
                continue
            try:
                b = side_book(self.md.book(m["slug"]), "yes")
            except Exception:
                continue
            rows.append(
                {
                    "slug": m["slug"],
                    "outcome": m.get("title") or m.get("subtitle") or m.get("question"),
                    "yes_bid": b.best_bid,
                    "yes_ask": b.best_ask,
                }
            )
        asks = [r["yes_ask"] for r in rows if r["yes_ask"] is not None]
        bids = [r["yes_bid"] for r in rows if r["yes_bid"] is not None]
        return {
            "event": ev.get("title") or event_slug,
            "markets": rows,
            "sum_of_yes_asks": round(sum(asks), 4) if len(asks) == len(rows) else None,
            "sum_of_yes_bids": round(sum(bids), 4) if len(bids) == len(rows) else None,
            "note": "Sums are only meaningful if the outcomes are mutually exclusive and cover every case.",
        }

    def t_cancel_order(self, order_id: str, slug: str) -> dict[str, Any]:
        self.broker.cancel(order_id, slug)
        self.journal.log("cancel", order_id=order_id, slug=slug)
        return {"status": "canceled", "order_id": order_id}


def track_record(broker: Any) -> dict[str, Any]:
    """Paper results by category and strategy: P&L, resolved count, hit rate and Brier score."""
    state = getattr(broker, "state", None)
    if not state:
        return {}
    groups: dict[str, dict[str, Any]] = {}
    for r in state.get("resolved", []):
        for key in (f"category:{r.get('category') or 'unknown'}", f"strategy:{r.get('strategy', 'edge')}"):
            g = groups.setdefault(key, {"resolved": 0, "won": 0, "brier_sum": 0.0, "brier_n": 0})
            g["resolved"] += 1
            g["won"] += 1 if r["outcome"] >= 0.5 else 0
            if r.get("probability") is not None:
                g["brier_sum"] += (r["probability"] - r["outcome"]) ** 2
                g["brier_n"] += 1
    out = {}
    for key, pnl in sorted(state.get("pnl_by", {}).items()):
        g = groups.get(key, {"resolved": 0, "won": 0, "brier_n": 0})
        out[key] = {
            "realized_pnl": round(pnl, 2),
            "resolved": g["resolved"],
            "hit_rate": round(g["won"] / g["resolved"], 3) if g["resolved"] else None,
            "brier": round(g["brier_sum"] / g["brier_n"], 4) if g.get("brier_n") else None,
        }
    return out


# USD per million tokens for claude-opus-5-5, plus $10 per 1,000 web searches.
PRICES = {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00, "search": 0.01}


class UsageMeter:
    def __init__(self) -> None:
        self.calls = 0
        self.tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        self.searches = 0

    def add(self, usage: Any) -> None:
        if usage is None:
            return
        self.calls += 1
        self.tokens["input"] += getattr(usage, "input_tokens", 0) or 0
        self.tokens["output"] += getattr(usage, "output_tokens", 0) or 0
        self.tokens["cache_read"] += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.tokens["cache_write"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
        stu = getattr(usage, "server_tool_use", None)
        self.searches += (getattr(stu, "web_search_requests", 0) or 0) if stu else 0

    def cost_usd(self) -> float:
        tok = sum(self.tokens[k] * PRICES[k] for k in self.tokens) / 1_000_000
        return round(tok + self.searches * PRICES["search"], 4)

    def summary(self) -> dict[str, Any]:
        return {"api_calls": self.calls, **self.tokens, "web_searches": self.searches, "est_cost_usd": self.cost_usd()}


def run_agent(settings: Settings, toolbox: Toolbox, context: str, client: anthropic.Anthropic | None = None) -> str:
    meter = UsageMeter()
    try:
        return _run_agent(settings, toolbox, context, client, meter)
    finally:
        toolbox.journal.log("usage", model=settings.model, **meter.summary())


def _run_agent(settings, toolbox, context, client, meter) -> str:
    client = client or anthropic.Anthropic()
    tools = tool_defs(settings)
    messages: list[dict[str, Any]] = [{"role": "user", "content": context}]
    final_text = ""

    for _ in range(settings.max_agent_turns):
        response = client.beta.messages.create(
            model=settings.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": settings.effort},
            cache_control={"type": "ephemeral"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        meter.add(getattr(response, "usage", None))
        messages.append({"role": "assistant", "content": response.content})
        text = "".join(b.text for b in response.content if b.type == "text")
        if text:
            final_text = text

        if response.stop_reason == "refusal":
            toolbox.journal.log("refusal", details=str(response.stop_details))
            return final_text or "Run ended: the model declined to continue."
        if response.stop_reason == "pause_turn":
            # A server tool (web search) hit its iteration cap; resend to resume.
            continue
        if response.stop_reason != "tool_use":
            return final_text

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                out = toolbox.run(block.name, block.input)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out, default=str)})
            except Exception as e:  # report tool failures back to Claude instead of crashing the run
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {e}", "is_error": True})
        messages.append({"role": "user", "content": results})

    return final_text or "Run ended: turn limit reached."


def run_context(settings: Settings, sync_events: list[str], last_run: str = "") -> str:
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"Current time: {now}.", f"Mode: {settings.mode}."]
    if settings.categories:
        lines.append(f"Only these categories can be traded: {', '.join(settings.categories)}.")
    if sync_events:
        lines.append("Since the last run: " + "; ".join(sync_events) + ".")
    if last_run:
        lines.append("Your previous run's summary, for continuity:\n" + last_run[:6000])
    lines.append("Run your trading routine now.")
    return "\n".join(lines)
