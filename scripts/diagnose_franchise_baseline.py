from pathlib import Path
import itertools,json
import numpy as np
import pandas as pd
P=Path("docs/d06/robust")
x=pd.read_csv("docs/d06/experiment/eligible_cells.csv")
# Historical log-ratio bounds, no target-year calibration or tuning.
rows=[];pairs=[]
for y in [2021,2022,2023,2024,2025]:
 tr=x[x.year<=y-2];te=x[x.year==y].copy();lo,hi=np.quantile(tr.change,[.1,.9],method="linear")
 te["prediction"]=te['last'];te["pred_lo"]=te['last']*np.exp(lo);te["pred_hi"]=te['last']*np.exp(hi)
 te["midpoint_covered"]=te.actual.between(te.pred_lo,te.pred_hi)
 te["full_disclosed_range_covered"]=(te.pred_lo<=te.lo)&(te.pred_hi>=te.hi)
 te["interval_overlap"]=(te.pred_lo<=te.hi)&(te.pred_hi>=te.lo)
 te["relative_width"]=(te.pred_hi-te.pred_lo)/te.prediction
 rows.append(te)
 for industry,g in te.groupby("industry"):
  for a,b in itertools.combinations(g.itertuples(),2):
   # Exact ordering is assessed only when the reported target ranges do not overlap.
   direction=1 if a.lo>b.hi else -1 if a.hi<b.lo else 0
   forecast=1 if a.pred_lo>b.pred_hi else -1 if a.pred_hi<b.pred_lo else 0
   raw=np.sign(a.prediction-b.prediction)
   pairs.append(dict(year=y,industry=industry,brand1=a.brand,brand2=b.brand,resolved_actual=direction!=0,separated_prediction=forecast!=0,correct=np.nan if direction==0 else .5 if raw==0 else float(raw==direction),separated_correct=np.nan if direction==0 or forecast==0 else float(forecast==direction)))
r=pd.concat(rows,ignore_index=True);pa=pd.DataFrame(pairs)
r.to_csv(P/"baseline_intervals.csv",index=False);pa.to_csv(P/"baseline_brand_pairs.csv",index=False)
metrics=[]
for y,g in r.groupby("year"):
 p=pa[pa.year==y]
 metrics.append(dict(year=int(y),cells=len(g),midpoint_coverage=float(g.midpoint_covered.mean()),whole_reported_range_coverage=float(g.full_disclosed_range_covered.mean()),any_overlap_coverage=float(g.interval_overlap.mean()),median_relative_width=float(g.relative_width.median()),same_industry_pairs=len(p),actual_resolved_pairs=int(p.resolved_actual.sum()),ordering_accuracy=float(p.correct.mean()),prediction_separated_pairs=int(p.separated_prediction.sum()),separated_resolved_pairs=int(p.separated_correct.notna().sum()),separated_order_accuracy=float(p.separated_correct.mean())))
(P/"baseline_utility.json").write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(metrics,ensure_ascii=False,indent=2))
