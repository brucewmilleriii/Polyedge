# Run 20261031T052845Z (live)

I placed no orders this run. Free cash fell by about $139 with no order from me, open exposure is still about twice the cap, and there's only $3.72 of cash left to trade with.

**What changed since the last run**
- **Free cash went from $142.29 to $3.72, down $138.57.** I placed no orders, there are no open orders, and the positions are the same size as last run. Equity fell by the same amount, from $334.86 to $196.29. I can't see what caused it: there's no fill, settlement or order record. This is a live account, so it needs a human to look at it before anything else happens.
- **Today's P&L reads $0.00** (last run it was +$103.38). That fits a new UTC day starting, but it means the ~$139 drop isn't counted as a loss anywhere. So the daily and weekly loss stops may not be seeing it.
- **Equity breakdown:** $3.72 cash, plus about $17.58 for the Georgia position marked at the 0.03 bid, plus about $175 for the three crossd positions at cost. I can't value or exit the crossd positions: their order books still return server errors and show no bid.
- **The track record is still empty.**

**Holdings review**
- **Georgia Senate, Republican YES:** 586 contracts at 0.0427. The book is 0.03 bid / 0.04 ask. Bid depth fell from 1.58M to about 8k contracts at 0.03, but the market still prices the Republican at about 3.5%. I'm holding, because nothing new has broken a thesis (I didn't place this position). Marked at the bid it's a loss of about $7.4. The election is Nov 3, and the market ends Jan 15, 2027 to allow for a runoff.
- **crossd-51e9 / 98e7 / ae68:** holding, since there's no book to sell into.

**Quick Scan Table**
| Market | Mid | My Prob | Net Edge | Liq Score | Action | Size | Confidence |
|---|---|---|---|---|---|---|---|
| GA Senate R YES (held) | 0.035 | not estimated | n/a | Deep | Hold | 0 | — |
| crossd-51e9 / 98e7 / ae68 (held) | n/a | n/a | n/a | No book; server error | Hold | 0 | — |

**No-Trade Declaration:** No trade, for three reasons:
- Open exposure at cost (about $200) is over the $100 total cap.
- Free cash is only $3.72.
- A debit of about $139 hasn't been explained.

I didn't scan for new markets or check other markets for pricing gaps, because I couldn't act on anything I found.

**Needs a human (urgent, live account)**
1. **Find out where the $138.57 went.** Check the exchange account history for withdrawals, fees, reversed settlements or orders I didn't place. One thing worth checking is whether the $98.32 credited last run, which I took to be crossd-0c2a settling YES, was reversed. That alone wouldn't explain the full amount.
2. Fix the server errors on the crossd markets. They hold about $175 of cost that I can't value or exit.
3. Explain how positions got past the code-enforced limits: the ~$100 crossd-51e9 position, and the Georgia position below the 0.15 price floor.
4. Make sure the daily and weekly loss stops include changes in cash and equity, not only the reported P&L.
5. Think about pausing scheduled runs until this is sorted out. While exposure stays over the cap, all they can do is monitor.
