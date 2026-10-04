from dataclasses import replace
from types import SimpleNamespace

import pytest

from polyedge.agent import Toolbox
from polyedge.brokers import INTENTS, LiveBroker, OrderRequest, PaperBroker
from polyedge.config import Settings
from polyedge.journal import Journal
from polyedge.market_data import MarketData, side_book, taker_fee_per_contract, to_yes_price
from polyedge.risk import RiskManager


def px(v):
    return {"value": f"{v:.4f}", "currency": "USD"}


class FakeClient:
    """Mimics the polymarket_us client using the response shapes the live gateway returns."""

    def __init__(self):
        self.books = {
            "atl": {
                "marketSlug": "atl",
                "bids": [{"px": px(0.40), "qty": "100"}, {"px": px(0.38), "qty": "500"}],
                "offers": [{"px": px(0.42), "qty": "50"}, {"px": px(0.45), "qty": "500"}],
                "state": "MARKET_STATE_OPEN",
            }
        }
        self.meta = {"atl": {"slug": "atl", "category": "sports", "active": True, "closed": False}}
        self.settle = {}
        self.markets = SimpleNamespace(
            list=lambda params=None: {"markets": []},
            retrieve_by_slug=lambda slug: {"market": self.meta[slug]},
            book=lambda slug: {"marketData": self.books[slug]},
            settlement=lambda slug: {"slug": slug, "settlement": self.settle[slug]},
        )


@pytest.fixture
def env(tmp_path):
    client = FakeClient()
    md = MarketData(client)
    settings = replace(
        Settings(),
        state_dir=tmp_path,
        kill_file=tmp_path / "KILL",
        max_order_usd=10,
        max_market_usd=25,
        max_total_usd=100,
    )
    broker = PaperBroker(md, tmp_path, settings.paper_starting_cash)
    risk = RiskManager(settings, broker, md)
    return SimpleNamespace(client=client, md=md, settings=settings, broker=broker, risk=risk)


def test_no_side_book_is_mirror_of_yes_book(env):
    raw = env.md.book("atl")
    no = side_book(raw, "no")
    assert no.best_ask == pytest.approx(0.60)  # 1 - best YES bid
    assert no.best_bid == pytest.approx(0.58)  # 1 - best YES ask
    assert to_yes_price("no", 0.60) == pytest.approx(0.40)
    assert INTENTS[("buy", "no")] == "ORDER_INTENT_BUY_SHORT"


def test_fee_formula_matches_published_example():
    # Polymarket US fee page: 1,000 contracts at $0.50 cost the taker $17.38 in fees.
    assert taker_fee_per_contract(0.5) * 1000 == pytest.approx(17.375)


def test_marketable_paper_buy_fills_at_ask_with_fee(env):
    res = env.broker.place(OrderRequest("atl", "buy", "yes", 0.42, 20))
    assert res["filled"] == 20 and res["resting"] == 0
    pos = env.broker.positions()[0]
    assert pos.qty == 20
    assert pos.cost == pytest.approx(0.42 * 20 + taker_fee_per_contract(0.42) * 20)


def test_partial_fill_rests_remainder_and_reserves_cash(env):
    cash0 = env.broker.cash()
    res = env.broker.place(OrderRequest("atl", "buy", "yes", 0.43, 60))
    assert res["filled"] == 50 and res["resting"] == 10
    assert env.broker.cash() == pytest.approx(cash0 - env.broker.positions()[0].cost - 0.43 * 10)


def test_resting_order_fills_when_market_crosses(env):
    env.broker.place(OrderRequest("atl", "buy", "yes", 0.30, 10))
    assert env.broker.positions() == []
    env.client.books["atl"]["offers"] = [{"px": px(0.29), "qty": "100"}]
    events = env.broker.sync()
    assert any("filled resting buy" in e for e in events)
    assert env.broker.positions()[0].qty == 10


def test_settlement_pays_no_holders(env):
    env.broker.place(OrderRequest("atl", "buy", "no", 0.60, 10))
    cash_before = env.broker.total_cash()
    env.client.meta["atl"]["closed"] = True
    env.client.settle["atl"] = 0.0  # YES lost, so NO pays $1
    env.broker.sync()
    assert env.broker.positions() == []
    assert env.broker.total_cash() == pytest.approx(cash_before + 10)


def test_risk_rejects_oversized_order(env):
    d = env.risk.check(OrderRequest("atl", "buy", "yes", 0.42, 30), probability=0.9)
    assert not d.ok and "max per order" in d.reason


def test_risk_requires_edge_after_fees(env):
    # Mid is 0.41, so 0.45 shrinks to 0.43: below price plus fee.
    d = env.risk.check(OrderRequest("atl", "buy", "yes", 0.42, 10), 0.45, "high")
    assert not d.ok and "shrunk toward the mid (0.430)" in d.reason
    assert env.risk.check(OrderRequest("atl", "buy", "yes", 0.42, 10), 0.70, "high").ok


def test_risk_caps_exposure_per_market(env):
    env.broker.place(OrderRequest("atl", "buy", "yes", 0.42, 23))  # about $9.80
    env.broker.place(OrderRequest("atl", "buy", "yes", 0.45, 22))  # about $9.90 more
    d = env.risk.check(OrderRequest("atl", "buy", "yes", 0.45, 20), probability=0.9)
    assert not d.ok and "in this market" in d.reason


def test_risk_blocks_opposite_side_and_unheld_sells(env):
    env.broker.place(OrderRequest("atl", "buy", "yes", 0.42, 10))
    assert "already holding" in env.risk.check(OrderRequest("atl", "buy", "no", 0.60, 5), 0.9).reason
    assert not env.risk.check(OrderRequest("atl", "sell", "yes", 0.40, 11), None).ok
    assert "held to resolution" in env.risk.check(OrderRequest("atl", "sell", "yes", 0.40, 10), None).reason
    assert env.risk.check(OrderRequest("atl", "sell", "yes", 0.40, 10), None, thesis_broken=True).ok


def test_kill_switch_and_daily_loss_halt_buys(env):
    (env.settings.kill_file).write_text("stop")
    assert "kill switch" in env.risk.check(OrderRequest("atl", "buy", "yes", 0.42, 5), 0.9).reason
    env.settings.kill_file.unlink()

    env.risk.start_of_day_equity(env.risk.equity())
    env.broker.state["cash"] -= 30  # simulate a $30 loss today
    assert "daily loss" in env.risk.halted().reason


def test_category_allowlist(env):
    s = replace(env.settings, categories=("politics",))
    risk = RiskManager(s, env.broker, env.md)
    assert "allowlist" in risk.check(OrderRequest("atl", "buy", "yes", 0.42, 5), 0.9).reason


def test_orders_per_run_limit_through_toolbox(env, tmp_path):
    s = replace(env.settings, max_orders_per_run=1)
    risk = RiskManager(s, env.broker, env.md)
    tb = Toolbox(s, env.md, env.broker, risk, Journal(tmp_path, "t", "paper"))
    first = tb.run("place_order", dict(slug="atl", action="buy", side="yes", price=0.42, contracts=5, probability=0.6, confidence="high", strategy="edge", thesis_broken=False, rationale="x"))
    second = tb.run("place_order", dict(slug="atl", action="buy", side="yes", price=0.42, contracts=5, probability=0.6, confidence="high", strategy="edge", thesis_broken=False, rationale="x"))
    assert first["status"] == "accepted"
    assert second["status"] == "rejected" and "this run" in second["reason"]
    assert (tmp_path / "journal.jsonl").read_text().count("order_request") == 2


def test_live_broker_sends_yes_terms_price_for_no_orders():
    sent = {}
    client = SimpleNamespace(orders=SimpleNamespace(create=lambda p: sent.update(p) or {"id": "o1", "executions": []}))
    LiveBroker(md=None, key_id="k", secret_key="s", client=client).place(OrderRequest("atl", "buy", "no", 0.60, 3))
    assert sent["intent"] == "ORDER_INTENT_BUY_SHORT"
    assert sent["price"] == {"value": "0.400", "currency": "USD"}
    assert sent["type"] == "ORDER_TYPE_LIMIT"


def test_agent_loop_runs_tools_and_returns_summary(env, tmp_path):
    from polyedge.agent import run_agent

    blk = lambda **kw: SimpleNamespace(**kw)
    replies = [
        SimpleNamespace(stop_reason="tool_use", content=[blk(type="tool_use", id="t1", name="get_portfolio", input={})]),
        SimpleNamespace(stop_reason="pause_turn", content=[blk(type="text", text="searching")]),
        SimpleNamespace(stop_reason="end_turn", content=[blk(type="text", text="No trades today.")]),
    ]
    calls = []

    def create(**kw):
        calls.append(kw)
        return replies[len(calls) - 1]

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    tb = Toolbox(env.settings, env.md, env.broker, env.risk, Journal(tmp_path, "t", "paper"))
    assert run_agent(env.settings, tb, "go", client=client) == "No trades today."
    tool_result = calls[1]["messages"][2]["content"][0]
    assert tool_result["tool_use_id"] == "t1" and '"mode": "paper"' in tool_result["content"]
    assert calls[0]["fallbacks"] == "default" and calls[0]["model"] == "claude-opus-5-5"


def test_confidence_sets_minimum_edge(env):
    # 0.66 shrinks to 0.535, an edge of about 0.098 after fees: enough for high and medium, not low.
    req = OrderRequest("atl", "buy", "yes", 0.42, 5)
    assert env.risk.check(req, 0.66, "high").ok
    assert env.risk.check(req, 0.66, "medium").ok
    assert "low confidence" in env.risk.check(req, 0.66, "low").reason


def test_fractional_kelly_caps_size(env):
    # Claude says 0.70 against a 0.41 mid: shrunk to 0.555, quarter Kelly on $500 allows about $26.
    d = env.risk.check(OrderRequest("atl", "buy", "yes", 0.42, 23), 0.70, "high")
    assert d.ok
    env.broker.state["cash"] = 100.0  # same trade on a $100 bankroll allows about $5
    env.risk.path.unlink()  # reset the day's opening equity so the loss stop doesn't fire
    d = env.risk.check(OrderRequest("atl", "buy", "yes", 0.42, 23), 0.70, "high")
    assert not d.ok and "shrunk probability (0.555)" in d.reason
    assert env.risk.check(OrderRequest("atl", "buy", "yes", 0.42, 5), 0.70, "high").ok


def test_percent_of_equity_cap_wins_when_stricter(env):
    s = replace(env.settings, max_market_pct=0.01)  # 1% of $500 = $5
    risk = RiskManager(s, env.broker, env.md)
    d = risk.check(OrderRequest("atl", "buy", "yes", 0.42, 15), 0.9, "high")
    assert not d.ok and "max is $5.00" in d.reason


def test_event_cluster_cap(env):
    env.client.meta["atl"]["eventSlug"] = "mlb-nl"
    env.client.books["atl2"] = env.client.books["atl"]
    env.client.meta["atl2"] = {"slug": "atl2", "category": "sports", "active": True, "closed": False, "eventSlug": "mlb-nl"}
    env.broker.place(OrderRequest("atl", "buy", "yes", 0.42, 20))
    s = replace(env.settings, max_cluster_pct=0.03)  # $15 across the event
    risk = RiskManager(s, env.broker, env.md)
    d = risk.check(OrderRequest("atl2", "buy", "yes", 0.42, 15), 0.9, "high")
    assert not d.ok and "event mlb-nl" in d.reason


def test_weekly_loss_halts(env):
    s = replace(env.settings, max_daily_loss_usd=1000, max_weekly_loss_usd=20)
    risk = RiskManager(s, env.broker, env.md)
    risk.start_of_week_equity(risk.equity())
    env.broker.state["cash"] -= 25
    assert "weekly loss" in risk.halted().reason


def test_system_prompt_is_polyedge_v2_1():
    from polyedge.agent import SYSTEM_PROMPT

    assert SYSTEM_PROMPT.startswith("# SYSTEM PROMPT — POLYEDGE v2.1")
    assert "Operating environment" in SYSTEM_PROMPT


def test_entry_price_floor_blocks_longshots(env):
    env.client.books["atl"]["bids"] = [{"px": px(0.08), "qty": "1000"}]
    env.client.books["atl"]["offers"] = [{"px": px(0.10), "qty": "1000"}]
    # 0.40 shrinks to 0.245 against a 0.09 mid: about 14 points, under the 15 needed below the floor.
    d = env.risk.check(OrderRequest("atl", "buy", "yes", 0.10, 20), 0.40, "high")
    assert not d.ok and "entry floor" in d.reason
    # 0.50 shrinks to 0.295: about 19 points, so the longshot is allowed.
    assert env.risk.check(OrderRequest("atl", "buy", "yes", 0.10, 20), 0.50, "high").ok


def _favorite_market(env, days=1.0, depth_qty="1000"):
    import datetime as dt

    end = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)
    env.client.meta["atl"]["endDate"] = end.isoformat().replace("+00:00", "Z")
    env.client.books["atl"]["bids"] = [{"px": px(0.93), "qty": depth_qty}]
    env.client.books["atl"]["offers"] = [{"px": px(0.94), "qty": depth_qty}]


def test_favorite_strategy_rules(env):
    import datetime as dt

    _favorite_market(env)
    fav = lambda n, price=0.94: OrderRequest("atl", "buy", "yes", price, n, strategy="favorite")
    # Mid 0.935: 0.995 shrinks to 0.965, about 2.1 points over price plus fee.
    assert env.risk.check(fav(5), 0.995, "high").ok
    assert "capped at $5.00" in env.risk.check(fav(6), 0.995, "high").reason
    assert "between 0.9" in env.risk.check(fav(5, price=0.89), 0.995, "high").reason
    assert "needs 0.020" in env.risk.check(fav(5), 0.97, "high").reason

    env.risk.record_order("favorite")
    env.risk.record_order("favorite")
    assert "2 favorite orders" in env.risk.check(fav(5), 0.995, "high").reason
    env.risk.favorites_this_run = env.risk.orders_this_run = 0

    _favorite_market(env, days=3)
    assert "allows 48" in env.risk.check(fav(5), 0.995, "high").reason

    _favorite_market(env)
    started = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    env.client.meta["atl"]["gameStartTime"] = started.isoformat().replace("+00:00", "Z")
    assert "live in-game" in env.risk.check(fav(5), 0.995, "high").reason
    del env.client.meta["atl"]["gameStartTime"]

    _favorite_market(env, depth_qty="100")
    assert "offered near the best ask" in env.risk.check(fav(5), 0.995, "high").reason


def test_favorite_exposure_is_capped_separately(env):
    _favorite_market(env)
    s = replace(env.settings, fav_max_total_usd=8)
    risk = RiskManager(s, env.broker, env.md)
    env.broker.place(OrderRequest("atl", "buy", "yes", 0.94, 5, strategy="favorite"))
    d = risk.check(OrderRequest("atl", "buy", "yes", 0.94, 5, strategy="favorite"), 0.995, "high")
    assert not d.ok and "favorite strategy exposure" in d.reason


def test_settlement_records_category_strategy_and_probability(env):
    env.broker.place(OrderRequest("atl", "buy", "yes", 0.42, 10, category="sports", probability=0.6))
    env.client.meta["atl"]["closed"] = True
    env.client.settle["atl"] = 1.0
    env.broker.sync()
    r = env.broker.state["resolved"][0]
    assert (r["category"], r["strategy"], r["probability"], r["outcome"]) == ("sports", "edge", 0.6, 1.0)
    assert env.broker.state["pnl_by"]["category:sports"] == pytest.approx(r["pnl"], abs=1e-3)
    assert r["pnl"] > 0


def test_track_record_and_usage_meter(env):
    from polyedge.agent import UsageMeter, track_record

    env.broker.place(OrderRequest("atl", "buy", "yes", 0.42, 10, category="sports", probability=0.6))
    env.client.meta["atl"]["closed"] = True
    env.client.settle["atl"] = 0.0
    env.broker.sync()
    rec = track_record(env.broker)["category:sports"]
    assert rec["resolved"] == 1 and rec["hit_rate"] == 0 and rec["brier"] == pytest.approx(0.36)
    assert rec["realized_pnl"] < 0

    m = UsageMeter()
    m.add(SimpleNamespace(input_tokens=1_000_000, output_tokens=0, cache_read_input_tokens=0,
                          cache_creation_input_tokens=0, server_tool_use=SimpleNamespace(web_search_requests=10)))
    assert m.cost_usd() == pytest.approx(4.10)
