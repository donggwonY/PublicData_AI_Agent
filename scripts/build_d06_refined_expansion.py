from pathlib import Path
import re,json,unicodedata
import pandas as pd
P=Path('docs/d06/expansion');O=P/'refined';O.mkdir(exist_ok=True)
j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet');x=pd.read_parquet('service/data/processed/stores.parquet',columns=['name','gu','ld','cd','is_primary','building_key'])
def norm(v):return re.sub(r'[^0-9a-z가-힣]','',unicodedata.normalize('NFKC',str(v)).lower())
j=j[j.brandNm.notna()].copy();j['alias']=j.brandNm.map(norm);pairs=j[['brandMnno','alias']].drop_duplicates();owner=pairs.groupby('alias').brandMnno.nunique();pairs=pairs[(pairs.alias.str.len()>=4)&pairs.alias.map(owner).eq(1)];mapping=dict(zip(pairs.alias,pairs.brandMnno));pat=re.compile('^(?:'+'|'.join(re.escape(a) for a in sorted(mapping,key=len,reverse=True))+')')
x=x[x.is_primary.eq(True)].copy();x['n']=x.name.fillna('').map(norm);x['alias']=x.n.map(lambda s: m.group() if (m:=pat.match(s)) else None);x['brand_id']=x.alias.map(mapping);x=x[x.brand_id.notna()].copy();x['ld']=pd.to_datetime(x.ld,errors='coerce');x['cd']=pd.to_datetime(x.cd,errors='coerce')
old=pd.read_csv(P/'expanded_brand_gu_year.csv');rows=[];newrows=[]
for y in range(2017,2026):
 current=set(zip(j[j.source_report_year==y+1].brandMnno,j[j.source_report_year==y+1].alias));prior=set(zip(j[j.source_report_year==y].brandMnno,j[j.source_report_year==y].alias));stable=current&prior
 g=x[[((b,a) in stable) for b,a in zip(x.brand_id,x.alias)]].copy();g=g[g.ld.notna()];active=g[(g.ld<=pd.Timestamp(y,12,31))&(g.cd.isna()|(g.cd>pd.Timestamp(y,12,31)))];count=active.groupby(['brand_id','gu']).building_key.nunique();new=active[active.ld.dt.year==y].groupby(['brand_id','gu']).size()
 for r in old[(old.year==y)&old.brand_id.isin({b for b,a in stable if a in mapping})].itertuples():rows.append(dict(brand_id=r.brand_id,year=y,gu=r.gu,observed_active_buildings=int(count.get((r.brand_id,r.gu),0)),new_permits=int(new.get((r.brand_id,r.gu),0))))
r=pd.DataFrame(rows);r.to_csv(O/'expanded_brand_gu_year.csv',index=False);r=r.sort_values(['brand_id','gu','year']);gr=r.groupby(['brand_id','gu']);r['prior_year']=gr.year.shift();r['previous_count']=gr.observed_active_buildings.shift();e=r[(r.year==r.prior_year+1)&r.previous_count.eq(0)].copy();e['entry_candidate']=e.observed_active_buildings.gt(0)&e.new_permits.gt(0)
city=r.groupby(['brand_id','year']).observed_active_buildings.sum().rename('previous_city_linked_total').reset_index();city.year+=1;e=e.merge(city,on=['brand_id','year'],validate='many_to_one');e['brand_present_elsewhere']=e.previous_city_linked_total.gt(0);e['previous_count_agrees']=False;e.to_csv(O/'entry_quality_cells.csv',index=False)
summary=dict(rows=len(r),brands=r.brand_id.nunique(),eligible=int(e.brand_present_elsewhere.sum()),entries=int(e[e.brand_present_elsewhere].entry_candidate.sum()),rule='longest globally unique >=4 char prefix, same alias both prior/current reports; observed empty to positive plus target-year new permit; same original panel universe; zero still means no linked records',annual=e[e.brand_present_elsewhere].groupby('year').entry_candidate.agg(['size','sum']).reset_index().to_dict('records'))
(O/'construction.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary))
