"""Screen all identifiable historical brand names for district entry candidates."""
from pathlib import Path
import re,json,unicodedata
import pandas as pd
P=Path('docs/d06/expansion');j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet',columns=['brandMnno','brandNm','source_report_year']);x=pd.read_parquet('service/data/processed/stores.parquet',columns=['uid','name','gu','ld','cd','is_primary','building_key'])
def norm(v):return re.sub(r'[^0-9a-z가-힣]','',unicodedata.normalize('NFKC',str(v)).lower())
j=j[j.brandNm.notna()].copy();j['alias']=j.brandNm.map(norm);names=j[['brandMnno','alias']].drop_duplicates();short=names[names.alias.str.len()<4];names=names[names.alias.str.len()>=4];amb=names.groupby('alias').brandMnno.nunique();bad=set(amb[amb>1].index);names=names[~names.alias.isin(bad)];mapping=dict(zip(names.alias,names.brandMnno));pat=re.compile('|'.join(re.escape(n) for n in sorted(mapping,key=len,reverse=True)))
x=x[x.is_primary.eq(True)].copy();x['normalized']=x.name.fillna('').map(norm)
def match(v):
 ids={mapping[m.group()] for m in pat.finditer(v)}
 return next(iter(ids)) if len(ids)==1 else None
x['brand']=x.normalized.map(match);x=x[x.brand.notna()].copy();x['ld']=pd.to_datetime(x.ld,errors='coerce');x['cd']=pd.to_datetime(x.cd,errors='coerce');districts=['중구','동구','서구','남구','북구','수성구','달서구','달성군'];x=x[x.gu.isin(districts)&x.ld.notna()];rows=[]
# Require same alias to occur in the historical report list, not only current names.
for y in range(2017,2026):
 available=j[j.source_report_year==y+1];allowed=set(available.alias)&set(mapping)
 g=x[x.brand.isin(available.brandMnno)].copy()
 # Validate each matched brand has at least one of its year-specific aliases in the permit name.
 by=available[available.alias.isin(allowed)].groupby('brandMnno').alias.apply(list).to_dict()
 g=g[g.apply(lambda r:any(a in r.normalized for a in by.get(r.brand,[])),axis=1)]
 active=g[(g.ld<=pd.Timestamp(y,12,31))&(g.cd.isna()|(g.cd>pd.Timestamp(y,12,31)))];counts=active.groupby(['brand','gu']).building_key.nunique()
 for brand in sorted(g.brand.unique()):
  for gu in districts:rows.append((brand,y,gu,int(counts.get((brand,gu),0))))
r=pd.DataFrame(rows,columns=['brand_id','year','gu','observed_active_buildings']);r.to_csv(P/'expanded_brand_gu_year.csv',index=False)
r=r.sort_values(['brand_id','gu','year']);gr=r.groupby(['brand_id','gu']);r['previous_year']=gr.year.shift();r['previous_count']=gr.observed_active_buildings.shift();eligible=r[(r.year==r.previous_year+1)&(r.previous_count==0)].copy();eligible['entry_candidate']=eligible.observed_active_buildings>0;eligible.to_csv(P/'expanded_entry_candidates.csv',index=False)
annual=eligible.groupby('year').agg(at_risk_cells=('entry_candidate','size'),entry_candidates=('entry_candidate','sum'));annual.to_csv(P/'expanded_annual.csv')
summary=dict(matched_permit_rows=len(x),matched_brands=x.brand.nunique(),panel_brands=r.brand_id.nunique(),excluded_short_aliases=len(short),excluded_shared_aliases=len(bad),entry_candidates=int(eligible.entry_candidate.sum()),entry_brands=int(eligible[eligible.entry_candidate].brand_id.nunique()),scope='unverified literal-name matching; observed permit buildings, not verified franchise stores; zero means no linked records, not confirmed absence; Gunwi excluded for fixed geography')
(P/'expanded_results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False));print(annual.to_string())