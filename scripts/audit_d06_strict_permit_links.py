from pathlib import Path
import json,pandas as pd,numpy as np
from sklearn.metrics import brier_score_loss,roc_auc_score
P=Path('docs/d06/delivery/revised');O=P/'permit_missing_latest/strict_link_audit';O.mkdir(exist_ok=True)
r=pd.read_csv(P/'permit_missing_latest/predictions.csv');f=pd.read_csv(P/'permit_support_refined/permit_features.csv');f=f.set_index(['brand','year']);q=pd.read_csv(P/'source_count_audit.csv');counts={(a.brand,int(a.year)):a.count for a in q[q['count'].notna()].itertuples()};j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet');names={(a.brandMnno,int(a.source_report_year)):str(a.brandNm).strip() for a in j[j.brandNm.notna()].itertuples()};rows=[]
for a in r[r.year.lt(2026)].drop_duplicates(['brand','year']).itertuples():
 b,y=a.brand,int(a.year);base=counts.get((b,y-2));key=(b,y-1)
 if base is None or base<=0 or key not in f.index:continue
 z=f.loc[key];ratio=z.permit_active/base;stable=names.get((b,y-1)) is not None and names.get((b,y-1))==names.get((b,y-2))
 rows.append(dict(brand=b,year=y,ratio=ratio,stable=stable))
a=pd.DataFrame(rows);results=[];chosen=[]
for lo,hi in [(.7,1.3),(.8,1.2),(.9,1.1)]:
 keys=a[a.stable&a.ratio.between(lo,hi)][['brand','year']];g=r.merge(keys,on=['brand','year'],validate='many_to_one');g['band']=str((lo,hi));chosen.append(g)
 for (y,m),v in g.groupby(['year','model']):results.append(dict(lower=lo,upper=hi,year=int(y),model=m,n=len(v),brier=float(brier_score_loss(v.label,v.probability)),auc=float(roc_auc_score(v.label,v.probability)) if v.label.nunique()>1 else None))
pd.DataFrame(results).to_csv(O/'metrics.csv',index=False);pd.concat(chosen).to_csv(O/'predictions.csv',index=False);a.to_csv(O/'link_screen.csv',index=False)
(O/'protocol.json').write_text(json.dumps({'selection':'same brand name in baseline and preceding report; baseline-year permit buildings / official baseline count within fixed sensitivity bands','no_target_selection':'screen uses Y-2 counts and permits only, never target or hidden Y-1 official counts','purpose':'subgroup evaluation of already fitted models; not an independent untouched test; ratio agreement does not prove correct identity','bands':[[.7,1.3],[.8,1.2],[.9,1.1]]},indent=2),encoding='utf-8')
print(pd.DataFrame(results).query('year>=2024').to_string(index=False))
