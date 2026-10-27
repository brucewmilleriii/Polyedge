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
        max_daily_loss_usd=25,
        max_weekly_loss_usd=50,
        max_price=0.97,
        paper_starting_cash=500.0,
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
    assert "turned off" in env.risk.check(
        OrderRequest("atl", "buy", "yes", 0.94, 5, strategy="favorite"), 0.995, "high"
    ).reason
    env.risk.s = replace(env.settings, fav_enabled=True, max_price=0.97)
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
    s = replace(env.settings, fav_max_total_usd=8, fav_enabled=True, max_price=0.97)
    risk = RiskManager(s, env.broker, env.md)
    env.broker.place(OrderRequest("atl", "buy", "yes", 0.94, 5, strategy="favorite"))
    d = risk.check(OrderRequest("atl", "buy", "yes", 0.94, 5, strategy="favorite"), 0.995, "high")
    assert not d.ok and "favorite strategy exposure" in d.reason


def test_new_defaults_cap_price_at_85_cents(env):
    s = Settings()
    assert (s.max_order_usd, s.max_market_usd, s.max_total_usd) == (5.0, 10.0, 50.0)
    assert s.paper_starting_cash == 200.0 and not s.fav_enabled
    risk = RiskManager(replace(env.settings, max_price=0.85), env.broker, env.md)
    assert "at most 0.85" in risk.check(OrderRequest("atl", "buy", "yes", 0.86, 5), 0.99, "high").reason


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


def test_dashboard_renders_from_state(tmp_path):
    from polyedge.config import Settings
    from polyedge.dashboard import render

    (tmp_path / "journal.jsonl").write_text(
        '{"ts": "2026-10-04T06:40:23+00:00", "run": "r1", "mode": "paper", "kind": "usage", "est_cost_usd": 0.3}\n'
    )
    (tmp_path / "live_check.json").write_text('{"auth": "ok", "account": {"funded": false, "balance": 123}}')
    out = render(Settings(state_dir=tmp_path), tmp_path / "d.html")
    html = out.read_text()
    assert "/*__POLYEDGE_DATA__*/" not in html
    assert '"est_cost_usd"' not in html and '"cost": 0.3' in html
    assert "123" not in html


# -- BTC Up/Down closing-minutes strategy ---------------------------------------

def _crypto_env(env, yes_bid=0.88, yes_ask=0.90, secs_left=60):
    import datetime as dt

    from polyedge.crypto_updown import CryptoTrader, current_window, market_slug

    now = dt.datetime(2026, 10, 27, 3, 40, tzinfo=dt.timezone.utc).timestamp() - secs_left
    start, end = current_window("5m", now)
    slug = market_slug("btc", "5m", start)
    env.client.meta[slug] = {
        "slug": slug, "category": "crypto", "active": True, "closed": False,
        "assetPriceTerms": {"windowEnd": end.isoformat().replace("+00:00", "Z")},
    }
    env.client.books[slug] = {
        "marketSlug": slug,
        "bids": [{"px": px(yes_bid), "qty": "500"}],
        "offers": [{"px": px(yes_ask), "qty": "500"}],
    }
    settings = replace(env.settings, crypto_max_order_usd=10, max_total_usd=50, crypto_assets=("btc",))
    journal = Journal(env.settings.state_dir, "t", "paper")
    risk = RiskManager(settings, env.broker, env.md)
    trader = CryptoTrader(settings, env.md, env.broker, risk, journal, clock=lambda: now, sleep=lambda s: None)
    return trader, slug


def test_crypto_slug_and_window():
    import datetime as dt

    from polyedge.crypto_updown import current_window, market_slug

    now = dt.datetime(2026, 10, 27, 3, 37, 19, tzinfo=dt.timezone.utc).timestamp()
    start, end = current_window("5m", now)
    assert market_slug("btc", "5m", start) == "cpc-btc-updown-5m-2026-10-27-0335z"
    assert end.minute == 40
    assert market_slug("eth", "5m", start) == "cpceth-eth-updown-5m-2026-10-27-0335z"


def test_crypto_buys_up_when_up_is_the_favorite(env):
    trader, slug = _crypto_env(env, yes_bid=0.88, yes_ask=0.90)
    trader.step()
    (pos,) = env.broker.positions()
    assert (pos.slug, pos.side, pos.qty) == (slug, "yes", 11)  # $10 at 0.90
    trader.step()  # one trade per window
    assert len(trader.trades) == 1


def test_crypto_buys_down_when_down_is_the_favorite(env):
    trader, slug = _crypto_env(env, yes_bid=0.08, yes_ask=0.10)  # Down asks 0.92
    trader.step()
    (pos,) = env.broker.positions()
    assert pos.side == "no" and pos.qty == 10


def test_crypto_waits_outside_window_or_price_band(env):
    trader, _ = _crypto_env(env, secs_left=200)  # before the last 2 minutes
    trader.step()
    assert not env.broker.positions()
    trader, _ = _crypto_env(env, yes_bid=0.60, yes_ask=0.62)  # neither side at 85+
    trader.step()
    assert not env.broker.positions() and not trader.done
    trader, _ = _crypto_env(env, yes_bid=0.98, yes_ask=0.99)  # above the 0.97 ceiling
    trader.step()
    assert not env.broker.positions()


def test_crypto_respects_loss_stop(env):
    trader, _ = _crypto_env(env)
    trader.s = trader.risk.s = replace(trader.s, max_daily_loss_usd=10)
    trader.risk.start_of_day_equity(env.broker.total_cash())
    env.broker.state["cash"] -= 15  # down $15 today
    trader.step()
    assert not env.broker.positions()


def test_crypto_records_closing_prices_and_outcome(env):
    import json

    trader, slug = _crypto_env(env, yes_bid=0.88, yes_ask=0.90)
    trader.s = replace(trader.s, crypto_assets=("btc",))
    trader.step()
    env.client.settle[slug] = 1.0
    end = trader.watch[slug]["end"]
    trader.clock = lambda: end + 60
    trader.record_outcomes()
    (row,) = [json.loads(l) for l in trader.markets_path.read_text().splitlines()]
    assert row["outcome"] == "up" and row["traded"] == "up"
    assert {s["at"] for s in row["snaps"]} == {60} and row["snaps"][0]["up_ask"] == 0.90


def test_crypto_skips_wide_books_and_reports(env):
    import json

    from polyedge.crypto_report import render
    from polyedge.crypto_updown import pick_side

    wide = {"bids": [{"px": px(0.03), "qty": "10"}], "offers": [{"px": px(0.97), "qty": "10"}]}
    assert pick_side(wide, 0.85, 0.97, 0.25) is None  # Up asks 0.97 and Down asks 0.97
    tight = {"bids": [{"px": px(0.88), "qty": "10"}], "offers": [{"px": px(0.90), "qty": "10"}]}
    assert pick_side(tight, 0.85, 0.97, 0.25) == ("yes", 0.90)

    d = env.settings.state_dir
    (d / "journal.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"kind": "order_request", "slug": "m1", "side": "no", "price": 0.9, "secs_left": 100},
        {"kind": "order_status", "slug": "m1", "filled": 10.0},
    ]) + "\n")
    (d / "markets.jsonl").write_text(json.dumps(
        {"slug": "m1", "outcome": "down", "snaps": [{"at": 120, "up_ask": 0.11, "down_ask": 0.9}]}) + "\n")
    out = render(d)
    assert "1 won, 0 lost" in out and "| 120 | – | 1/1 (100%) | – |" in out


def test_new_loss_stop_defaults():
    s = Settings()
    assert (s.max_daily_loss_usd, s.max_weekly_loss_usd) == (100.0, 100.0)
    assert s.crypto_max_order_usd == 10.0 and s.crypto_min_price == 0.85
