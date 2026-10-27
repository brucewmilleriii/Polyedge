import json, sys, numpy as np
fee=lambda p:0.0695*p*(1-p)
J=json.load(open(sys.argv[1] if len(sys.argv)>1 else 'research/joined_twap.json'))
rows=[]
for r in J:
  for side,ask in (('up',r['up_ask']),('down',r['down_ask'])):
    if ask is None or ask>=0.995 or ask<=0.01: continue
    other = r['down_ask'] if side=='up' else r['up_ask']
    if other is None or ask + other > 1.06: continue   # wide book: no real quote on this side
    pm = r['p_up'] if side=='up' else 1-r['p_up']
    rows.append(dict(slug=r['slug'],at=r['at'],side=side,ask=ask,pm=pm,won=r['outcome']==side,asset=r['asset'],tl=r['tl']))
A=np.array([x['ask'] for x in rows]);P=np.array([x['pm'] for x in rows]);Y=np.array([x['won'] for x in rows])
print("corr(ask,model)",np.corrcoef(A,P)[0,1].round(3))
for lo,hi in ((0.02,0.2),(0.2,0.5),(0.5,0.8),(0.8,0.9),(0.9,0.95),(0.95,0.98),(0.98,0.995)):
  k=(A>=lo)&(A<hi); print(f"ask {lo}-{hi} n={k.sum()} mean ask {A[k].mean():.3f} model {P[k].mean():.3f} won {Y[k].mean():.3f}")
print("\nby model prob (all asks)")
for lo,hi in ((0,0.05),(0.05,0.5),(0.5,0.9),(0.9,0.97),(0.97,0.99),(0.99,0.999),(0.999,1.01)):
  k=(P>=lo)&(P<hi); 
  if k.sum(): print(f"model {lo}-{hi} n={k.sum()} mean ask {A[k].mean():.3f} model {P[k].mean():.4f} won {Y[k].mean():.3f}")
def rule(f, label):
  seen=set();n=w=0;pnl=0.0;cost=0
  for x in sorted(rows,key=lambda x:(x['slug'],-x['at'])):
    if x['slug'] in seen or not f(x): continue
    seen.add(x['slug']); n+=1; w+=x['won']; pnl+=(1-x['ask'] if x['won'] else -x['ask'])-fee(x['ask']); cost+=x['ask']
  print(f"{label:45s} n={n:3d} won={w:3d} ({w/max(n,1):.3f}) pnl/contract={pnl:+.2f} ROI={pnl/max(cost,1e-9):+.3f}")
print()
rule(lambda x: 0.90<=x['ask']<=0.97 and x['tl']<=90, "current: ask .90-.97, <=90s")
for thr in (0.0,0.01,0.02,0.03):
  rule(lambda x: x['pm']-x['ask']-fee(x['ask'])>thr, f"model edge>{thr}")
  rule(lambda x: x['pm']-x['ask']-fee(x['ask'])>thr and x['ask']>=0.5, f"model edge>{thr}, favorite")
  rule(lambda x: x['pm']-x['ask']-fee(x['ask'])>thr and x['ask']>=0.85, f"model edge>{thr}, ask>=.85")
for pmin in (0.98,0.99,0.995,0.999):
  rule(lambda x: x['pm']>=pmin and 0.85<=x['ask']<=0.985, f"model>={pmin}, ask .85-.985")
