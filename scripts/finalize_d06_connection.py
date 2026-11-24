from pathlib import Path
import json,pandas as pd,hashlib
P=Path('docs/d06/delivery/revised');r=json.loads((P/'brand_registry.json').read_text(encoding='utf-8'));q=pd.read_csv(P/'source_count_audit.csv');v=q[q['count'].notna()];d={(a.brand,int(a.year)):a for a in v.itertuples()};rates={}
for h in [1,2]:
 rows=[]
 for a in v.itertuples():
  y=int(a.year);b=d.get((a.brand,y-h))
  if y>2026-h or b is None or b.count<3 or (a.brand,y-h-1) not in d:continue
  rows.append((str(b.industry),int(a.count<b.count)))
 t=pd.DataFrame(rows,columns=['industry','label'])
 for ind,g in t.groupby('industry'):rates[h,ind]={'decrease_rate':float(g.label.mean()),'sample_size':len(g),'horizon_years':h,'training_target_year_max':2026-h,'meaning':'과거 동일 업종의 같은 간격 감소 비율. 2026년 실측 비율이 아님'}
for a in r:
 a['generated_date']='2026-11-24'
 if a.get('decline_probability') is not None:a['industry_reference']=rates.get((a['forecast_horizon_years'],str(a['industry'])))
(P/'brand_registry.json').write_text(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');pd.DataFrame([{k:v for k,v in a.items() if k not in ['count_history','permit_support','industry_reference']} for a in r]).to_csv(P/'brand_registry.csv',index=False,encoding='utf-8-sig')
import sys
sys.path.insert(0,str(Path.cwd()))
from scripts.d06_franchise_lookup import lookup_franchise
checks={}
for name in ['CU','BBQ','메가커피']:
 a=lookup_franchise(name);assert a['status']=='ok',(name,a);checks[name]=a['brand_name']
for name in ['세큐T','세큐큐','BRD_20240813','마카롱택시','우버택시']:
 assert lookup_franchise(name)['status']=='not_found',name
assert not any('택시' in str(a['brand_name']) or a['brand']=='BRD_20240813' for a in r)
examples=[lookup_franchise(b) for b in ['CU','BBQ','메가커피','맘스터치','세븐일레븐']];(P/'lookup_examples.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2),encoding='utf-8')
m=json.loads((P/'service_bundle_manifest.json').read_text(encoding='utf-8'));m['files']={n:hashlib.sha256((P/n).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for n in m['files']};(P/'service_bundle_manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf-8');(P/'connection_checks.json').write_text(json.dumps({'search':checks,'taxi_exclusion':True,'period':'baseline year explicitly retained; official2026 unconfirmed','industry_reference':'same horizon historical observed decrease rate','actual_app_test':False},ensure_ascii=False,indent=2),encoding='utf-8');print('CONNECTION CHECKS PASS',checks)
