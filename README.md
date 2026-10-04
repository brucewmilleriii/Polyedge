# Polyedge

Polyedge is a Claude-driven trading agent for [Polymarket US](https://polymarket.us), the CFTC-regulated US exchange. On every run Claude reviews the portfolio, researches markets (including web search), and proposes limit orders. Before any order is sent, code checks it against hard risk limits.

It starts in **paper mode**. Paper mode reads live order books but only simulates fills, and it keeps its ledger in `state/`. Nothing real is traded until you explicitly switch to live mode.

## System prompt

Claude runs with the PolyEdge v2.1 prompt in `polyedge/prompts/polyedge_v2_1.md`. A short runner note is appended in `polyedge/agent.py`. It tells Claude the run is unattended, lists the tools, and explains that code enforces the limits below. Edit the markdown file to change the strategy. The limits stay in code regardless of what the prompt says.

## How a run works

1. Resting paper orders that the market has crossed are filled, and positions in closed markets are settled.
2. If the kill switch is on or today's loss limit is hit, the run stops.
3. Claude (`claude-opus-5-5`) is given the previous run's summary and works through a set of tools: `get_portfolio`, `list_markets`, `search_markets`, `get_market`, `check_event_consistency`, `place_order`, `cancel_order` and `web_search`.
4. `place_order` runs every request through `polyedge/risk.py`, then logs both the request and the outcome to `state/journal.jsonl`.
5. A summary of the run is written to `state/last_run.md`, and the run's token use and estimated API cost go to the journal.

## Strategy rules

These come from research into what persistently profitable Polymarket accounts do (`top-accounts-analysis.md` in the project files).

- **Entry-price floor.** The edge strategy can't buy anything priced below $0.15, because longshots are where the crowd overpays. Buying the NO side of an overpriced longshot is still allowed.
- **Shrink, then quarter Kelly.** Claude's full probability has to clear the edge gate. For sizing, the probability is first pulled halfway toward the market mid, and a buy can't exceed 0.25x Kelly on that shrunk number.
- **Cross-market consistency.** `check_event_consistency` sums the YES bids and asks across an event's outcome markets, so Claude can spot mutually exclusive outcomes that are mispriced against each other.
- **Hold to resolution.** A sell is rejected unless Claude marks `thesis_broken`.
- **No single-decision markets.** The prompt tells Claude to skip markets settled by one person's decision or a surprise announcement.
- **Track record.** Paper P&L, hit rate and Brier score are tracked by category and by strategy. Claude sees them on every run through `get_portfolio`, and `python -m polyedge status` prints them.
- **Favorites strategy (`strategy: "favorite"`), tracked separately.** It buys outcomes priced 0.92 or higher that resolve within 7 days, with at least $500 offered within 2¢ of the best ask. Each order is capped at $5 and the strategy at $30 total. It skips the confidence-tier edge minimums but still needs Claude's probability above price plus fee.

## Risk limits (enforced in code)

| Variable | Default | What it does |
|---|---|---|
| `POLYEDGE_MAX_ORDER_USD` | 10 | Max cost of a single buy |
| `POLYEDGE_MAX_MARKET_USD` | 25 | Max cost basis plus resting buys in any one market |
| `POLYEDGE_MAX_TOTAL_USD` | 100 | Max total cost basis plus resting buys |
| `POLYEDGE_MAX_MARKET_PCT` | 0.05 | Per-market cap as a share of equity; the stricter of this and the dollar cap applies |
| `POLYEDGE_MAX_CLUSTER_PCT` | 0.15 | Cap on everything in one event (correlated markets), as a share of equity |
| `POLYEDGE_KELLY_MULTIPLIER` | 0.25 | A buy can't exceed this fraction of full Kelly (computed with the fee included) |
| `POLYEDGE_SHRINK` | 0.5 | How far Claude's probability counts versus the market mid when sizing (0 = market only, 1 = Claude only) |
| `POLYEDGE_MAX_DAILY_LOSS_USD` | 25 | Stop the run once equity is this far below today's open (UTC) |
| `POLYEDGE_MAX_WEEKLY_LOSS_USD` | 50 | Stop the run once equity is this far below this week's open |
| `POLYEDGE_MAX_ORDERS_PER_RUN` | 3 | Max orders per run |
| `POLYEDGE_MIN_EDGE` | 0.05 | Floor on edge after fees; the stated confidence raises it to 5 / 8 / 12 points for high / medium / low |
| `POLYEDGE_MIN_PRICE` / `POLYEDGE_MAX_PRICE` | 0.15 / 0.97 | Entry-price floor for the edge strategy, and the highest price anything can be bought at |
| `POLYEDGE_FAV_MIN_PRICE`, `_FAV_MAX_DAYS`, `_FAV_MIN_DEPTH_USD`, `_FAV_MAX_ORDER_USD`, `_FAV_MAX_TOTAL_USD` | 0.92, 7, 500, 5, 30 | Favorites strategy rules |
| `POLYEDGE_CATEGORIES` | all | Comma-separated allowlist, for example `sports` |
| `POLYEDGE_KILL` or a `KILL` file in the repo root | off | Blocks all buys |

Other rules: buys need a probability estimate, you can't hold both YES and NO in one market, sells are limited to contracts you hold and need `thesis_broken`, and every order is a limit order.

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

`.github/workflows/trade.yml` runs every 30 minutes and commits `state/` back to the repo, so the paper ledger persists between runs. GitHub sometimes starts scheduled runs late or skips one when it's busy. If the cost is too high, change the `cron` line.

1. Add the repository secret `ANTHROPIC_API_KEY`.
2. Optionally set repository variables (Settings → Secrets and variables → Actions → Variables) for any of the limits above.
3. Trigger it once by hand from the Actions tab (`trade` → Run workflow) and read `state/last_run.md`.

Each run makes several Claude calls plus up to 8 web searches. The estimated cost of every run is written to the journal, and `python -m polyedge status` prints the last 24 hours of spend.

### 3. Going live (only after paper results justify it)

1. Install the Polymarket US app, complete KYC, and fund the account. Polymarket US is not available in every state.
2. Create an API key at [polymarket.us/developer](https://polymarket.us/developer). The secret is shown once.
3. Add the repository secrets `POLYMARKET_KEY_ID` and `POLYMARKET_SECRET_KEY`.
4. **Verify NO-side pricing with one tiny manual order first.** Polymarket US documents that order prices refer to the YES side. Polyedge therefore sends a NO buy at `p` as `ORDER_INTENT_BUY_SHORT` with YES price `1 - p` (see `LiveBroker.place`). Confirm this on a 1-contract order before trusting it with size. Also check that `portfolio.positions()` reports NO holdings as negative `netPosition`, as `LiveBroker.positions` assumes.
5. Set the repository variable `POLYEDGE_MODE=live`.

To stop trading immediately, set the repository variable `POLYEDGE_KILL=1` or commit a `KILL` file.

## Judging whether it works

Paper-trade for at least a few weeks and dozens of resolved markets. Then compare `python -m polyedge status` against simply holding cash, and use the `probability` values in `state/journal.jsonl` to check whether Claude's estimates were calibrated against outcomes. Without a measurable edge in paper mode, don't go live.
