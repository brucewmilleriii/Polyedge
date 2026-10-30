# Run 20261030T053742Z (live)

I placed no orders this run. The weekly loss stop is still breached, only $3.36 is free, and open exposure is about $275 against a $100 total cap.

**Portfolio (equity $231.48, P&L today $0.00 because the daily counter reset)**
- Equity fell $4.47 since the last run, mostly because the cricket bid dropped from 0.29 to 0.28.
- **Free cash dropped $0.79, from $4.15 to $3.36, with no fills and no open orders.** I don't know why. It could be a fee or a settlement adjustment, but someone should check it.
- The weekly loss stop is still breached. Today's P&L reset to zero, but the weekly loss window has not reset, so new risk is still suspended.
- The over-cap positions are unchanged. The longshot position (2,157 contracts at 0.046, about $100) breaks the $10 per-market cap and the 0.15 price floor.

**Positions**
- **aec-testcr-sao-aus-2026-10-27 (YES, 368.33 @ 0.407; bid 0.28 / ask 0.33, 379 contracts at the ask).** At stumps on day 3, South Africa were 329 and 140/4, a lead of 40 runs. Cricinfo calls it "Inglis century, Starc strikes hand Australia the advantage," and says Lyon's late wicket left South Africa "effectively 40 for 4." That makes Australia favourites, with a draw still possible over two days. A draw would settle at $0.50, above the current 0.28–0.33 market. My rough estimate for YES, assuming YES stands for South Africa, is about 0.25–0.30, close to the market. So there's no edge, and I couldn't act on one anyway.
  - The hold rule allows a sell only if the reason for buying has been disproved. It hasn't: the match is undecided, South Africa haven't lost, and selling at 0.28 would lock in a loss with no edge. **Holding.**
  - It's still not confirmed which team YES stands for. The rules don't say, and I'm assuming South Africa because they're named first.
- **crossd-51e9ddba4c918582 and crossd-ae6858b4ce7ba2ba:** Looking them up failed with a server error for the third run in a row. Neither has a bid, so I can't see the rules, value them or sell them. **Holding.**

**Quick Scan Table**
| Market | Mid Price | My Prob | Net Edge | Liq Score | Action | Size | Confidence |
|---|---|---|---|---|---|---|---|
| SA vs AUS 3rd Test (YES) | 0.305 | ~0.27 | none (≈ −1 to −2 pts after shrink) | Moderate (5¢ spread) | Hold | 0 | Low |
| crossd-51e9… | n/a | n/a | n/a | No book; lookup fails | Hold | 0 | — |
| crossd-ae68… | n/a | n/a | n/a | No book; lookup fails | Hold | 0 | — |

**No-Trade Declaration:** No trade. Reasons: (1) the weekly loss stop is breached; (2) only $3.36 is free; (3) exposure is about 2.75× the total cap; (4) the cricket market shows no edge. I didn't scan for new markets because I couldn't trade anything I found.

**Needs a human (still open, plus one new item):**
1. Find out how the oversized positions got past the code-enforced per-market, total and price-floor limits.
2. Find out why $0.79 of cash disappeared between runs.
3. Confirm which team YES stands for in the SA vs AUS market. Day 4 is underway now, and the match can settle by October 31.
4. Fix the server errors on the two crossd markets. Without them, those positions can't be valued or exited.
