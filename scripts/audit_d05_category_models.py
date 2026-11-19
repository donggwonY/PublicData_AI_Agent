"""Reproduce D-05 category error diagnostics and past-only feature checks."""
from pathlib import Path
import pandas as pd
import numpy as np
P=Path(__file__).resolve().parents[1]/'docs/d05'
r=pd.read_csv(P/'category_model_predictions.csv');c=pd.read_csv(P/'category_model_cells.csv');g=pd.read_csv(P/'category_panel.csv');keys=['year','gu','service','category']
for x in c.itertuples():
 h=g[(g.gu==x.gu)&(g.service==x.service)&(g.category==x.category)&g.year.between(x.year-3,x.year-1)]
 assert np.isclose(x.detail,h.u.sum()/h.k.sum())
 assert np.isclose(np.expm1(x.logk),h.k.sum()) and np.isclose(x.coverage,h.k.sum()/h.n.sum())
assert r.groupby('model').size().eq(479).all() and not r.duplicated(keys+['model']).any()
old=pd.read_csv(P/'category_predictions.csv');z=r[r.model=='detail3'].merge(old[old.model=='detailed'],on=keys,suffixes=('_new','_old'),validate='one_to_one');assert np.allclose(z.pred_new,z.pred_old)
r=r.merge(c[keys+['logk','coverage']],on=keys,validate='many_to_one');rows=[]
for label,minimum,coverage in [('all',30,.8),('past60_90pct',60,.9),('past100_90pct',100,.9)]:
 t=r[(np.expm1(r.logk)>=minimum-1e-8)&(r.coverage>=coverage-1e-8)]
 for m,z in t.groupby('model'):rows.append(dict(subset=label,model=m,cells=len(z),mae_pp=z.ae.mean(),weighted_mae_pp=np.average(z.ae,weights=z.k)))
pd.DataFrame(rows).to_csv(P/'category_past_quality.csv',index=False,encoding='utf-8-sig')
r[r.model=='detail3'].groupby(['service','category']).agg(cells=('ae','size'),known=('k','sum'),mae_pp=('ae','mean')).reset_index().to_csv(P/'category_error_diagnosis.csv',index=False,encoding='utf-8-sig')
print('Past-only features, common rows, baseline reproduction passed.')
