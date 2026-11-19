"""Provisional group early closure forecast; no individual predictions."""
import json, hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import Ridge

out=Path("docs/d05/topic_screening/cohort");out.mkdir(parents=True,exist_ok=True)
protocol={"target":"share of an opening-year gu/service cohort with reported closure within 365 days", "asof":"2026-11-06", "evaluation_years":list(range(2020,2025)), "training":"opening years <= forecast year - 2; no partially observed last cohort", "history":"three latest mature opening cohorts", "min_history":60,"min_target":1,"models":["pooled_three_mature_cohorts","service_shrink_30","ridge_alpha_100"],"scope":"Exploratory reuse of previously inspected years; not untouched final test. Current snapshot historical reconstruction. Not individual failure or causal location recommendation."}
(out/"protocol.json").write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding="utf-8")
p=Path("service/data/processed/stores.parquet")
d=pd.read_parquet(p);d=d[d.is_primary.fillna(False)&~d.short_event.fillna(False)].copy()
d["ld"]=pd.to_datetime(d.ld,errors="coerce");d["cd"]=pd.to_datetime(d.cd,errors="coerce")
d=d[d.ld.notna()&d.gu.notna()&d.service.notna()&(d.ld>= "2010-01-01")&(d.ld<"2025-01-01")&(d.cd.isna()|(d.cd>=d.ld))]
d["year"]=d.ld.dt.year;d["event"]=((d.cd-d.ld).dt.days.between(0,365)).astype(int)
a=d.groupby(["gu","service","year"],observed=True).agg(n=("event","size"),events=("event","sum")).reset_index()
rows=[]
for (gu,service),g in a.groupby(["gu","service"],observed=True):
 for year in range(2015,2025):
  h=g[g.year.between(year-4,year-2)];target=g[g.year==year]
  if h.n.sum()<60 or len(target)!=1:continue
  ss=a[(a.service==service)&a.year.between(year-4,year-2)]
  rate=h.events.sum()/h.n.sum();sr=ss.events.sum()/ss.n.sum()
  rows.append(dict(gu=str(gu),service=str(service),year=year,n=int(target.n.iloc[0]),actual=float(target.events.iloc[0]/target.n.iloc[0]),hist_n=int(h.n.sum()),past_rate=rate,service_rate=sr,shrink=(h.events.sum()+30*sr)/(h.n.sum()+30)))
x=pd.DataFrame(rows);pred=[]
features=["gu","service","past_rate","service_rate","log_n"]
x["log_n"]=np.log1p(x.hist_n)
for y in range(2020,2025):
 train=x[x.year<=y-2];test=x[x.year==y]
 if len(train)==0 or len(test)==0:continue
 prep=ColumnTransformer([("cat",OneHotEncoder(handle_unknown="ignore",sparse_output=False),["gu","service"]),("num",StandardScaler(),["past_rate","service_rate","log_n"])])
 model=make_pipeline(prep,Ridge(alpha=100))
 model.fit(train[features],train.actual,ridge__sample_weight=train.n/train.n.mean())
 values={"pooled_three_mature_cohorts":test.past_rate.to_numpy(),"service_shrink_30":test.shrink.to_numpy(),"ridge_alpha_100":np.clip(model.predict(test[features]),0,1)}
 for name,v in values.items():
  z=test[["gu","service","year","n","actual"]].copy();z["model"]=name;z["prediction"]=v;z["error_pp"]=abs(z.prediction-z.actual)*100;pred.append(z)
r=pd.concat(pred,ignore_index=True)
metrics=[]
for name,g in r.groupby("model"):
 metrics.append(dict(model=name,cells=len(g),mae_pp=g.error_pp.mean(),weighted_mae_pp=np.average(g.error_pp,weights=g.n)))
annual=r.groupby(["model","year"]).error_pp.mean().unstack(0)
a.to_csv(out/"cohorts.csv",index=False);r.to_csv(out/"predictions.csv",index=False);annual.to_csv(out/"annual.csv")
result=dict(protocol=protocol,source_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),source_rows=len(d),metrics=metrics)
(out/"results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(metrics,indent=2));print(annual.to_string())
