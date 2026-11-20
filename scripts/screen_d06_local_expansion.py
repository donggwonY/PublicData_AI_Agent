from pathlib import Path
import json
import pandas as pd
P=Path('docs/d06/expansion');x=pd.read_parquet('service/data/processed/stores.parquet',columns=['uid','name','gu','ld','cd','is_primary','building_key']);j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet',columns=['brandMnno','brandNm','source_report_year'])
x['ld']=pd.to_datetime(x.ld,errors='coerce');x['cd']=pd.to_datetime(x.cd,errors='coerce');x=x[x.is_primary.eq(True)].copy()
valid_gu=['중구','동구','서구','남구','북구','수성구','달서구','달성군'];brands={'BRD_20080600002':'교촌치킨','BRD_20080100157':'맘스터치','BRD_20170451':'선비꼬마김밥'};rows=[];samples=[]
for bid,name in brands.items():
 g=x[x.name.fillna('').str.contains(name,regex=False)].copy()
 if name=='맘스터치':g=g[~g.name.str.contains('피자|치킨전문점',regex=True)]
 for z in g.sort_values('name').head(6).itertuples():samples.append(dict(brand=name,matched_name=z.name,gu=z.gu))
 for y in range(2017,2026):
  # Use only historical brand list at corresponding report year; name matching still provisional.
  if not ((j.brandMnno==bid)&(j.source_report_year==y+1)).any():continue
  cutoff=pd.Timestamp(y,12,31);active=g[(g.ld<=cutoff)&(g.cd.isna()|(g.cd>cutoff))]
  for gu in valid_gu:
   h=active[active.gu==gu];rows.append(dict(brand_id=bid,brand=name,year=y,gu=gu,observed_active_buildings=h.building_key.nunique(),permit_rows=len(h)))
r=pd.DataFrame(rows);r.to_csv(P/'pilot_brand_gu_year.csv',index=False);pd.DataFrame(samples).to_csv(P/'pilot_match_samples.csv',index=False)
events=[]
for (bid,gu),g in r.groupby(['brand_id','gu']):
 g=g.sort_values('year');prev=g.shift()
 for i in g.index:
  if pd.notna(prev.loc[i,'year']) and g.loc[i,'year']==prev.loc[i,'year']+1 and prev.loc[i,'observed_active_buildings']==0 and g.loc[i,'observed_active_buildings']>0:events.append(dict(brand=g.loc[i,'brand'],gu=gu,year=int(g.loc[i,'year'])))
(P/'pilot_results.json').write_text(json.dumps(dict(scope='provisional name-matched primary permit building counts, not verified franchise counts; excludes Gunwi and invalid district strings',cells=len(r),observed_zero_to_positive_events=events,matching='literal brand substring; related Momstouch pizza/chicken-specialty labels excluded; branch validity not manually verified'),ensure_ascii=False,indent=2),encoding='utf-8')
print(r[r.year==2024].groupby('brand').agg(districts=('observed_active_buildings',lambda s:int((s>0).sum())),buildings=('observed_active_buildings','sum')).to_string());print('zero-to-positive events',json.dumps(events,ensure_ascii=False));print(pd.DataFrame(samples).head(8).to_string(index=False))
