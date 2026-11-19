from pathlib import Path
import json
import numpy as np
import pandas as pd
from sklearn.metrics import precision_score,recall_score
P=Path('docs/d06/decline/additional');d=pd.read_csv(P/'predictions.csv');d=d[d.model=='additional'].merge(pd.read_csv(P.parent/'eligible_cells.csv')[['brand','year','last']],on=['brand','year'],validate='one_to_one');d['size']=pd.cut(d['last'],[2,5,10,np.inf],labels=['3-5','6-10','11+']).astype(str)
protocol=dict(fit=2022,validation=2023,evaluation=2024,provisional=2025,scope='exploratory reused years',rule='per size maximize recall with precision>=.60 and alerts>=20 in2022; otherwise threshold .5',validation_gate='2023 precision >=.60 and recall greater than fixed .5 per size; otherwise keep .5',reference='.5 pre-existing fixed threshold; .51 is not independent because selected on pooled2022/2023',grid='.10 to .90 step .01')
(P/'size_warning_protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
def score(g,t):
 a=g.probability>=t;return dict(n=len(g),threshold=float(t),alerts=int(a.sum()),true_alerts=int((a&(g.label==1)).sum()),false_alerts=int((a&(g.label==0)).sum()),missed=int(((~a)&(g.label==1)).sum()),precision=float(precision_score(g.label,a,zero_division=0)),recall=float(recall_score(g.label,a,zero_division=0)))
choices={};grid=[]
for size,g in d[d.year==2022].groupby('size'):
 rows=[score(g,t) for t in np.round(np.arange(.10,.901,.01),2)];grid.extend([dict(size=size,**r) for r in rows]);ok=[r for r in rows if r['precision']>=.6 and r['alerts']>=20];best=max(ok,key=lambda r:(r['recall'],r['precision'],r['threshold'])) if ok else score(g,.5)
 choices[size]=dict(candidate=best['threshold'],training=best,qualified=bool(ok))
(P/'size_warning_candidates.json').write_text(json.dumps(choices,indent=2),encoding='utf-8');pd.DataFrame(grid).to_csv(P/'size_warning_grid.csv',index=False)
for size,c in choices.items():
 v=d[(d.year==2023)&(d['size']==size)];a=score(v,c['candidate']);b=score(v,.5);passed=c['qualified'] and a['precision']>=.6 and a['recall']>b['recall'];c.update(validation_candidate=a,validation_reference=b,accepted=bool(passed),final_threshold=c['candidate'] if passed else .5)
(P/'size_warning_selection.json').write_text(json.dumps(choices,indent=2),encoding='utf-8')
rows=[]
for y,g in d[d.year>=2024].groupby('year'):
 for policy in ['fixed_05','size_candidate','validated_size']:
  z=g.copy();z['threshold']=.5 if policy=='fixed_05' else z['size'].map({s:c['candidate' if policy=='size_candidate' else 'final_threshold'] for s,c in choices.items()});a=z.probability>=z.threshold
  rows.append(dict(year=int(y),policy=policy,n=len(z),alerts=int(a.sum()),true_alerts=int((a&(z.label==1)).sum()),false_alerts=int((a&(z.label==0)).sum()),missed=int(((~a)&(z.label==1)).sum()),precision=float(precision_score(z.label,a,zero_division=0)),recall=float(recall_score(z.label,a,zero_division=0))))
assert not d.duplicated(['brand','year']).any();(P/'size_warning_results.json').write_text(json.dumps(rows,indent=2),encoding='utf-8');print(json.dumps({s:{k:c[k] for k in ['candidate','accepted','final_threshold']} for s,c in choices.items()}));print(pd.DataFrame(rows).to_string(index=False))
