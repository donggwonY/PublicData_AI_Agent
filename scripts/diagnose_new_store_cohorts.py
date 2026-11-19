"""Frozen exploratory ranking/error checks; no UI or model retuning."""
import json, itertools, hashlib
from pathlib import Path
import numpy as np
import pandas as pd
P=Path("docs/d05/topic_screening/cohort")
protocol={"pairing":"same service and opening year, different gu; all eligible pairs", "ties":"actual ties excluded and counted; prediction ties score 0.5", "fixed_gap_pp":5,"interval":"90th percentile absolute historical shrink forecast errors, cohort years <= y-2, higher quantile, >=50 calibration cells; pooled descriptive coverage, no conditional guarantee", "history_bands":[60,150,300],"scope":"post-hoc diagnostic on already inspected years; fixed rules before this diagnostic, no threshold search"}
(P/"diagnostic_protocol.json").write_text(json.dumps(protocol,indent=2),encoding="utf-8")
a=pd.read_csv(P/"cohorts.csv");r=pd.read_csv(P/"predictions.csv")
# Generate historical pseudo-forecasts using mature cohorts only, including pre-evaluation years.
rows=[]
for (gu,service),g in a.groupby(["gu","service"]):
 for y in range(2014,2025):
  h=g[g.year.between(y-4,y-2)];t=g[g.year==y]
  if h.n.sum()<60 or len(t)!=1:continue
  ss=a[(a.service==service)&a.year.between(y-4,y-2)]
  q=(h.events.sum()+30*ss.events.sum()/ss.n.sum())/(h.n.sum()+30)
  rows.append(dict(gu=gu,service=service,year=y,pred=q,actual=t.events.iloc[0]/t.n.iloc[0],hist_n=h.n.sum(),history_span_pp=(h.events/h.n).max()*100-(h.events/h.n).min()*100))
hist=pd.DataFrame(rows);hist["err"]=abs(hist.pred-hist.actual)
s=r[r.model=="service_shrink_30"].merge(hist,on=["gu","service","year"],validate="one_to_one",suffixes=("","_check"))
assert np.allclose(s.prediction,s.pred) and np.allclose(s.actual,s.actual_check)
s["radius"]=np.nan;s["calibration_n"]=0
for y in sorted(s.year.unique()):
 cal=hist[hist.year<=y-2]
 s.loc[s.year==y,"calibration_n"]=len(cal)
 if len(cal)>=50:s.loc[s.year==y,"radius"]=np.quantile(cal.err,.9,method="higher")
s["low"]=np.maximum(0,s.prediction-s.radius);s["high"]=np.minimum(1,s.prediction+s.radius)
s["covered"]=s.actual.between(s.low,s.high)
pairs=[]
for (model,year,service),g in r.groupby(["model","year","service"]):
 for i,j in itertools.combinations(g.itertuples(),2):
  true=i.actual-j.actual;pred=i.prediction-j.prediction
  tie=abs(true)<1e-12
  score=np.nan if tie else (.5 if abs(pred)<1e-12 else float(true*pred>0))
  pairs.append(dict(model=model,year=int(year),service=service,gu1=i.gu,gu2=j.gu,actual_gap_pp=true*100,pred_gap_pp=pred*100,actual_tie=tie,score=score))
pd_pairs=pd.DataFrame(pairs)
summary=[]
for model,g in pd_pairs.groupby("model"):
 for name,sub in [("all",g),("predicted_gap_ge_5pp",g[g.pred_gap_pp.abs()>=5])]:
  summary.append(dict(model=model,subset=name,pairs=len(sub),actual_ties=int(sub.actual_tie.sum()),accuracy=float(sub.score.mean()) if len(sub) else None,all_pair_coverage=len(sub)/len(g)))
rank=pd.DataFrame(summary);rank.to_csv(P/"ranking_summary.csv",index=False)
pd_pairs.to_csv(P/"ranking_pairs.csv",index=False)
pd_pairs.groupby(["model","year"]).score.agg(["count","mean"]).to_csv(P/"ranking_annual.csv")
error_rows=[]
for key,label in [("hist_n","past_n"),("n","target_n_diagnostic_only")]:
 for lo,hi in [(0,60),(60,150),(150,300),(300,float("inf"))]:
  sub=s[(s[key]>=lo)&(s[key]<hi)]
  if len(sub):error_rows.append(dict(group=label,lower=lo,upper=str(hi),cells=len(sub),mae_pp=sub.error_pp.mean(),over_10pp=float((sub.error_pp>10).mean())))
pd.DataFrame(error_rows).to_csv(P/"error_groups.csv",index=False)
s.to_csv(P/"uncertainty_cells.csv",index=False)
# Compare only intervals computed from historical errors; no true gap filtering.
pair_intervals=[]
for (year,service),g in s.groupby(["year","service"]):
 for i,j in itertools.combinations(g.itertuples(),2):
  if pd.isna(i.radius) or pd.isna(j.radius):continue
  separate=(i.high<j.low) or (j.high<i.low)
  pair_intervals.append(dict(separate=separate,correct=(i.prediction-j.prediction)*(i.actual-j.actual)>0,actual_tie=abs(i.actual-j.actual)<1e-12))
pi=pd.DataFrame(pair_intervals);z=s[s.radius.notna()]
result={"cells":len(s),"ranking":summary,"interval_cells":len(z),"interval_coverage":float(z.covered.mean()),"median_interval_width_pp":float(((z.high-z.low)*100).median()),"intervals_nonoverlap_pairs":int(pi.separate.sum()),"interval_comparable_pairs":len(pi),"nonoverlap_accuracy":float(pi[pi.separate&~pi.actual_tie].correct.mean()) if (pi.separate&~pi.actual_tie).any() else None,"prediction_sha256":hashlib.sha256((P/"predictions.csv").read_bytes()).hexdigest()}
(P/"diagnostic_results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(result,ensure_ascii=False,indent=2));print(pd.DataFrame(error_rows).to_string(index=False))

# Same-pair baseline comparison, not incomparable model-specific subsets.
keys=["year","service","gu1","gu2"]
chosen=pd_pairs[(pd_pairs.model=="service_shrink_30")&(pd_pairs.pred_gap_pp.abs()>=5)][keys]
matched=pd_pairs.merge(chosen,on=keys,validate="many_to_one")
matched.groupby("model").score.agg(["count","mean"]).to_csv(P/"same_selected_pairs.csv")
sel=matched[matched.model=="service_shrink_30"]
sel.groupby("year").score.agg(["count","mean"]).to_csv(P/"selected_annual.csv")
sel.groupby("service").score.agg(["count","mean"]).to_csv(P/"selected_services.csv")
print("SAME PAIRS",matched.groupby("model").score.agg(["count","mean"]).to_string())
print("SELECTED YEARS",sel.groupby("year").score.agg(["count","mean"]).to_string())
print("SELECTED SERVICES",sel.groupby("service").score.agg(["count","mean"]).to_string())
