# Run 20261004T152821Z (paper)

# Run 20261004T1528Z (paper)

I placed three resting buy orders on MLB Game 3 "+1.5 run" spread markets. None has filled yet. Paper cash is $500, I hold no positions, and $28.78 is committed in open orders.

### Changes since last run
- **Alaska Senate (Dem):** price unchanged (Dem 0.71 / Rep 0.29). I'm still watching only.
- **New mispricing found:** in all four division series Game 3s, the "+1.5 runs" spread markets are mispriced. The only bids sit at roughly the moneyline price (the chance the team wins outright). The asks are fixed at 0.93, which looks like a placeholder from a market maker. A team covers +1.5 if it wins outright or loses by exactly one run, so +1.5 has to be worth more than the moneyline. About 30% of MLB losses are by one run, so fair value is about the moneyline plus 0.30 × (1 − moneyline).

### Quick Scan Table
| Market | Mid | My Prob | Net Edge (after shrink and fee) | Liq Score | Action | Size | Confidence |
|---|---|---|---|---|---|---|---|
| LAD +1.5 vs ATL (G3, Oct 6) | 0.74 (0.55/0.93) | 0.68 | +9.6 pts at 0.60 | Low (placeholder ask) | BUY YES limit 0.60, resting | 16 ($9.60) | Med |
| CLE +1.5 vs CWS (G3, Oct 7) | 0.715 | 0.645 | +9.6 pts at 0.565 | Low | BUY YES limit 0.565, resting | 17 ($9.61) | Med |
| MIL +1.5 vs SD (G3, Oct 6) | 0.695 | 0.615 | +9.3 pts at 0.535 | Low | BUY YES limit 0.535, resting | 18 ($9.63) | Med |
| TB +1.5 vs NYY (G3) | 0.69 | ~0.61 | ~+10 pts at 0.53 | Low | None (out of order slots) | 0 | Med |
| Texas Senate Dem (Talarico) | 0.64 | ~0.58 (0.50–0.66) | <0 | High | None | 0 | Med |
| TX county markets (Tarrant D 0.88, Collin D 0.64, Denton D 0.57) | — | ~fair compared with statewide | <3 pts | Thin | None | 0 | Low |
| ME Senate margin and turnout ladders | — | — | — | No real book | None | 0 | — |
| WS champion vs. pennant ladder (LAD 0.364/0.497) | — | LAD ~0.31 to win the WS | ~2.5 pts | Medium | None | 0 | Low |

### Full Trade Thesis: MLB Game 3 +1.5 run spreads (3 orders, same reasoning)
- **Settlement rule:** settles YES "if the [team] cover a +1.5 run spread", extra innings count, and the outcome comes from MLB. Game 3 is played regardless of the series score, and the postponement fallback is standard. The wording is clear.
- **How I get my probability:** P(+1.5) = P(team wins) + P(team loses by exactly 1). I take P(win) from the deep moneyline books: LAD's is 0.545/0.555 with 500+ contracts at each level. About 30% of MLB losses are by one run, and the playoff share is similar or a bit higher. That gives fair values of LAD 0.68, CLE 0.645 and MIL 0.615.
- **Case against:** a late starting-pitcher change could move the moneyline. Anyone who sells into my bid may know something I don't. And if one-run games are less common than I assume (25%), each fair value drops about 2 points.
- **Book:** the bids are 0.55, 0.50 and 0.46 with about 660–780 contracts each, and every ask is 0.93. Every price I could take now is overpriced: the opposite side of each spread asks about 0.45–0.55, against a fair value near 0.31–0.39. So the only trade is to rest a bid myself.
- **Edge:** using LAD as the example, p_used = 0.74 + 0.5 × (0.68 − 0.74) = 0.71, and 0.71 − 0.60 − 0.017 fee = **+9.6 points**. That clears the 8-point minimum for medium confidence. The other two orders come to +9.6 and +9.3 points.
- **Sizing:** quarter Kelly works out to about $35 per order, so the $10 per-order cap applies. Total is $28.84. All three are in the MLB cluster, which allows up to $75.
- **Orders:** limit buys at 0.60, 0.565 and 0.535. They stay open until each game starts.
- **When I'd cancel:** if a team's moneyline moves more than 5 points before the game, or the starting pitcher changes, I'll re-price and cancel any bid that no longer has 8 points of edge. If filled, I hold to settlement.
- **Portfolio:** if all three fill, total exposure is $28.84 of the $100 cap. Their outcomes are close to independent of each other.

### No-Trade Declarations
- **Texas Senate Dem at 0.64:** No trade. Reason: no edge. James Talarico leads Ken Paxton 47% to 46% in the TSU poll, and TPOR has Talarico's lead over Paxton narrowed by one point (net +6 to +5). Texas polls have overstated Democrats before, so my 0.58 is at or below the market.
- **TB +1.5:** No trade this run. Reason: I'd used all three order slots. It's the first candidate for next run if the book hasn't changed.
- **TX county markets, ME ladders, Alaska turnout:** No trade. Reason: the books are thin or just leftover quotes, or the edge is under 3 points.
- **WS champion vs. pennant ladder:** No trade. Reason: the Dodgers' WS price implies about a 74% chance of winning the WS if they take the pennant, which looks rich. But after the shrink the edge on LAD WS NO is only about 2.5 points.
- **Alaska Senate Dem NO:** No trade. Reason: unchanged since last run, with about 3.8 points of edge against 8 needed.

### Risk state
I have $28.84 in resting orders against the $100 cap, with no positions and nothing filled. The loss stops haven't been touched. I used all three orders this run.

### Next run
1. Check fills on the three spread bids. Re-check the moneylines and probable starters, and cancel any bid whose edge falls below 8 points.
2. Post TB +1.5 at 0.53 if the book is still the same.
3. Look at the midterm races I haven't covered (MI, NC, GA, NH). Alaska stays on watch for NO at 0.25 or lower.
