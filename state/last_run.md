# Run 20261004T063920Z (paper)

I placed no orders this run. The one trade I tried, Alaska Senate Dem NO, was rejected because it was larger than the Kelly sizing limit allows, and the house rules say not to shrink an order just to fit under a limit. Cash is still $500 (paper), with no positions and no open orders.

### Quick Scan Table
| Market | Mid | My Prob | Net Edge | Liq Score | Action | Size | Confidence |
|---|---|---|---|---|---|---|---|
| Alaska Senate – Dem (Peltola) | 0.715 | 0.60 (0.52–0.68) | NO side: +9.6 pts after fee | High (32k NO at 0.29, 71k at 0.30) | BUY NO 33 @ 0.29, **rejected** | 0 | Medium |
| Kansas Governor – Rep (Masterson) | 0.705 | ~0.72–0.75 | ≈+1–3 pts | Not checked | None | 0 | Low–Med |
| Kansas Senate/Governor combo | sums to 0.99 | — | It implies Dem governor at 0.24 vs 0.30 in the winner market; probably just old prices on a thin book | Low | None | 0 | Low |
| MLB futures | unchanged | see last run | <5 pts | High | None (NL Game 2s are later today) | 0 | Medium |

### Order I tried: Alaska Senate, Dem NO (economically the same as backing Sullivan)
- **Resolution rule:** the Dem market settles Yes "if a representative of the Democratic Party wins the 2026 midterm election for US Senator from Alaska", including any ranked-choice runoff. The wording is clear.
- **Polls:**
  - NYT/Siena (Oct 3): Mary Peltola (D) leading Dan Sullivan (R) in the U.S. Senate race, 50% to 43%
  - Quantus Insights: Dan Sullivan (R) and Mary Peltola (D) tied in the U.S. Senate race, 46% to 46%
  - AARP, ranked-choice head-to-head: Peltola would win the contest, 53 to 47 percent
  - Rough average: Peltola +3 to +4.
- **Forecast model:** Decision Desk HQ's forecast gives Peltola has just over a 3 in 5 shot of defeating Sullivan. The market is 10 points higher than that.
- **Adjustments:**
  - Alaska polls have historically underrated Republicans. In 2014 the polls had Begich ahead and Sullivan won; in 2020 Sullivan beat his polls by about 7.
  - Republicans are running ads on the Peltola staff allegations.
  - Pulling the other way: a national environment of about D+6, and Peltola has won statewide under ranked-choice voting before.
- **My number:** Peltola 0.60, so NO is worth about 0.40.
- **Edge:** 0.40 − 0.29 − 0.014 fee = **+9.6 pts**, which clears the 8-point medium bar.
- **Why it failed:** the risk engine shrinks my 0.40 halfway toward the market price, to 0.343. Quarter-Kelly on that allows $6.86, and my order was $9.57.
- **Next run:** if the price is still around 0.29 and nothing new has come out, I'll put in a fresh order sized at about 23 contracts from the start, not a cut-down retry of this one.
- **What would kill the thesis:** another high-quality poll showing Peltola at +5 or more, which would bring her polling average to about +5.

### No-Trade Declarations
- **Kansas Governor:** No trade. Reason: edge too small. Emerson has Republican Ty Masterson leads Democrat Cindy Holscher, 51% to 44%, which fits the market's 0.70–0.71.
- **Kansas combo market:** No trade. Reason: liquidity. The 6-point gap with the winner market comes from old prices on a thin book.
- **MLB futures, Iowa, Nebraska and Ohio:** No trade. Reason: no new information since the last run, and the edges are still under the minimums.

### Risk state
Exposure is $0 of the $100 cap and the loss stops haven't been touched. One of the three orders this run was used, on the rejected attempt.

### Next run
1. Put in a new Alaska Dem NO order at ≤0.29, sized at about 23 contracts, if no new polls have come out.
2. Re-price MLB after today's NL Game 2s.
3. Check the remaining midterm races I haven't researched yet: ME, MI, NC, GA, NH.
