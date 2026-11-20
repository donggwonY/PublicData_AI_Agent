from pathlib import Path
import json,gzip
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.metrics import brier_score_loss,precision_score,recall_score,roc_auc_score
P=Path('docs/d06/decline/additional');P.mkdir(exist_ok=True)
x=pd.read_csv(P.parent/'eligible_cells.csv');j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet')
# Metadata same report year as feature accounting year+1; national statistics one more report year lag.
meta=j[['source_report_year','brandMnno','jngBizStrtDate','dmsCnt']].rename(columns={'source_report_year':'year','brandMnno':'brand'})
x=x.merge(meta,on=['year','brand'],how='left',validate='many_to_one')
cols=[c for c in j if c.startswith('national_')];n=j[['source_report_year','brandMnno']+cols].rename(columns={'source_report_year':'year','brandMnno':'brand'});n['year']=n.year+1
x=x.merge(n,on=['year','brand'],how='left',validate='many_to_one')
x['brand_age']=x.year-1-pd.to_numeric(x.jngBizStrtDate.astype(str).str[:4],errors='coerce');x.loc[x.brand_age<0,'brand_age']=np.nan
for c in cols+['dmsCnt']:x[c]=pd.to_numeric(x[c],errors='coerce')
for c in ['newFrcsRgsCnt','ctrtEndCnt','ctrtCncltnCnt','nmChgCnt']:x[c+'_rate']=x['national_'+c]/x.national_frcsCnt.where(x.national_frcsCnt>0)
x['log_national_count']=np.log1p(x.national_frcsCnt);x['log_direct']=np.log1p(x.dmsCnt)
extra=['brand_age','log_direct','log_national_count']+[c+'_rate' for c in ['newFrcsRgsCnt','ctrtEndCnt','ctrtCncltnCnt','nmChgCnt']]

O=Path('docs/d06/decline/additional/eatout_context');O.mkdir(exist_ok=True);groups=[]
fee=['jngBzmnJngAmt','jngBzmnEduAmt','jngBzmnGrnteAmt','jngBzmnEtcAmt','depstAmt','intrrAmt'];term=['frstCtrtYycnt','prlgCtrtYycnt']
manifest=json.loads(Path('docs/d06/decline/additional/eatout_manifest.json').read_text())
for year in range(2017,2026):
 f=Path(f'data/raw/d06_franchise/eatout_{year}.jsonl.gz');import hashlib
 assert hashlib.sha256(f.read_bytes()).hexdigest()==manifest[str(year)]['sha256']
 a=pd.DataFrame([json.loads(line) for line in gzip.decompress(f.read_bytes()).decode('utf-8').splitlines() if line.strip()])
 if len(a)==0:continue
 for col in fee+term:a[col]=pd.to_numeric(a[col],errors='coerce');a.loc[a[col]<0,col]=np.nan
 # Context uses target-1 report year, like national contract features. No anonymous ID linkage.
 g=a.groupby('tpbizMclsfNm')[fee+term].median().reset_index().rename(columns={'tpbizMclsfNm':'industry',**{c:'industry_'+c for c in fee+term}});g['year']=year+1;groups.append(g)
context=pd.concat(groups,ignore_index=True);context.to_csv(O/'industry_context.csv',index=False);x=x.merge(context,on=['year','industry'],how='left',validate='many_to_one');x=x[x['industry_frstCtrtYycnt'].notna()].copy()
new=[]
for col in fee:
 name='log_industry_'+col;x[name]=np.log1p(x['industry_'+col]);new.append(name)
new+=['industry_'+c for c in term];nums=['log_count','growth']+extra+new
protocol=dict(source='eatout15165094; national industry medians, not brand-specific costs',no_anonymous_id_link=True,timing='target-1 report only; actual release dates unknown',population='same matched food-context subset for existing and context model',development=[2022,2023],evaluation=[2024],provisional=[2025],selection='development Brier',features=new,model='same fixed HGB settings',scope='exploratory reused evaluation years')
(O/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
def run(years):
 out=[]
 for y in years:
  tr=x[x.year<y];te=x[x.year==y]
  # Retrain both methods on the SAME food sample, so the comparison isolates context inputs.
  for name,features in [('food_base',['log_count','growth']+extra),('food_context',nums)]:
   pre=ColumnTransformer([('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['industry']),('num',SimpleImputer(strategy='median',add_indicator=True),features)]);m=make_pipeline(pre,HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,min_samples_leaf=30,l2_regularization=10,learning_rate=.05,random_state=20261119));m.fit(tr,tr.label);z=te[['brand','year','label']].copy();z['model']=name;z['probability']=m.predict_proba(te)[:,1];out.append(z)
 return pd.concat(out,ignore_index=True)
dev=run([2022,2023]);ds={name:float(brier_score_loss(g.label,g.probability)) for name,g in dev.groupby('model')};chosen=min(ds,key=ds.get);(O/'selection.json').write_text(json.dumps(dict(selected=chosen,development=ds),indent=2),encoding='utf-8');r=pd.concat([dev,run([2024,2025])]);r.to_csv(O/'predictions.csv',index=False);rows=[]
for (y,name),g in r.groupby(['year','model']):rows.append(dict(year=int(y),model=name,n=len(g),brier=float(brier_score_loss(g.label,g.probability)),auc=float(roc_auc_score(g.label,g.probability)),precision=float(precision_score(g.label,g.probability>=.5,zero_division=0)),recall=float(recall_score(g.label,g.probability>=.5,zero_division=0))))
(O/'results.json').write_text(json.dumps(dict(selected=chosen,annual=rows),indent=2),encoding='utf-8');print('selected',chosen);print(pd.DataFrame(rows).to_string(index=False))
