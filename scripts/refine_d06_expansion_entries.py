from pathlib import Path
import pandas as pd,re,unicodedata,json
P=Path('docs/d06/expansion');e=pd.read_csv(P/'entry_quality_cells.csv');e=e[e.entry_candidate & e.brand_present_elsewhere].copy();j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet',columns=['brandMnno','brandNm','source_report_year']);x=pd.read_parquet('service/data/processed/stores.parquet',columns=['uid','name','gu','ld','cd','is_primary'])
def norm(v):return re.sub(r'[^0-9a-z가-힣]','',unicodedata.normalize('NFKC',str(v)).lower())
x=x[x.is_primary.eq(True)].copy();x['ld']=pd.to_datetime(x.ld,errors='coerce');x['cd']=pd.to_datetime(x.cd,errors='coerce');x['n']=x.name.fillna('').map(norm);j=j[j.brandNm.notna()].copy();j['alias']=j.brandNm.map(norm)
by=j.groupby(['brandMnno','source_report_year']).alias.apply(set).to_dict();allowners=j.groupby('alias').brandMnno.apply(set).to_dict();rows=[];matches=[]
for r in e.itertuples():
 y=int(r.year);old=by.get((r.brand_id,y),set());now=by.get((r.brand_id,y+1),set());stable={a for a in old&now if len(a)>=4 and len(allowners[a])==1}
 g=x[(x.gu==r.gu)&(x.ld.dt.year==y)&(x.cd.isna()|(x.cd>pd.Timestamp(y,12,31)))];anywhere=[];prefix=[]
 for z in g.itertuples():
  used=[a for a in stable if a in z.n]
  if used:anywhere.append(z)
  if any(z.n.startswith(a) for a in used):prefix.append(z)
 status='stable_name_new_prefix' if prefix else 'stable_name_new_nonprefix' if anywhere else 'no_stable_alias' if not stable else 'no_stable_name_new_permit'
 rows.append(dict(brand_id=r.brand_id,brand_name=r.brandNm,year=y,gu=r.gu,reentry=bool(r.reentry_candidate),stable_alias_count=len(stable),new_substring_matches=len(anywhere),new_prefix_matches=len(prefix),review_status=status))
 for z in (prefix or anywhere)[:3]:matches.append(dict(brand_id=r.brand_id,year=y,gu=r.gu,permit_name=z.name,uid=z.uid,matched_as_prefix=z in prefix))
r=pd.DataFrame(rows);r.to_csv(P/'entry_refinement.csv',index=False);pd.DataFrame(matches).to_csv(P/'entry_refinement_names.csv',index=False)
summary=dict(original_positive_candidates=len(e),status_counts=r.review_status.value_counts().to_dict(),prefix_candidates_excluding_reentry=int(((r.review_status=='stable_name_new_prefix')&~r.reentry).sum()),meaning='stricter candidate audit only, not verified franchise affiliation; removed candidates remain unknown not negative labels')
(P/'entry_refinement_results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False))
