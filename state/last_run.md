# Run 20261030T234101Z (live)

I placed no orders this run. Open exposure at cost is still about **$200 against the $100 total cap**, so any new order would be rejected.

**What changed since the last run**
- **crossd-0c2a37f9… is gone and cash rose by exactly its contract count.** Last run it was held as 98.32 YES at 0.5085. Free cash went from $43.97 to $142.29, up $98.32, which is $1 per contract. That fits the market settling YES, worth about +$48.3 against its ~$50 cost. Unlike last run, the cash change has a plausible explanation. I still can't confirm it: the market returns a server error and there's no settlement record.
- **The three other crossd positions are still held and still can't be valued or exited** (the order book returns server errors, no bid):
  - crossd-51e9: 2,156.69 YES at 0.0464, about $100 cost
  - crossd-98e7: 220.85 YES at 0.2264, about $50 cost
  - crossd-ae68: 48.75 YES at 0.5128, about $25 cost
- **Account numbers:** equity is $334.86, and the reported P&L today is +$103.38. The P&L is up $48.32 from last run's +$55.06, which matches the crossd-0c2a settlement gain. Equity rose by the same $48.32, since last run's figure was $286.54. The track record is still empty, so I have no calibration data.

**Holdings review**
- **Georgia Senate, Republican YES:** 586 contracts at 0.0427. The book is 0.03 bid / 0.04 ask, with 1.58M contracts bid at 0.03, so the market still gives the Republican about 3.5%. I didn't place this position and have no thesis that new information could break, so under hold-to-resolution I'm holding it. Marked at the bid it's a loss of about $7.4. The election is Nov 3; a Dec 1 runoff is possible, and the market's end date is Jan 15.
- **crossd ×3:** holding, since there's no book to exit into.

**Quick Scan Table**
| Market | Mid | My Prob | Net Edge | Liq Score | Action | Size | Confidence |
|---|---|---|---|---|---|---|---|
| GA Senate R YES (held) | 0.035 | not estimated | n/a | Very deep | Hold | 0 | — |
| crossd-51e9 / 98e7 / ae68 (held) | n/a | n/a | n/a | No book; server error | Hold | 0 | — |
| crossd-0c2a | — | — | — | — | Apparently settled YES (not confirmed) | — | — |

**No-Trade Declaration:** No trade. Exposure at cost (about $200) is twice the $100 total cap, so any order would be rejected. I didn't scan for new markets or check other markets for pricing gaps, because I couldn't act on anything I found.

**Needs a human (still open)**
1. Confirm that crossd-0c2a settled YES; the matching cash increase points that way. Fix the server errors on the crossd markets, which hold about $175 of cost that can't be valued.
2. Explain how positions got past the code-enforced limits: the 2,157-contract crossd-51e9 position (about $100) and the Georgia position under the 0.15 price floor. Last run's unexplained changes are still not reconciled: the cricket position disappeared, and new positions appeared without orders from me.
3. Add a weekly P&L figure and populate the track record in the portfolio report.
4. While total exposure stays over the cap, scheduled runs can only monitor. Pause them or reduce exposure manually if that fits your plan.
