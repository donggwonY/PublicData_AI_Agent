from pathlib import Path
import gzip,json,hashlib
import pandas as pd
P=Path('data/raw/d06_franchise');O=Path('docs/d06/decline');manifest=json.loads((O/'acquisition_manifest.json').read_text());rows=[]
def read(name,year):
 f=P/f'{name}_{year}.jsonl.gz';assert hashlib.sha256(f.read_bytes()).hexdigest()==manifest[f.name]['sha256'];d=pd.DataFrame([json.loads(line) for line in gzip.decompress(f.read_bytes()).decode().splitlines()]);assert len(d)==manifest[f.name]['rows'];return d
joined=[]
for y in range(2017,2027):
 b=read('brand_list',y);r=read('brand_region',y);r=r[r.areaNm=='대구'].copy();b=b[['brandMnno','brandNm','corpNm','jngBizStrtDate']].drop_duplicates(); ambiguous_brand_rows=int(b.brandMnno.duplicated(keep=False).sum()); b=b[~b.brandMnno.duplicated(keep=False)]; r=r.drop_duplicates(); assert not r.brandMnno.duplicated().any()
 z=r.merge(b[['brandMnno','brandNm','corpNm','jngBizStrtDate']],on='brandMnno',how='left',validate='one_to_one',indicator=True);count=int((z['_merge']=='both').sum());z=z.drop(columns='_merge')
 stats_matched=ambiguous=0
 if y<=2025:
  t=read('brand_stats',y);keys=['brandNm','corpNm'];bad=t.duplicated(keys,keep=False);ambiguous=int(bad.sum());unique=t[~bad].copy()
  cols=['frcsCnt','newFrcsRgsCnt','ctrtEndCnt','ctrtCncltnCnt','nmChgCnt','avrgSlsAmt']
  unique=unique[keys+cols].rename(columns={c:'national_'+c for c in cols})
  z=z.merge(unique,on=keys,how='left',validate='many_to_one');stats_matched=int(z.national_frcsCnt.notna().sum())
 z['source_report_year']=y;joined.append(z)
 rows.append(dict(report_year=y,daegu_rows=len(r),ambiguous_brand_rows_excluded=ambiguous_brand_rows,brand_name_matched=count,stats_matched=stats_matched,ambiguous_national_rows_excluded=ambiguous,active_three_plus=int((pd.to_numeric(r.frcsCnt)>=3).sum()),accounting_years=sorted(r.acntgYr.astype(str).unique().tolist())))
pd.concat(joined,ignore_index=True).to_parquet(P/'joined_daegu.parquet',index=False)
(O/'source_join_audit.json').write_text(json.dumps(rows,indent=2),encoding='utf-8');print(json.dumps(rows,indent=2))
