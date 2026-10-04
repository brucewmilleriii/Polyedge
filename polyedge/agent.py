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

This is an unattended, scheduled run. No human will reply, so do not wait for \
instructions: work through your pipeline on markets you find with the tools, act through \
place_order, and finish with your Quick Scan Table, a Full Trade Thesis for each order \
you placed, and a No-Trade Declaration for anything you passed on.

- Venue: Polymarket US (CFTC-regulated). Contracts pay $1 if their side wins. Markets \
settle under the exchange's rules rather than UMA, but still skip ambiguous resolution wording.
- Prices from get_market are per contract of the named side (yes or no). Taker fee per \
contract is 0.0695 x p x (1 - p).
- Tools: get_portfolio, list_markets, search_markets, get_market, place_order, \
cancel_order, web_search.
- Only limit orders exist here. For an emergency exit, sell at or below the best bid.
- place_order enforces hard limits in code; get_portfolio lists their current values. Where \
your sizing rules and those limits differ, the stricter one applies. Limits include \
per-order, per-market and total dollar caps, a per-event cluster cap, daily and weekly \
loss stops, a fractional-Kelly cap, and minimum edge after fees measured against the \
price you pay (high 5, medium 8, low 12 points). If an order is rejected, do not resize \
it just to squeeze under a limit; move on.
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
                    "rationale": {"type": "string"},
                },
                "required": ["slug", "action", "side", "price", "contracts", "probability", "confidence", "rationale"],
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
        rationale: str,
    ) -> dict[str, Any]:
        req = OrderRequest(slug=slug, action=action, side=side, price=round(float(price), 3), contracts=int(contracts))
        decision = self.risk.check(req, probability, confidence)
        self.journal.log(
            "order_request",
            slug=slug,
            action=action,
            side=side,
            price=req.price,
            contracts=req.contracts,
            probability=probability,
            confidence=confidence,
            rationale=rationale,
            approved=decision.ok,
            reject_reason=decision.reason or None,
        )
        if not decision.ok:
            return {"status": "rejected", "reason": decision.reason}
        result = self.broker.place(req)
        self.risk.record_order()
        self.journal.log("order_result", slug=slug, **result)
        return {"status": "accepted", **result}

    def t_cancel_order(self, order_id: str, slug: str) -> dict[str, Any]:
        self.broker.cancel(order_id, slug)
        self.journal.log("cancel", order_id=order_id, slug=slug)
        return {"status": "canceled", "order_id": order_id}


def run_agent(settings: Settings, toolbox: Toolbox, context: str, client: anthropic.Anthropic | None = None) -> str:
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


def run_context(settings: Settings, sync_events: list[str]) -> str:
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"Current time: {now}.", f"Mode: {settings.mode}."]
    if settings.categories:
        lines.append(f"Only these categories can be traded: {', '.join(settings.categories)}.")
    if sync_events:
        lines.append("Since the last run: " + "; ".join(sync_events) + ".")
    lines.append("Run your trading routine now.")
    return "\n".join(lines)
