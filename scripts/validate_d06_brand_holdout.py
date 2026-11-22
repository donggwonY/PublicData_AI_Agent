"""Two-year forecast for brands last observed2024; never relabel one-year scores."""
from pathlib import Path
import pandas as pd,numpy as np,json
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss,roc_auc_score,precision_score,recall_score
P=Path('docs/d06/delivery/revised');O=P/'final_brand_holdout';O.mkdir(exist_ok=True);q=pd.read_csv(P/'source_count_audit.csv');v=q[q['count'].notna()];lookup={(r.brand,int(r.year)):r for r in v.itertuples()};j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet');registry=json.loads((P/'brand_registry.json').read_text(encoding='utf-8'));rows=[]
for r in v.itertuples():
 y=int(r.year);a=lookup.get((r.brand,y-2));b=lookup.get((r.brand,y-3))
 if a is None or b is None or a.count<3:continue
 rows.append(dict(brand=r.brand,year=y,baseyear=y-2,last=a.count,previous=b.count,industry=a.industry,label=int(r.count<a.count),kind='train'))
for r in registry:
 if r['status'] not in ['latest_count_unavailable','two_year_projection'] or r['last_observed_accounting_year']!=2024 or r['last_observed_stores']<3:continue
 a=lookup[(r['brand'],2024)];b=lookup.get((r['brand'],2023))
 if b is not None:rows.append(dict(brand=r['brand'],year=2026,baseyear=2024,last=a.count,previous=b.count,industry=a.industry,label=np.nan,kind='current'))
x=pd.DataFrame(rows);x['industry']=x.industry.fillna('unknown');x['log_count']=np.log1p(x['last']);x['growth']=np.log1p(x['last'])-np.log1p(x.previous);x['feature_report_year']=x.baseyear+1
meta=j[['brandMnno','source_report_year','jngBizStrtDate','dmsCnt']].rename(columns={'brandMnno':'brand','source_report_year':'feature_report_year'});x=x.merge(meta,on=['brand','feature_report_year'],how='left',validate='many_to_one');n=j[['brandMnno','source_report_year']+[c for c in j if c.startswith('national_')]].rename(columns={'brandMnno':'brand','source_report_year':'baseyear'});x=x.merge(n,on=['brand','baseyear'],how='left',validate='many_to_one')
x['brand_age']=x.baseyear-pd.to_numeric(x.jngBizStrtDate.astype(str).str[:4],errors='coerce');x.loc[x.brand_age<0,'brand_age']=np.nan
for c in ['national_frcsCnt','national_newFrcsRgsCnt','national_ctrtEndCnt','national_ctrtCncltnCnt','national_nmChgCnt','dmsCnt']:x[c]=pd.to_numeric(x[c],errors='coerce')
x['log_direct']=np.log1p(x.dmsCnt);x['log_national_count']=np.log1p(x.national_frcsCnt)
for c in ['newFrcsRgsCnt','ctrtEndCnt','ctrtCncltnCnt','nmChgCnt']:x[c+'_rate']=x['national_'+c]/x.national_frcsCnt.where(x.national_frcsCnt>0)
nums=['log_count','growth','brand_age','log_direct','log_national_count']+[c+'_rate' for c in ['newFrcsRgsCnt','ctrtEndCnt','ctrtCncltnCnt','nmChgCnt']]

f=pd.read_csv(P/'permit_support_refined/permit_features.csv');pc=['permit_active','permit_open','permit_closed','permit_name_linked'];x=x.merge(f[['brand','year']+pc],on=['brand','year'],how='left',validate='one_to_one')
for c in pc[:3]:x[c]=np.log1p(x[c])
(O/'protocol.json').write_text(json.dumps(dict(target='count[Y]<count[Y-2]',masked='count[Y-1] never used; permits through Y-1 allowed',train_labels='<=Y-2',comparison='same rows fixed HGB with and without permit auxiliary features',limitation='historical current-name snapshot; permit feature missing imputed with indicator; retrospective reused periods'),indent=2),encoding='utf-8')
out=[]
import hashlib
excluded=set(json.loads((P/'industry_scope.json').read_text(encoding='utf-8'))['excluded_brand_ids']);x=x[~x.brand.isin(excluded)].copy()
holdout={b for b in x.brand.unique() if int(hashlib.sha256(('d06-final-'+b).encode()).hexdigest()[:8],16)%5==0}
(O/'split.json').write_text(json.dumps({'rule':'sha256 d06-final-brand modulo5 equals0; fixed before run; no tuning','holdout_brand_ids':sorted(holdout),'scope':'all years of held-out brands excluded from fitting; later2024 and provisional2025 evaluated; source snapshots previously explored'},indent=2),encoding='utf-8')
for y in [2024,2025]:
 tr=x[x.kind.eq('train')&x.year.le(y-2)&~x.brand.isin(holdout)];te=x[x.kind.eq('train')&x.year.eq(y)&x.brand.isin(holdout)]
 for name,features in [('stale_only',nums),('stale_plus_permits',nums+pc)]:
  pre=ColumnTransformer([('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['industry']),('num',SimpleImputer(strategy='median',add_indicator=True),features)])
  m=make_pipeline(pre,HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,min_samples_leaf=30,l2_regularization=10,learning_rate=.05,random_state=20261119));m.fit(tr,tr.label.astype(int));z=te[['brand','year','label']].copy();z['model']=name;z['probability']=m.predict_proba(te)[:,1];out.append(z)
r=pd.concat(out);r.to_csv(O/'predictions.csv',index=False);metrics=[]
for (y,m),g in r[r.year.lt(2026)].groupby(['year','model']):metrics.append(dict(year=int(y),model=m,n=len(g),brier=float(brier_score_loss(g.label,g.probability)),auc=float(roc_auc_score(g.label,g.probability))))
summary={'metrics':metrics,'current_brands':int(r[r.year.eq(2026)].brand.nunique()),'current_permit_features_available':int(x[x.kind.eq('current')].permit_active.notna().sum()),'service_registry_modified':False};(O/'results.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(pd.DataFrame(metrics).to_string(index=False));print('current',summary['current_brands'])
