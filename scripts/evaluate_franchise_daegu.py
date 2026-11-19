"""Time-ordered Daegu franchise revenue-range forecast experiment."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor

P=Path("docs/d06/experiment");P.mkdir(parents=True,exist_ok=True)
protocol={"target":"Daegu brand annual average sales range midpoint proxy; not exact sales", "forecast_origin":"before target accounting year; latest input accounting year t-2, report year t-1", "publication_limit":"Actual historical publication dates/vintages unavailable; report-year lag is an approximation, retrospective experiment only", "development_years":[2021,2022],"evaluation_years":[2023,2024],"provisional_latest_year":[2025],"train_labels":"accounting years <= target year - 2", "features":"two consecutive prior positive ranges t-2/t-3, their store counts and prior industry; no target metadata", "models":{"ridge_alpha":10,"hgb":{"max_iter":150,"max_leaf_nodes":7,"min_samples_leaf":20,"l2_regularization":10,"learning_rate":.05}},"primary_metric":"mean absolute log(midpoint prediction/observed midpoint)","secondary_metrics":["MAPE midpoint proxy","relative distance to disclosed target range","mean absolute log change direction"],"selection":"best baseline and best model on development only; both frozen before evaluation", "adoption_gate":"at least 5% primary error reduction pooled 2023/2024, improvement in each year and no worse relative range-distance overall; even passing requires data/publication checks before service", "range_note":"midpoints are proxies; zero/missing ranges excluded, no zero imputation; no guarantee for new/undisclosed brands"}
(P/"protocol.json").write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding="utf-8")
f=Path("data/raw/franchise/daegu_panel.parquet");d=pd.read_parquet(f);v=d[d.valid_sales].copy()
assert not v.duplicated(["brandMnno","year"]).any()
lookup={(str(z.brandMnno),int(z.year)):z for z in v.itertuples()};rows=[]
for z in v.itertuples():
 key=str(z.brandMnno);t=int(z.year);a=lookup.get((key,t-2));b=lookup.get((key,t-3))
 if a is None or b is None:continue
 rows.append(dict(brand=key,year=t,industry=str(a.indutyMlsfcNm),industry_changed=str(a.indutyMlsfcNm)!=str(z.indutyMlsfcNm),last=a.midpoint_proxy,previous=b.midpoint_proxy,actual=z.midpoint_proxy,lo=z.sales_lo,hi=z.sales_hi,log_last=np.log(a.midpoint_proxy),growth=np.log(a.midpoint_proxy/b.midpoint_proxy),log_stores=np.log1p(a.stores),store_growth=np.log1p(a.stores)-np.log1p(b.stores),past_stores=a.stores))
x=pd.DataFrame(rows);x["change"]=np.log(x.actual/x['last'])
num=["log_last","growth","log_stores","store_growth"]
features=num+["industry"]
def prep():return ColumnTransformer([("cat",OneHotEncoder(handle_unknown="ignore",sparse_output=False),["industry"]),("num",StandardScaler(),num)])
def score(g):return dict(cells=len(g),brands=g.brand.nunique(),mean_abs_log=float(g.abs_log.mean()),mape_pct=float(g.ape.mean()*100),range_distance_pct=float(g.range_error.mean()*100),within_disclosed_range=float(g.inside.mean()))
def evaluate(years):
 pred=[]
 for y in years:
  train=x[x.year<=y-2];test=x[x.year==y]
  assert train.year.max()<=y-2
  assert len(train)>=50 and len(test)>0
  models={"ridge":make_pipeline(prep(),Ridge(alpha=10)),"hgb":make_pipeline(prep(),HistGradientBoostingRegressor(max_iter=150,max_leaf_nodes=7,min_samples_leaf=20,l2_regularization=10,learning_rate=.05,random_state=20261118))}
  values={"last_available":test['last'].to_numpy(),"two_year_mean":(test['last'].to_numpy()+test.previous.to_numpy())/2,"damped_trend":test['last'].to_numpy()*np.exp(np.clip(test.growth.to_numpy(),-.5,.5))}
  for name,model in models.items():
   model.fit(train[features],train.change)
   values[name]=test['last'].to_numpy()*np.exp(np.clip(model.predict(test[features]),-1.5,1.5))
  for name,a in values.items():
   z=test.copy();z["model"]=name;z["prediction"]=a;z["train_cells"]=len(train)
   z["abs_log"]=abs(np.log(a/z.actual));z["ape"]=abs(a-z.actual)/z.actual
   z["range_error"]=np.maximum(np.maximum(z.lo-a,a-z.hi),0)/z.actual
   z["inside"]=(a>=z.lo)&(a<=z.hi)
   pred.append(z)
 return pd.concat(pred,ignore_index=True)
dev=evaluate([2021,2022]);devscores={m:score(g) for m,g in dev.groupby("model")}
base=min(["last_available","two_year_mean","damped_trend"],key=lambda m:devscores[m]["mean_abs_log"])
model=min(["ridge","hgb"],key=lambda m:devscores[m]["mean_abs_log"])
selection=dict(baseline=base,model=model,development=devscores)
(P/"selection.json").write_text(json.dumps(selection,indent=2),encoding="utf-8")
# Selection persisted before evaluation outcomes are computed.
test=evaluate([2023,2024]);late=evaluate([2025]);allpred=pd.concat([dev,test,late],ignore_index=True)
metrics=[]
for (m,y),g in allpred.groupby(["model","year"]):metrics.append(dict(model=m,year=int(y),**score(g)))
allpred.to_csv(P/"predictions.csv",index=False);pd.DataFrame(metrics).to_csv(P/"annual.csv",index=False)
x.to_csv(P/"eligible_cells.csv",index=False)
bscore=score(test[test.model==base]);mscore=score(test[test.model==model])
byyear={str(y):{m:score(g) for m,g in yy.groupby("model")} for y,yy in test.groupby("year")}
improvement=1-mscore['mean_abs_log']/bscore['mean_abs_log']
passed=improvement>=.05 and all(z[model]['mean_abs_log']<z[base]['mean_abs_log'] for z in byyear.values()) and mscore['range_distance_pct']<=bscore['range_distance_pct']
result=dict(selection=selection,evaluation_baseline=bscore,evaluation_model=mscore,relative_primary_improvement=improvement,gate_passed=bool(passed),evaluation_by_year=byyear,provisional_2025={m:score(g) for m,g in late.groupby("model")},source_sha256=hashlib.sha256(f.read_bytes()).hexdigest(),eligible_by_year=x.groupby("year").size().to_dict())
(P/"results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(result,ensure_ascii=False,indent=2))
