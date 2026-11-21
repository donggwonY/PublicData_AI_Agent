"""Rebuild count observations without treating missing rows or fields as zero."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss,roc_auc_score,precision_score,recall_score
P=Path('docs/d06/delivery/revised');P.mkdir(exist_ok=True)
j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet');d=pd.read_parquet('data/raw/franchise/daegu_panel.parquet')
a=j[['brandMnno','acntgYr','frcsCnt','brandNm','indutyMlsfcNm','dmsCnt','jngBizStrtDate','source_report_year']].rename(columns={'brandMnno':'brand','acntgYr':'year','frcsCnt':'region_count','brandNm':'brand_name','indutyMlsfcNm':'industry'})
a['year']=pd.to_numeric(a.year);a['region_row_present']=True
b=d[['brandMnno','year','stores','indutyMlsfcNm']].rename(columns={'brandMnno':'brand','stores':'sales_count','indutyMlsfcNm':'sales_industry'});b['sales_row_present']=True
q=a.merge(b,on=['brand','year'],how='outer',validate='one_to_one')
for c in ['region_count','sales_count']:q[c]=pd.to_numeric(q[c],errors='coerce');q.loc[(q[c]<0)|(q[c]%1!=0),c]=np.nan
q['conflict']=q.region_count.notna()&q.sales_count.notna()&q.region_count.ne(q.sales_count);q['count']=q.region_count.combine_first(q.sales_count);q.loc[q.conflict,'count']=np.nan
q['count_source']=np.select([q.conflict,q.region_count.notna(),q.sales_count.notna()],['conflict','region_api','sales_api'],default='unavailable');q['industry']=q.industry.combine_first(q.sales_industry)
q.to_csv(P/'source_count_audit.csv',index=False)
# Known annual observations only; explicit zero kept. Last observed year never replaced by absent year.
valid=q[q['count'].notna()].copy();lookup={(r.brand,int(r.year)):r for r in valid.itertuples()};rows=[]
for r in valid.itertuples():
 y=int(r.year);base=lookup.get((r.brand,y-1));prev=lookup.get((r.brand,y-2))
 if base is None or prev is None or base.count<3:continue
 rows.append(dict(brand=r.brand,year=y,last=base.count,previous=prev.count,label=int(r.count<base.count),industry=base.industry,actual=r.count))
x=pd.DataFrame(rows)
latest=valid[valid.year==2025].merge(valid[valid.year==2024][['brand','count']].rename(columns={'count':'previous'}),on='brand',how='left',validate='one_to_one');latest=latest[latest['count'].ge(3)&latest.previous.notna()].copy();latest=latest.rename(columns={'count':'last'});latest['year']=2026
x=x.assign(kind='train');latest=latest.assign(kind='current');z=pd.concat([x,latest[['brand','year','last','previous','industry','kind']]],ignore_index=True);z['log_count']=np.log1p(z['last']);z['growth']=np.log1p(z['last'])-np.log1p(z.previous)
meta=j[['brandMnno','source_report_year','jngBizStrtDate','dmsCnt']].rename(columns={'brandMnno':'brand','source_report_year':'year'});z=z.merge(meta,on=['brand','year'],how='left',validate='many_to_one')
cols=[c for c in j if c.startswith('national_')];n=j[['brandMnno','source_report_year']+cols].rename(columns={'brandMnno':'brand','source_report_year':'year'});n['year']+=1;z=z.merge(n,on=['brand','year'],how='left',validate='many_to_one')
z['brand_age']=z.year-1-pd.to_numeric(z.jngBizStrtDate.astype(str).str[:4],errors='coerce');z.loc[z.brand_age<0,'brand_age']=np.nan
for c in cols+['dmsCnt']:z[c]=pd.to_numeric(z[c],errors='coerce')
for c in ['newFrcsRgsCnt','ctrtEndCnt','ctrtCncltnCnt','nmChgCnt']:z[c+'_rate']=z['national_'+c]/z.national_frcsCnt.where(z.national_frcsCnt>0)
z['log_national_count']=np.log1p(z.national_frcsCnt);z['log_direct']=np.log1p(z.dmsCnt);z['industry']=z.industry.fillna('unknown')
nums=['log_count','growth','brand_age','log_direct','log_national_count']+[c+'_rate' for c in ['newFrcsRgsCnt','ctrtEndCnt','ctrtCncltnCnt','nmChgCnt']]
def fit(tr):
 pre=ColumnTransformer([('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['industry']),('num',SimpleImputer(strategy='median',add_indicator=True),nums)]);m=make_pipeline(pre,HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,min_samples_leaf=30,l2_regularization=10,learning_rate=.05,random_state=20261119));return m.fit(tr,tr.label.astype(int))
preds=[];metrics=[]
for y in [2022,2023,2024,2025]:
 tr=z[(z.kind=='train')&(z.year<y)];te=z[(z.kind=='train')&(z.year==y)];m=fit(tr);prob=m.predict_proba(te)[:,1];v=te[['brand','year','label']].copy();v['probability']=prob;preds.append(v);metrics.append(dict(year=y,n=len(te),brier=float(brier_score_loss(te.label,prob)),auc=float(roc_auc_score(te.label,prob)),precision=float(precision_score(te.label,prob>=.5,zero_division=0)),recall=float(recall_score(te.label,prob>=.5,zero_division=0))))
tr=z[(z.kind=='train')&(z.year<=2025)];te=z[z.kind=='current'].copy();m=fit(tr);te['decline_probability']=m.predict_proba(te)[:,1]
# Historical three-plus brands remain searchable even when latest counts are missing.
cohort=set(valid[valid['count'].ge(3)].brand);last=valid[valid.brand.isin(cohort)].sort_values(['brand','year']).groupby('brand').tail(1);registry=last[['brand','year','count','industry','count_source']].rename(columns={'year':'last_observed_accounting_year','count':'last_observed_stores'});names=q[q.brand_name.notna()].sort_values('year').groupby('brand').tail(1)[['brand','brand_name']];registry=registry.merge(names,on='brand',how='left',validate='one_to_one');registry=registry.merge(te[['brand','decline_probability']],on='brand',how='left',validate='one_to_one')
registry['status']=np.select([registry.last_observed_accounting_year.lt(2025),registry.last_observed_stores.lt(3),registry.decline_probability.notna()],['latest_count_unavailable','below_three_stores','current_projection'],default='prior_year_unavailable')
registry['target_accounting_year']=np.where(registry.decline_probability.notna(),2026,None);registry['generated_date']='2026-11-21';registry['message']=registry.apply(lambda r:f'{int(r.last_observed_accounting_year)}년 말에는 대구 가맹점 {int(r.last_observed_stores)}개가 확인돼요. 최신 연도 수치가 확인되지 않아 현재 전망은 제공하지 않아요.' if r.status=='latest_count_unavailable' else '확인된 매장 수와 자료 연도를 함께 안내해요.',axis=1)

registry['count_history']=registry.brand.map(valid.groupby('brand').apply(lambda g:g.sort_values('year')[['year','count','count_source']].to_dict('records'),include_groups=False).to_dict())
national_fields=['national_frcsCnt','national_newFrcsRgsCnt','national_ctrtEndCnt','national_ctrtCncltnCnt']
registry=registry.merge(te[['brand']+national_fields],on='brand',how='left',validate='one_to_one')
registry.to_csv(P/'brand_registry.csv',index=False,encoding='utf-8-sig');(P/'brand_registry.json').write_text(json.dumps(json.loads(registry.to_json(orient='records',force_ascii=False)),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');pd.concat(preds).to_csv(P/'validation_predictions.csv',index=False);pd.DataFrame(metrics).to_csv(P/'validation_metrics.csv',index=False);te.to_csv(P/'projection_features.csv',index=False)
assert registry.brand.is_unique;assert registry.loc[registry.status=='latest_count_unavailable','decline_probability'].isna().all();assert q.loc[q.conflict,'count'].isna().all()
summary=dict(historical_threeplus_brands=len(registry),status_counts=registry.status.value_counts().to_dict(),conflicting_brand_years=int(q.conflict.sum()),training_rows=len(tr),validation=metrics,source_policy='valid region count first; valid sales API fallback same accounting year; conflicting values unknown; missing never0; not permit counts',target=2026,baseline=2025)
(P/'rebuild_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary))
