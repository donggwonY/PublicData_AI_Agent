"""Fixed robust follow-up on frozen Daegu eligible cells; exploratory reuse."""
from pathlib import Path
import json,hashlib,warnings
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import HuberRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.exceptions import ConvergenceWarning
P=Path("docs/d06/robust");P.mkdir(parents=True,exist_ok=True)
protocol={"date":"2026-11-19","source":"frozen first experiment eligible_cells.csv", "scope":"Previously evaluated periods reused; exploratory follow-up, not new independent final validation", "development":[2021,2022],"evaluation":[2023,2024],"provisional":[2025],"training_labels":"year <= target-2","primary":"mean absolute log error against midpoint proxy","methods":{"huber":{"epsilon":1.35,"alpha":1,"max_iter":1000},"absolute_boosting":{"loss":"absolute_error","max_iter":100,"max_leaf_nodes":7,"min_samples_leaf":20,"l2_regularization":10,"learning_rate":.05},"industry_median":{"minimum_history":20,"shrink_weight":.5}},"selection":"lowest development mean absolute log error; do not select using evaluated periods", "data_rule":"No target-outlier deletion or manual scale correction; all methods on same cells"}
(P/"protocol.json").write_text(json.dumps(protocol,indent=2),encoding="utf-8")
f=Path("docs/d06/experiment/eligible_cells.csv");x=pd.read_csv(f)
num=["log_last","growth","log_stores","store_growth"];features=num+["industry"]
def prep():return ColumnTransformer([("cat",OneHotEncoder(handle_unknown="ignore",sparse_output=False),["industry"]),("num",StandardScaler(),num)])
def metric(g):return dict(cells=len(g),log_error=float(g.abs_log.mean()),mape_pct=float(g.ape.mean()*100),median_ape_pct=float(g.ape.median()*100),range_distance_pct=float(g.range_error.mean()*100))
def evaluate(years):
 results=[];convergence=[]
 for y in years:
  tr=x[x.year<=y-2];te=x[x.year==y]
  models={"huber":make_pipeline(prep(),HuberRegressor(epsilon=1.35,alpha=1,max_iter=1000)),"absolute_boosting":make_pipeline(prep(),HistGradientBoostingRegressor(loss="absolute_error",max_iter=100,max_leaf_nodes=7,min_samples_leaf=20,l2_regularization=10,learning_rate=.05,random_state=20261119))}
  vals={"last_available":te['last'].to_numpy()}
  glob=tr.change.median();group=tr.groupby("industry").change.agg(["count","median"])
  delta=np.array([group.loc[c,"median"] if c in group.index and group.loc[c,"count"]>=20 else glob for c in te.industry])*.5
  vals["industry_median"]=te['last'].to_numpy()*np.exp(np.clip(delta,-1.5,1.5))
  for name,m in models.items():
   with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always",ConvergenceWarning);m.fit(tr[features],tr.change)
   convergence.append(dict(year=y,model=name,warnings=[str(w.message) for w in caught]))
   vals[name]=te['last'].to_numpy()*np.exp(np.clip(m.predict(te[features]),-1.5,1.5))
  for name,v in vals.items():
   z=te.copy();z["model"]=name;z["prediction"]=v;z["abs_log"]=abs(np.log(v/z.actual));z["ape"]=abs(v-z.actual)/z.actual
   z["range_error"]=np.maximum(np.maximum(z.lo-v,v-z.hi),0)/z.actual;results.append(z)
 return pd.concat(results,ignore_index=True),convergence
dev,w1=evaluate([2021,2022]);scores={m:metric(g) for m,g in dev.groupby("model")}
chosen=min(["huber","absolute_boosting","industry_median"],key=lambda m:scores[m]["log_error"])
(P/"selection.json").write_text(json.dumps(dict(chosen=chosen,development=scores),indent=2),encoding="utf-8")
ev,w2=evaluate([2023,2024]);late,w3=evaluate([2025]);r=pd.concat([dev,ev,late],ignore_index=True)
r.to_csv(P/"predictions.csv",index=False)
annual=[dict(year=int(y),model=m,**metric(g)) for (y,m),g in r.groupby(["year","model"])]
pd.DataFrame(annual).to_csv(P/"annual.csv",index=False)
wide=ev.pivot(index=["brand","year"],columns="model",values="abs_log").reset_index();wide["delta"]=wide[chosen]-wide.last_available
g=wide.groupby("brand").delta.agg(["sum","count"]).to_numpy();rng=np.random.default_rng(20261119);boot=[]
for _ in range(2000):
 z=g[rng.integers(len(g),size=len(g))];boot.append(z[:,0].sum()/z[:,1].sum())
res=dict(chosen=chosen,development=scores,evaluation={m:metric(g) for m,g in ev.groupby("model")},provisional_2025={m:metric(g) for m,g in late.groupby("model")},chosen_difference_ci=np.quantile(boot,[.025,.975]).tolist(),convergence=w1+w2+w3,input_sha256=hashlib.sha256(f.read_bytes()).hexdigest())
(P/"results.json").write_text(json.dumps(res,indent=2),encoding="utf-8")
print(json.dumps({k:v for k,v in res.items() if k!="convergence"},indent=2));print(pd.DataFrame(annual).to_string(index=False))
