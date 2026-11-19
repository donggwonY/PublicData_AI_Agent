"""D-05 diagnosis: temporal change, missing floors, and past-defined changing groups."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
P=Path(__file__).resolve().parents[1]/'docs/d05'
g=pd.read_csv(P/'category_panel.csv');c=pd.read_csv(P/'category_model_cells.csv');r=pd.read_csv(P/'category_model_predictions.csv');keys=['year','gu','service','category'];lookup={(x.year,x.gu,x.service,x.category):(x.n,x.k,x.u) for x in g.itertuples()}
rows=[]
for x in c[c.year>=2020].itertuples():
 h=[lookup.get((x.year-i,x.gu,x.service,x.category),(0,0,0)) for i in (1,2,3)]
 sufficient=all(t[1]>=15 for t in h)
 change=abs(h[0][2]/h[0][1]-h[2][2]/h[2][1]) if sufficient else np.nan
 group='changing' if sufficient and change>=.1 else ('stable' if sufficient else 'insufficient_history')
 rows.append(dict(year=x.year,gu=x.gu,service=x.service,category=x.category,group=group,past_change_pp=change*100,n=x.n,k=x.k,u=x.u,past_rate=x.detail,current_rate=x.u/x.k,current_coverage=x.k/x.n,past_coverage=x.coverage,coverage_change_pp=100*(x.k/x.n-x.coverage),lower_pct=100*x.u/x.n,upper_pct=100*(x.u+x.n-x.k)/x.n))
d=pd.DataFrame(rows);d['missing_width_pp']=d.upper_pct-d.lower_pct;d['abs_error_pp']=100*abs(d.current_rate-d.past_rate);d.to_csv(P/'direction_cells.csv',index=False,encoding='utf-8-sig')
r=r.merge(d[keys+['group']],on=keys,validate='many_to_one');assert len(d)==479
metrics=[];intervals={};rng=np.random.default_rng(18)
for group,t in r.groupby('group'):
 for model,z in t.groupby('model'):metrics.append(dict(group=group,model=model,cells=len(z),known=int(z.k.sum()),mae_pp=float(z.ae.mean()),weighted_mae_pp=float(np.average(z.ae,weights=z.k))))
 w=t.pivot(index=keys,columns='model',values='ae')
 for model in w.columns:
  if model=='detail3':continue
  delta=(w[model]-w.detail3).rename('delta').reset_index();cl=delta.groupby(['gu','service','category']).delta.agg(['sum','count']);ix=rng.integers(len(cl),size=(2000,len(cl)));draw=cl['sum'].to_numpy()[ix].sum(axis=1)/cl['count'].to_numpy()[ix].sum(axis=1)
  intervals[group+'/'+model]={'delta_pp':float(delta.delta.mean()),'ci95':np.quantile(draw,[.025,.975]).tolist(),'years_improved':int((delta.groupby('year').delta.mean()<0).sum()),'years':int(delta.year.nunique())}
pd.DataFrame(metrics).to_csv(P/'direction_group_metrics.csv',index=False,encoding='utf-8-sig')
# Illustration: even a constant true rate has noisy annual observed fractions.
noise=np.abs(rng.binomial(d.k.to_numpy(dtype=int),d.past_rate.to_numpy(),size=(2000,len(d)))/d.k.to_numpy()-d.past_rate.to_numpy())*100
sim=noise.mean(axis=1)
# Same selected evaluation cells, no changing membership aggregate trend.
annual=[]
for y,z in d.groupby('year'):annual.append({'year':int(y),'cells':len(z),'mean_abs_change_from_past_pp':float(z.abs_error_pp.mean()),'mean_missing_width_pp':float(z.missing_width_pp.mean()),'known_coverage_pct':float(100*z.k.sum()/z.n.sum())})
report={'group_counts':d.group.value_counts().to_dict(),'observed_mae_pp':float(d.abs_error_pp.mean()),'constant_rate_noise_example':{'mean_mae_pp':float(sim.mean()),'simulation95':np.quantile(sim,[.025,.975]).tolist(),'caveat':'Fixed fitted past rates treated as truth, independent binomial records. Ignores past estimation uncertainty, clustering and real changes; not a formal stationarity test.'},'missing':{'median_width_pp':float(d.missing_width_pp.median()),'p90_width_pp':float(d.missing_width_pp.quantile(.9)),'mean_width_pp':float(d.missing_width_pp.mean()),'coverage_below80_cells':int((d.current_coverage<.8).sum()),'coverage_fell10pp_cells':int((d.coverage_change_pp<=-10).sum()),'spearman_error_vs_abs_coverage_change':float(d.abs_error_pp.corr(abs(d.coverage_change_pp),method='spearman'))},'annual':annual,'group_metrics':metrics,'paired':intervals,'limits':'Diagnostic exploratory reuse. Past groups fixed before scoring. Missing bounds worst case not probability intervals. Latest category/address histories cannot be established by these tables.'}
(P/'direction_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:report[k] for k in ['group_counts','observed_mae_pp','constant_rate_noise_example','missing']},ensure_ascii=False,indent=2));print(pd.DataFrame(metrics).pivot(index='model',columns='group',values='mae_pp').round(3).to_string());print('changing paired',json.dumps({k:v for k,v in intervals.items() if k.startswith('changing/')},ensure_ascii=False))
