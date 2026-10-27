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

- **Shrink first.** Before any check, Claude's probability is pulled halfway toward the market mid: `p_used = mid + 0.5 × (p_claude − mid)`. The edge minimums (5 / 8 / 12 points for high / medium / low confidence) and quarter-Kelly sizing both use `p_used`.
- **Entry-price floor.** Anything under $0.15 needs at least 15 points of edge on `p_used`, because longshots are where the crowd overpays. Buying NO on an overpriced longshot is the usual alternative.
- **Linked-market scan.** On every run Claude checks for inconsistencies between linked markets: mutually exclusive outcomes far from summing to 100% (`check_event_consistency`), state against national races, game against series, and "by date A" against "by date B" ladders. It confirms that the resolution wording matches before trading.
- **Hold to resolution.** A sell is rejected unless Claude marks `thesis_broken`.
- **No single-decision markets.** The prompt tells Claude to skip markets settled by one person's decision or a secret announcement (strikes, arrests, appointments, awards).
- **Track record.** Every order is tagged with a category and a strategy. Paper P&L, hit rate and Brier score are written to `state/performance.json` on every run, shown to Claude through `get_portfolio`, and printed by `python -m polyedge status`.
- **Favorites strategy (`strategy: "favorite"`, off by default, paper only, tracked separately).** Set `POLYEDGE_FAV_ENABLED=1` and raise `POLYEDGE_MAX_PRICE` to 0.97 to turn it back on. It buys YES or NO priced 0.90 to 0.97 that resolves within 48 hours, with at least $500 offered within 2¢ of the best ask. It needs at least 2 points of edge after fees on `p_used`. Limits: $5 per order, 2 orders per run, $30 total, and every other cap still applies. Live in-game sports markets are excluded.

## Risk limits (enforced in code)

| Variable | Default | What it does |
|---|---|---|
| `POLYEDGE_MAX_ORDER_USD` | 5 | Max cost of a single buy |
| `POLYEDGE_MAX_MARKET_USD` | 10 | Max cost basis plus resting buys in any one market |
| `POLYEDGE_MAX_TOTAL_USD` | 50 | Max total cost basis plus resting buys |
| `POLYEDGE_MAX_MARKET_PCT` | 0.05 | Per-market cap as a share of equity; the stricter of this and the dollar cap applies |
| `POLYEDGE_MAX_CLUSTER_PCT` | 0.15 | Cap on everything in one event (correlated markets), as a share of equity |
| `POLYEDGE_KELLY_MULTIPLIER` | 0.25 | A buy can't exceed this fraction of full Kelly (computed with the fee included) |
| `POLYEDGE_SHRINK` | 0.5 | Weight on Claude's probability versus the market mid for every edge and sizing check (0 = market only, 1 = Claude only) |
| `POLYEDGE_MAX_DAILY_LOSS_USD` | 10 | Stop the run once equity is this far below today's open (UTC) |
| `POLYEDGE_MAX_WEEKLY_LOSS_USD` | 20 | Stop the run once equity is this far below this week's open |
| `POLYEDGE_MAX_ORDERS_PER_RUN` | 3 | Max orders per run |
| `POLYEDGE_MIN_EDGE` | 0.05 | Floor on edge after fees on the shrunk probability; the stated confidence raises it to 5 / 8 / 12 points for high / medium / low |
| `POLYEDGE_LONGSHOT_MIN_EDGE` | 0.15 | Edge needed to buy below the entry-price floor |
| `POLYEDGE_MIN_PRICE` / `POLYEDGE_MAX_PRICE` | 0.15 / 0.85 | Entry-price floor for the edge strategy, and the highest price anything can be bought at |
| `POLYEDGE_FAV_MIN_PRICE`, `_FAV_MAX_HOURS`, `_FAV_MIN_EDGE`, `_FAV_MIN_DEPTH_USD`, `_FAV_MAX_ORDER_USD`, `_FAV_MAX_ORDERS_PER_RUN`, `_FAV_MAX_TOTAL_USD` | 0.90, 48, 0.02, 500, 5, 2, 30 | Favorites strategy rules |
| `POLYEDGE_FAV_ENABLED` | off | Set to 1 to allow the favorites strategy |
| `POLYEDGE_PAPER_STARTING_CASH` | 200 | Cash a new paper ledger starts with |
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

`.github/workflows/trade.yml` runs every 2 hours and commits `state/` back to the repo, so the paper ledger persists between runs. GitHub sometimes starts scheduled runs late or skips one when it's busy. If the cost is too high, change the `cron` line.

1. Add the repository secret `ANTHROPIC_API_KEY`.
2. Optionally set repository variables (Settings → Secrets and variables → Actions → Variables) for any of the limits above.
3. Trigger it once by hand from the Actions tab (`trade` → Run workflow) and read `state/last_run.md`.

Each run makes several Claude calls plus up to 8 web searches. The estimated cost of every run is written to the journal, and `python -m polyedge status` prints the last 24 hours of spend.

### 3. Going live (only after paper results justify it)

1. Install the Polymarket US app, complete KYC, and fund the account. Polymarket US is not available in every state.
2. Create an API key at [polymarket.us/developer](https://polymarket.us/developer). The secret is shown once.
3. Add the repository secrets `POLYMARKET_KEY_ID` and `POLYMARKET_SECRET_KEY`.
4. Run the `live-check` workflow from the Actions tab. It confirms the keys authenticate and previews, without placing, 1-contract YES and NO orders, then writes the result to `state/live_check.json`. The NO-side convention was confirmed this way on 2026-10-04: a `BUY_SHORT` at YES-terms price `1 - p` rests on the book as a YES sell at `1 - p`, which is a NO buy at `p`.
5. Set the repository variable `POLYEDGE_MODE=live`.

To stop trading immediately, set the repository variable `POLYEDGE_KILL=1` or commit a `KILL` file.

## Judging whether it works

Paper-trade for at least a few weeks and dozens of resolved markets. Then compare `python -m polyedge status` against simply holding cash, and use the `probability` values in `state/journal.jsonl` to check whether Claude's estimates were calibrated against outcomes. Without a measurable edge in paper mode, don't go live.
