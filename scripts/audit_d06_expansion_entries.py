from pathlib import Path
import pandas as pd,re,unicodedata,json
P=Path('docs/d06/expansion');events=pd.read_csv(P/'entry_review_sample.csv');j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet');x=pd.read_parquet('service/data/processed/stores.parquet',columns=['uid','name','gu','ld','cd','is_primary']);x=x[x.is_primary.eq(True)].copy()
def norm(v):return re.sub(r'[^0-9a-z가-힣]','',unicodedata.normalize('NFKC',str(v)).lower())
x['n']=x.name.fillna('').map(norm);x['ld']=pd.to_datetime(x.ld,errors='coerce');x['cd']=pd.to_datetime(x.cd,errors='coerce');rows=[];samples=[]
for r in events.itertuples():
 y=int(r.year);current=j[(j.brandMnno==r.brand_id)&(j.source_report_year==y+1)];prior=j[(j.brandMnno==r.brand_id)&(j.source_report_year==y)];aliases={norm(z) for z in current.brandNm.dropna() if len(norm(z))>=4};old={norm(z) for z in prior.brandNm.dropna() if len(norm(z))>=4}
 g=x[(x.gu==r.gu)&x.n.map(lambda v:any(a in v for a in aliases))];end=pd.Timestamp(y,12,31);active=g[(g.ld<=end)&(g.cd.isna()|(g.cd>end))];new=active[active.ld.dt.year==y];older=active[active.ld.dt.year<y]
 rows.append(dict(brand_id=r.brand_id,brand_name=r.brandNm,year=y,gu=r.gu,current_aliases='|'.join(sorted(aliases)),previous_aliases='|'.join(sorted(old)),alias_changed=aliases!=old,active_rows=len(active),new_permit_rows=len(new),older_permit_rows=len(older),all_active_new=len(active)>0 and len(older)==0))
 for z in active.head(3).itertuples():samples.append(dict(brand_id=r.brand_id,brand_name=r.brandNm,year=y,gu=r.gu,permit_name=z.name,permit_date=str(z.ld.date()),closed_date=None if pd.isna(z.cd) else str(z.cd.date()),uid=z.uid))
a=pd.DataFrame(rows);b=pd.DataFrame(samples);a.to_csv(P/'entry_sample_date_audit.csv',index=False);b.to_csv(P/'entry_sample_name_review.csv',index=False)
summary=dict(sample_n=len(a),sample_rule='previously fixed seed20261120 sample30 from positive events with prior city presence; not manual ground-truth check',all_active_rows_new_permits=int(a.all_active_new.sum()),events_with_older_permits=int((a.older_permit_rows>0).sum()),alias_changed_events=int(a.alias_changed.sum()),empty_reconstruction=int(a.active_rows.eq(0).sum()))
(P/'entry_sample_audit.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary));print(b[['brand_name','permit_name','year']].head(18).to_string(index=False));print('older cases');print(a[a.older_permit_rows>0][['brand_name','year','gu','alias_changed','new_permit_rows','older_permit_rows']].to_string(index=False))
