"""Fixed detailed-category cohort comparison; exploratory, no serving."""
from pathlib import Path
import json,itertools,hashlib
import pandas as pd
import numpy as np
P=Path("docs/d05/topic_screening/cohort_detail");P.mkdir(parents=True,exist_ok=True)
protocol={"years":list(range(2020,2025)),"history":"y-4 through y-2","minimum_mature_history":60,"target":"365-day closure-report proportion among opening cohorts","aliases":{"통닭(치킨)":"호프/통닭","까페":"커피숍"},"methods":["broad_service_history","detailed_history","detail_shrink30_city_category"],"scope":"same target cells for all methods; category split effect, not proven AI gain; previously inspected periods"}
(P/"protocol.json").write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding="utf-8")
f=Path("service/data/processed/stores.parquet");d=pd.read_parquet(f)
d=d[d.is_primary.fillna(False)&~d.short_event.fillna(False)].copy()
for c in ["ld","cd"]:d[c]=pd.to_datetime(d[c],errors="coerce")
d=d[d.ld.between("2010-01-01","2024-12-31")&d.gu.notna()&d.service.notna()&d.category.notna()&(d.cd.isna()|(d.cd>=d.ld))]
d=d[d.category.str.strip().ne("")];d.category=d.category.replace(protocol["aliases"])
d["year"]=d.ld.dt.year;d["event"]=(d.cd-d.ld).dt.days.between(0,365).astype(int)
a=d.groupby(["gu","service","category","year"],observed=True).agg(n=("event","size"),events=("event","sum")).reset_index()
# Broad-service source includes all categories, including those unavailable in detailed targets.
b=pd.read_csv("docs/d05/topic_screening/cohort/cohorts.csv")
rows=[]
for y in range(2020,2025):
 hist=a[a.year.between(y-4,y-2)].groupby(["gu","service","category"])[["n","events"]].sum()
 city=a[a.year.between(y-4,y-2)].groupby(["service","category"])[["n","events"]].sum()
 broad=b[b.year.between(y-4,y-2)].groupby(["gu","service"])[["n","events"]].sum()
 for t in a[a.year==y].itertuples():
  key=(t.gu,t.service,t.category)
  if key not in hist.index or hist.loc[key,"n"]<60:continue
  h=hist.loc[key];c=city.loc[(t.service,t.category)];bh=broad.loc[(t.gu,t.service)]
  preds={"broad_service_history":bh.events/bh.n,"detailed_history":h.events/h.n,"detail_shrink30_city_category":(h.events+30*c.events/c.n)/(h.n+30)}
  for model,pred in preds.items():rows.append(dict(gu=t.gu,service=t.service,category=t.category,year=y,n=t.n,hist_n=int(h.n),actual=t.events/t.n,model=model,prediction=pred,error_pp=abs(pred-t.events/t.n)*100))
r=pd.DataFrame(rows)
assert not r.duplicated(["gu","service","category","year","model"]).any()
metrics=[]
for m,g in r.groupby("model"):
 metrics.append(dict(model=m,cells=len(g),mae_pp=g.error_pp.mean(),weighted_mae_pp=np.average(g.error_pp,weights=g.n)))
r.to_csv(P/"predictions.csv",index=False)
r.groupby(["year","model"]).error_pp.mean().unstack().to_csv(P/"annual.csv")
r.groupby(["service","category","model"]).agg(cells=("error_pp","size"),mae_pp=("error_pp","mean")).to_csv(P/"categories.csv")
pairs=[]
for (model,year,service,category),g in r.groupby(["model","year","service","category"]):
 for i,j in itertools.combinations(g.itertuples(),2):
  true=i.actual-j.actual;pred=i.prediction-j.prediction
  pairs.append(dict(model=model,year=year,service=service,category=category,gu1=i.gu,gu2=j.gu,true_gap=true,pred_gap=pred,score=np.nan if abs(true)<1e-12 else .5 if abs(pred)<1e-12 else float(true*pred>0)))
pairs=pd.DataFrame(pairs);pairs.to_csv(P/"pairs.csv",index=False)
pairs.groupby("model").score.agg(["count","mean"]).to_csv(P/"ranking.csv")
wide=r.pivot(index=["gu","service","category","year"],columns="model",values="error_pp").reset_index()
wide["delta"]=wide.detail_shrink30_city_category-wide.broad_service_history
clusters=wide.groupby(["gu","service","category"]).delta.agg(["sum","count"]).to_numpy();rng=np.random.default_rng(20261118);bs=[]
for _ in range(2000):
 z=clusters[rng.integers(len(clusters),size=len(clusters))];bs.append(z[:,0].sum()/z[:,1].sum())
result=dict(metrics=metrics,cluster_difference_ci_pp=np.quantile(bs,[.025,.975]).tolist(),source_sha256=hashlib.sha256(f.read_bytes()).hexdigest(),scope=protocol["scope"])
(P/"results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(result,ensure_ascii=False,indent=2));print(r.groupby(["year","model"]).error_pp.mean().unstack().to_string());print(pairs.groupby("model").score.agg(["count","mean"]).to_string())
