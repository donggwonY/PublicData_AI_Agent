"""Build D-06 delivery data from saved historical evaluation; no training or app edits."""
from pathlib import Path
import json,hashlib
import pandas as pd
P=Path('docs/d06/decline/additional');O=Path('docs/d06/delivery');O.mkdir(exist_ok=True)
d=pd.read_csv(P/'predictions.csv');d=d[(d.model=='additional')&d.year.isin([2024,2025])]
x=pd.read_csv(P.parent/'eligible_cells.csv');j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet')
z=d.merge(x,on=['brand','year','label'],validate='one_to_one')
meta=j[['brandMnno','source_report_year','brandNm']].rename(columns={'brandMnno':'brand','source_report_year':'year','brandNm':'brand_name'})
z=z.merge(meta,on=['brand','year'],how='left',validate='many_to_one')
cols=['national_frcsCnt','national_newFrcsRgsCnt','national_ctrtEndCnt','national_ctrtCncltnCnt','national_nmChgCnt']
n=j[['brandMnno','source_report_year']+cols].rename(columns={'brandMnno':'brand','source_report_year':'year'});n['year']=n.year+1;z=z.merge(n,on=['brand','year'],how='left',validate='many_to_one')
out=pd.DataFrame(dict(brand_id=z.brand,brand_name=z.brand_name,industry=z.industry,prediction_kind='historical_evaluation',target_accounting_year=z.year,regional_report_year=z.year,regional_accounting_year=z.year-1,previous_accounting_year=z.year-2,previous_daegu_stores=z.previous,latest_daegu_stores=z['last'],national_report_year=z.year-1,decline_probability=z.probability,model='additional_hgb_unadjusted',national_scope='전국'))
for c in cols:out[c]=pd.to_numeric(z[c],errors='coerce').astype('Int64')
for c in ['brand_name']+cols:out[c+'_status']=out[c].notna().map({True:'observed',False:'unavailable'})
out.to_csv(O/'consultation_data.csv',index=False,encoding='utf-8-sig')
records=json.loads(out.to_json(orient='records',force_ascii=False));(O/'consultation_data.json').write_text(json.dumps(records,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
evaldata=z[['brand','year','actual','label']].rename(columns={'brand':'brand_id','year':'target_accounting_year','actual':'observed_target_stores','label':'observed_decline'});evaldata.to_csv(O/'evaluation_outcomes.csv',index=False,encoding='utf-8-sig')
metrics=json.loads((P/'results.json').read_text(encoding='utf-8'));pd.DataFrame(metrics['annual']).to_csv(O/'model_metrics.csv',index=False,encoding='utf-8-sig')
assert len(out)==1485 and not out.duplicated(['brand_id','target_accounting_year']).any()
assert out.decline_probability.between(0,1).all()
assert not {'actual','label','observed_target_stores','observed_decline'}&set(out.columns)
for c in cols:
 assert (out[c+'_status'].eq('unavailable')==out[c].isna()).all()
 assert out.loc[out[c].eq(0).fillna(False),c+'_status'].eq('observed').all()
manifest=dict(rows=len(out),brands=int(out.brand_id.nunique()),years=sorted(out.target_accounting_year.unique().tolist()),missing={c:int(out[c].isna().sum()) for c in ['brand_name']+cols},files={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in O.iterdir() if f.suffix in ['csv','json'] and f.name!='manifest.json'},checks=['unique brand/year','probabilities within0..1','actual outcomes separated','missing distinct from observed zero'])
(O/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in manifest.items() if k!='files'},ensure_ascii=False))
