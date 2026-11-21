"""Two-year forecast for brands last observed2024; never relabel one-year scores."""
from pathlib import Path
import pandas as pd,numpy as np,json
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss,roc_auc_score,precision_score,recall_score
P=Path('docs/d06/delivery/revised');O=P/'two_year';O.mkdir(exist_ok=True);q=pd.read_csv(P/'source_count_audit.csv');v=q[q['count'].notna()];lookup={(r.brand,int(r.year)):r for r in v.itertuples()};j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet');registry=json.loads((P/'brand_registry.json').read_text(encoding='utf-8'));rows=[]
for r in v.itertuples():
 y=int(r.year);a=lookup.get((r.brand,y-2));b=lookup.get((r.brand,y-3))
 if a is None or b is None or a.count<3:continue
 rows.append(dict(brand=r.brand,year=y,baseyear=y-2,last=a.count,previous=b.count,industry=a.industry,label=int(r.count<a.count),kind='train'))
for r in registry:
 if r['status']!='latest_count_unavailable' or r['last_observed_accounting_year']!=2024 or r['last_observed_stores']<3:continue
 a=lookup[(r['brand'],2024)];b=lookup.get((r['brand'],2023))
 if b is not None:rows.append(dict(brand=r['brand'],year=2026,baseyear=2024,last=a.count,previous=b.count,industry=a.industry,label=np.nan,kind='current'))
x=pd.DataFrame(rows);x['industry']=x.industry.fillna('unknown');x['log_count']=np.log1p(x['last']);x['growth']=np.log1p(x['last'])-np.log1p(x.previous);x['feature_report_year']=x.baseyear+1
meta=j[['brandMnno','source_report_year','jngBizStrtDate','dmsCnt']].rename(columns={'brandMnno':'brand','source_report_year':'feature_report_year'});x=x.merge(meta,on=['brand','feature_report_year'],how='left',validate='many_to_one');n=j[['brandMnno','source_report_year']+[c for c in j if c.startswith('national_')]].rename(columns={'brandMnno':'brand','source_report_year':'baseyear'});x=x.merge(n,on=['brand','baseyear'],how='left',validate='many_to_one')
x['brand_age']=x.baseyear-pd.to_numeric(x.jngBizStrtDate.astype(str).str[:4],errors='coerce');x.loc[x.brand_age<0,'brand_age']=np.nan
for c in ['national_frcsCnt','national_newFrcsRgsCnt','national_ctrtEndCnt','national_ctrtCncltnCnt','national_nmChgCnt','dmsCnt']:x[c]=pd.to_numeric(x[c],errors='coerce')
x['log_direct']=np.log1p(x.dmsCnt);x['log_national_count']=np.log1p(x.national_frcsCnt)
for c in ['newFrcsRgsCnt','ctrtEndCnt','ctrtCncltnCnt','nmChgCnt']:x[c+'_rate']=x['national_'+c]/x.national_frcsCnt.where(x.national_frcsCnt>0)
nums=['log_count','growth','brand_age','log_direct','log_national_count']+[c+'_rate' for c in ['newFrcsRgsCnt','ctrtEndCnt','ctrtCncltnCnt','nmChgCnt']]
protocol=dict(horizon=2,target='count[Y]<count[Y-2]',population='base count>=3 and prior-year observation',train_labels='<=Y-2 including current target2026 train<=2024',development=[2022,2023],evaluation=[2024],provisional=[2025],selection='development Brier, compare fixed additional HGB versus industry-rate baseline',publication_limit='retrospective latest snapshot, actual vintage release dates unverified')
(O/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
def run(y):
 tr=x[(x.kind=='train')&(x.year<=y-2)];te=x[(x.kind==('current' if y==2026 else 'train'))&x.year.eq(y)];pre=ColumnTransformer([('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['industry']),('num',SimpleImputer(strategy='median',add_indicator=True),nums)]);m=make_pipeline(pre,HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,min_samples_leaf=30,l2_regularization=10,learning_rate=.05,random_state=20261119));m.fit(tr,tr.label.astype(int));rates=tr.groupby('industry').label.agg(['sum','count']);rates['p']=(rates['sum']+20*tr.label.mean())/(rates['count']+20);out=[]
 for name,p in [('two_year_hgb',m.predict_proba(te)[:,1]),('two_year_industry',te.industry.map(rates.p).fillna(tr.label.mean()).to_numpy())]:
  z=te[['brand','year','label']].copy();z['model']=name;z['probability']=p;z['train_max_year']=int(tr.year.max());out.append(z)
 return pd.concat(out)
dev=pd.concat([run(2022),run(2023)]);scores={m:float(brier_score_loss(g.label,g.probability)) for m,g in dev.groupby('model')};selected=min(scores,key=scores.get);(O/'selection.json').write_text(json.dumps(dict(selected=selected,development=scores),indent=2),encoding='utf-8');r=pd.concat([dev,run(2024),run(2025)]);r.to_csv(O/'validation_predictions.csv',index=False);metrics=[]
for (y,m),g in r.groupby(['year','model']):metrics.append(dict(year=int(y),model=m,n=len(g),brier=float(brier_score_loss(g.label,g.probability)),auc=float(roc_auc_score(g.label,g.probability)),precision=float(precision_score(g.label,g.probability>=.5,zero_division=0)),recall=float(recall_score(g.label,g.probability>=.5,zero_division=0))))
current=run(2026);current.to_csv(O/'current_predictions.csv',index=False);cur=current[current.model==selected].set_index('brand');national=x[(x.kind=='current')&x.year.eq(2026)].set_index('brand')
for a in registry:
 a['forecast_horizon_years']=1 if a['status']=='current_projection' else None;a['baseline_accounting_year']=2025 if a['status']=='current_projection' else None;a['model_kind']='one_year_hgb' if a['status']=='current_projection' else None;a['national_report_year']=2025 if a['status']=='current_projection' else None
 if a['brand'] in cur.index:
  a['message']='2025년 수치가 미확인이라 2024년 말 자료로 2026년 말의 감소 여부를 예측하는 별도 2년 전망임.'
  a.update(status='two_year_projection',decline_probability=float(cur.loc[a['brand'],'probability']),forecast_horizon_years=2,baseline_accounting_year=2024,target_accounting_year=2026,model_kind=selected,national_report_year=2024)
  for c in ['national_frcsCnt','national_newFrcsRgsCnt','national_ctrtEndCnt','national_ctrtCncltnCnt']:
   val=national.loc[a['brand'],c];a[c]=int(val) if pd.notna(val) else None
(P/'brand_registry.json').write_text(json.dumps(registry,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');pd.DataFrame([{k:v for k,v in a.items() if k!='count_history'} for a in registry]).to_csv(P/'brand_registry.csv',index=False,encoding='utf-8-sig');summary=dict(selected=selected,forecast_count=len(cur),status_counts=pd.Series([a['status'] for a in registry]).value_counts().to_dict(),validation=metrics);(O/'results.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print('selected',selected,'count',len(cur),'status',summary['status_counts']);print(pd.DataFrame(metrics).query('year>=2024').to_string(index=False))
