# Run 20261030T124429Z (live)

I placed no orders this run. I can't add risk: open exposure is about 3× the $100 total cap and only $3.49 is free. I'm holding all three positions.

**What changed since the last run**
- Equity rose from $231.48 to $305.28, and P&L today is +$73.80. Almost all of it comes from the cricket bid rising from 0.28 to 0.48 (368.33 × 0.20 = $73.67). The rest is a $0.13 rise in cash, from $3.36 to $3.49, again with no fills. That's the second unexplained cash change in a row after last run's −$0.79, so it should be checked.
- I can't tell whether the weekly loss stop has cleared, because the portfolio only reports today's P&L, not the weekly total. That doesn't change anything this run. Exposure far above the total cap is enough to block new trades.
- South Africa turned the cricket match around. In session 2 of day 4 they were 252/5, 152 runs ahead with 5 wickets left, according to the Cricinfo scorecard. At lunch, AP reported South Africa "crawled to 202-5 to lead Australia by 102 runs."
- The two crossd markets still return a server error (fourth run in a row) and neither has a bid. I can't value or exit them.

**Cricket position (aec-testcr-sao-aus-2026-10-27, YES 368.33 @ 0.407)**
- Book: YES bid 0.48 (500 contracts) / ask 0.59 (511 contracts). Mid is 0.535 and the spread is 11¢, which is wide.
- Settlement rules: the market pays the winner, and a draw or tie with no official tie-breaker "will settle to $0.50."
- My estimate, assuming YES means South Africa: about 35% South Africa win, 30% draw, 35% Australia win. That values YES at roughly 0.35 + 0.5 × 0.30 = 0.50, with a plausible range of 0.42–0.58. Confidence is low. About 1.3 days of play remain on a worn pitch where Lyon is taking wickets. South Africa will probably bat on and set a target of 250+.
- Edge: after shrinking halfway to the mid, my figure becomes about 0.52, roughly 1.5 points below the 0.535 mid. There's no edge either way.
- **Decision: hold.** The reason for buying still stands: South Africa haven't lost, and their position has improved. Selling at the 0.48 bid would cost about 5.5¢ of spread for no edge.
- It's still not confirmed that YES means South Africa. The rules don't say, and I'm inferring it from South Africa being named first. The bid jumping as South Africa took the lead supports that reading.

**Quick Scan Table**
| Market | Mid | My Prob | Net Edge | Liq Score | Action | Size | Confidence |
|---|---|---|---|---|---|---|---|
| SA vs AUS 3rd Test (YES) | 0.535 | ~0.50 | none (≈ −1.5 pts after shrink) | Moderate (11¢ spread, about 500 contracts each side) | Hold | 0 | Low |
| crossd-51e9… | n/a | n/a | n/a | No book; lookup fails | Hold | 0 | — |
| crossd-ae68… | n/a | n/a | n/a | No book; lookup fails | Hold | 0 | — |

**No-Trade Declaration:** No trade. Reasons:
1. Exposure is about 3× the $100 total cap, and only $3.49 is free.
2. I can't confirm whether the weekly loss stop has cleared.
3. The cricket market shows no edge after the shrink.

I didn't scan for new markets because nothing I found could be traded.

**Needs a human (open items):**
1. Find out how the oversized positions got past the code-enforced limits. The worst is the 2,157-contract position at 0.046, about $100 against a $10 per-market cap and a 0.15 price floor.
2. Find out why free cash changed with no fills: −$0.79 last run, +$0.13 this run.
3. Confirm which team YES stands for in the SA vs AUS market. The match ends October 31.
4. Fix the server errors on the two crossd markets.
5. Add the weekly P&L figure to the portfolio report so the weekly loss stop can be checked.
