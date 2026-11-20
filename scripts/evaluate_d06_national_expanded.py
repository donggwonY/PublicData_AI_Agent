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

O=Path('docs/d06/decline/additional/expanded_national');O.mkdir(exist_ok=True)
# One additional report-year lag for the previous nationwide figures.
prev=n[['year','brand','national_frcsCnt','national_avrgSlsAmt']].copy();prev.year+=1;prev=prev.rename(columns={'national_frcsCnt':'previous_national_count','national_avrgSlsAmt':'previous_national_sales'});x=x.merge(prev,on=['year','brand'],how='left',validate='many_to_one')
for c in ['national_avrgSlsAmt','previous_national_sales','previous_national_count']:x[c]=pd.to_numeric(x[c],errors='coerce')
x['national_count_growth']=np.log1p(x.national_frcsCnt)-np.log1p(x.previous_national_count)
x['national_log_sales']=np.log(x.national_avrgSlsAmt.where(x.national_avrgSlsAmt>0));x['national_sales_growth']=x.national_log_sales-np.log(x.previous_national_sales.where(x.previous_national_sales>0))
x['national_net_open_rate']=x.newFrcsRgsCnt_rate-x.ctrtEndCnt_rate-x.ctrtCncltnCnt_rate
nums=['log_count','growth']+extra+['national_count_growth','national_log_sales','national_sales_growth','national_net_open_rate']
protocol=dict(scope='same frozen Daegu3+ sample, exploratory reused years',development=[2022,2023],evaluation=[2024],provisional=[2025],added=['national count change','national sales level and change','national openings minus terminations and cancellations divided by national count'],source='approved brand statistics source, previously collected unused fields; external eatout API returned403 and not used',timing='national report year target-1 and target-2 only',selection='development pooled Brier against stored additional HGB; no choice using2024/2025',model='fixed HGB100 leaves7 min30 l2=10 lr=.05')
(O/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
def run(years):
 out=[]
 for y in years:
  tr=x[x.year<y];te=x[x.year==y];pre=ColumnTransformer([('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['industry']),('num',SimpleImputer(strategy='median',add_indicator=True),nums)]);m=make_pipeline(pre,HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,min_samples_leaf=30,l2_regularization=10,learning_rate=.05,random_state=20261119));m.fit(tr,tr.label)
  z=te[['brand','year','label']].copy();z['model']='expanded';z['probability']=m.predict_proba(te)[:,1];out.append(z)
 return pd.concat(out,ignore_index=True)
old=pd.read_csv(P/'predictions.csv');old=old[old.model=='additional'];dev=run([2022,2023]);ref=old[old.year.isin([2022,2023])];choice='expanded' if brier_score_loss(dev.label,dev.probability)<brier_score_loss(ref.label,ref.probability) else 'additional';(O/'selection.json').write_text(json.dumps(dict(selected=choice,development_expanded_brier=float(brier_score_loss(dev.label,dev.probability)),development_reference_brier=float(brier_score_loss(ref.label,ref.probability))),indent=2),encoding='utf-8')
r=pd.concat([old,dev,run([2024,2025])]);r.to_csv(O/'predictions.csv',index=False);rows=[]
for (y,name),g in r.groupby(['year','model']):rows.append(dict(year=int(y),model=name,n=len(g),brier=float(brier_score_loss(g.label,g.probability)),auc=float(roc_auc_score(g.label,g.probability)),precision=float(precision_score(g.label,g.probability>=.5,zero_division=0)),recall=float(recall_score(g.label,g.probability>=.5,zero_division=0))))
availability=x.groupby('year')[['national_count_growth','national_log_sales','national_sales_growth']].agg(lambda s:float(s.notna().mean())).reset_index();availability.to_csv(O/'availability.csv',index=False)
(O/'results.json').write_text(json.dumps(dict(selected=choice,annual=rows),indent=2),encoding='utf-8');assert not r.duplicated(['brand','year','model']).any();print('selected',choice);print(pd.DataFrame(rows).to_string(index=False))
