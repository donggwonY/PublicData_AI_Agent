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

O=Path('docs/d06/delivery/current');O.mkdir(exist_ok=True)
d=pd.read_parquet('data/raw/franchise/daegu_panel.parquet');latest=d[d.year==2025].copy();prev=d[d.year==2024][['brandMnno','stores']].rename(columns={'stores':'previous'});c=latest.merge(prev,on='brandMnno',how='left',validate='one_to_one');c=c[c.stores.ge(3)&c.previous.notna()].copy();c=c.rename(columns={'brandMnno':'brand','indutyMlsfcNm':'industry'});c['year']=2026;c['log_count']=np.log1p(c.stores);c['growth']=np.log1p(c.stores)-np.log1p(c.previous)
c=c.merge(meta,on=['year','brand'],how='left',validate='many_to_one',suffixes=('','_metadata'));c=c.merge(n,on=['year','brand'],how='left',validate='many_to_one')
c['brand_age']=c.year-1-pd.to_numeric(c.jngBizStrtDate.astype(str).str[:4],errors='coerce');c.loc[c.brand_age<0,'brand_age']=np.nan
for col in cols+['dmsCnt']:c[col]=pd.to_numeric(c[col],errors='coerce')
for col in ['newFrcsRgsCnt','ctrtEndCnt','ctrtCncltnCnt','nmChgCnt']:c[col+'_rate']=c['national_'+col]/c.national_frcsCnt.where(c.national_frcsCnt>0)
c['log_national_count']=np.log1p(c.national_frcsCnt);c['log_direct']=np.log1p(c.dmsCnt)
nums=['log_count','growth']+extra;pre=ColumnTransformer([('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['industry']),('num',SimpleImputer(strategy='median',add_indicator=True),nums)]);model=make_pipeline(pre,HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,min_samples_leaf=30,l2_regularization=10,learning_rate=.05,random_state=20261119));tr=x[x.year<=2025];model.fit(tr,tr.label)
c['decline_probability']=model.predict_proba(c)[:,1];names=j[j.source_report_year==2026][['brandMnno','brandNm']].rename(columns={'brandMnno':'brand','brandNm':'brand_name'});c=c.merge(names,on='brand',how='left',validate='one_to_one')
out=pd.DataFrame(dict(brand_id=c.brand,brand_name=c.brand_name,industry=c.industry,prediction_kind='current_accounting_year_projection',target_accounting_year=2026,baseline_accounting_year=2025,previous_accounting_year=2024,regional_report_year=2026,national_report_year=2025,baseline_daegu_stores=c.stores,previous_daegu_stores=c.previous,decline_probability=c.decline_probability,generated_date='2026-11-20'))
for col in ['national_frcsCnt','national_newFrcsRgsCnt','national_ctrtEndCnt','national_ctrtCncltnCnt']:
 out[col]=pd.to_numeric(c[col],errors='coerce').astype('Int64');out[col+'_status']=out[col].notna().map({True:'observed',False:'unavailable'})
out['brand_name_status']=out.brand_name.notna().map({True:'observed',False:'unavailable'});out.to_csv(O/'consultation_current.csv',index=False,encoding='utf-8-sig');(O/'consultation_current.json').write_text(json.dumps(json.loads(out.to_json(orient='records',force_ascii=False)),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
summary=dict(rows=len(out),known_names=int(out.brand_name.notna().sum()),national_known=int(out.national_frcsCnt.notna().sum()),training_rows=len(tr),training_target_max=int(tr.year.max()),target=2026,baseline=2025,meaning='2026 year-end decline compared with2025, not next12months from generation date and not2027 forecast',mean_probability=float(out.decline_probability.mean()),model_settings='same fixed additional HGB, no probability adjustment',source_limit='latest2025 source may be incomplete; prospective outcome not yet validated')
(O/'generation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');assert out.brand_id.is_unique and out.decline_probability.between(0,1).all();print(json.dumps(summary))
