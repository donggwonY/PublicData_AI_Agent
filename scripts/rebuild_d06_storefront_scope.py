"""Rebuild D06 with transportation brands excluded from train, evaluation and delivery."""
from pathlib import Path
import json,runpy,hashlib
import pandas as pd
P=Path('docs/d06/delivery/revised')
j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet')
excluded=set(j.loc[j.indutyMlsfcNm.eq('운송'),'brandMnno'])
(P/'industry_scope.json').write_text(json.dumps({'excluded_industries':['운송'],'excluded_brand_ids':sorted(excluded),'reason':'transport franchise units do not represent comparable local storefront counts','date':'2026-11-22'},ensure_ascii=False,indent=2),encoding='utf-8')
readp=pd.read_parquet;readc=pd.read_csv
def clean(d):
 for c in ['brandMnno','brand','brand_id']:
  if c in d.columns:d=d[~d[c].isin(excluded)].copy()
 return d
pd.read_parquet=lambda *a,**k:clean(readp(*a,**k))
pd.read_csv=lambda *a,**k:clean(readc(*a,**k))
for script in ['rebuild_d06_missing_counts.py','build_d06_two_year_fallback.py','evaluate_d06_missing_latest_permits.py']:
 runpy.run_path('scripts/'+script,run_name='__main__')
r=json.loads((P/'brand_registry.json').read_text(encoding='utf-8'));v=readc(P/'permit_missing_latest/predictions.csv');cur=v[v.year.eq(2026)&v.model.eq('stale_plus_permits')].set_index('brand');f=readc(P/'permit_support_refined/permit_features.csv');f=f[f.year.eq(2026)].set_index('brand')
for a in r:
 if a['status']=='two_year_projection':
  b=a['brand'];a['decline_probability']=float(cur.loc[b,'probability']);a['model_kind']='two_year_hgb_permit_support';a['permit_support']={'year':2025,'linked_active_buildings':int(f.loc[b,'permit_active']),'linked_opened_buildings':int(f.loc[b,'permit_open']),'linked_closed_buildings':int(f.loc[b,'permit_closed']),'meaning':'인허가 건물 활동 지표이며 공식 가맹점 수가 아님'}
assert not excluded.intersection(a['brand'] for a in r)
(P/'brand_registry.json').write_text(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');pd.DataFrame([{k:v for k,v in a.items() if k not in ['count_history','permit_support']} for a in r]).to_csv(P/'brand_registry.csv',index=False,encoding='utf-8-sig')
import sys
sys.path.insert(0,str(Path.cwd()))
from scripts.d06_franchise_lookup import lookup_franchise
old=json.loads((P/'lookup_examples.json').read_text(encoding='utf-8'));examples=[lookup_franchise(a['brand_id']) for a in old if a['brand_id'] not in excluded];(P/'lookup_examples.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2),encoding='utf-8')
m=json.loads((P/'service_bundle_manifest.json').read_text(encoding='utf-8'));counts=pd.Series([a['status'] for a in r]).value_counts().to_dict();m.update(date='2026-11-22',registry_rows=len(r),forecast_rows=sum(a.get('decline_probability') is not None for a in r),one_year=counts.get('current_projection',0),two_year=counts.get('two_year_projection',0));m['unavailable_current_forecast']=len(r)-m['forecast_rows'];m['industry_scope']='excludes transportation';m['hash_policy']='UTF-8 text normalized CRLF to LF';m['files']={n:hashlib.sha256((P/n).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for n in m['files']};(P/'service_bundle_manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf-8');print('FINAL',m['registry_rows'],m['forecast_rows'],counts)
