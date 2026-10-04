# Polyedge

Polyedge is a Claude-driven trading agent for [Polymarket US](https://polymarket.us), the CFTC-regulated US exchange. On every run Claude reviews the portfolio, researches markets (including web search), and proposes limit orders. Before any order is sent, code checks it against hard risk limits.

It starts in **paper mode**. Paper mode reads live order books but only simulates fills, and it keeps its ledger in `state/`. Nothing real is traded until you explicitly switch to live mode.

## How a run works

1. Resting paper orders that the market has crossed are filled, and positions in closed markets are settled.
2. If the kill switch is on or today's loss limit is hit, the run stops.
3. Claude (`claude-opus-5-5`) works through a set of tools: `get_portfolio`, `list_markets`, `search_markets`, `get_market`, `place_order`, `cancel_order` and `web_search`.
4. `place_order` runs every request through `polyedge/risk.py`, then logs both the request and the outcome to `state/journal.jsonl`.
5. A summary of the run is written to `state/last_run.md`.

## Risk limits (enforced in code)

| Variable | Default | What it does |
|---|---|---|
| `POLYEDGE_MAX_ORDER_USD` | 10 | Max cost of a single buy |
| `POLYEDGE_MAX_MARKET_USD` | 25 | Max cost basis plus resting buys in any one market |
| `POLYEDGE_MAX_TOTAL_USD` | 100 | Max total cost basis plus resting buys |
| `POLYEDGE_MAX_DAILY_LOSS_USD` | 25 | Stop the run once equity is this far below today's open (UTC) |
| `POLYEDGE_MAX_ORDERS_PER_RUN` | 3 | Max orders per run |
| `POLYEDGE_MIN_EDGE` | 0.05 | Claude's probability must beat price plus taker fee by this much |
| `POLYEDGE_MIN_PRICE` / `POLYEDGE_MAX_PRICE` | 0.03 / 0.97 | No lottery tickets and no picking up pennies |
| `POLYEDGE_CATEGORIES` | all | Comma-separated allowlist, for example `sports` |
| `POLYEDGE_KILL` or a `KILL` file in the repo root | off | Blocks all buys |

Other rules: buys need a probability estimate, you can't hold both YES and NO in one market, sells are limited to contracts you hold, and every order is a limit order.

## Setup

### 1. Run it locally in paper mode

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
export ANTHROPIC_API_KEY=sk-ant-...
python -m polyedge run
python -m polyedge status
```

Paper mode needs no Polymarket account, because market data is public.

### 2. Run it on a schedule with GitHub Actions

`.github/workflows/trade.yml` runs every 2 hours and commits `state/` back to the repo, so the paper ledger persists between runs.

1. Add the repository secret `ANTHROPIC_API_KEY`.
2. Optionally set repository variables (Settings → Secrets and variables → Actions → Variables) for any of the limits above.
3. Trigger it once by hand from the Actions tab (`trade` → Run workflow) and read `state/last_run.md`.

Each run makes several Claude calls plus up to 8 web searches. Watch your API spend for a few days before you increase the frequency.

### 3. Going live (only after paper results justify it)

1. Install the Polymarket US app, complete KYC, and fund the account. Polymarket US is not available in every state.
2. Create an API key at [polymarket.us/developer](https://polymarket.us/developer). The secret is shown once.
3. Add the repository secrets `POLYMARKET_KEY_ID` and `POLYMARKET_SECRET_KEY`.
4. **Verify NO-side pricing with one tiny manual order first.** Polymarket US documents that order prices refer to the YES side. Polyedge therefore sends a NO buy at `p` as `ORDER_INTENT_BUY_SHORT` with YES price `1 - p` (see `LiveBroker.place`). Confirm this on a 1-contract order before trusting it with size. Also check that `portfolio.positions()` reports NO holdings as negative `netPosition`, as `LiveBroker.positions` assumes.
5. Set the repository variable `POLYEDGE_MODE=live`.

To stop trading immediately, set the repository variable `POLYEDGE_KILL=1` or commit a `KILL` file.

## Judging whether it works

Paper-trade for at least a few weeks and dozens of resolved markets. Then compare `python -m polyedge status` against simply holding cash, and use the `probability` values in `state/journal.jsonl` to check whether Claude's estimates were calibrated against outcomes. Without a measurable edge in paper mode, don't go live.
