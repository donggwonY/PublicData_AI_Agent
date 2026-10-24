"""Audit cafe cohort and temporal availability; no model fitting or DB writes."""
import json
from pathlib import Path
import pandas as pd
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1]
def main():
    base=ROOT/'service/data/processed'
    s=pd.read_parquet(base/'stores.parquet')
    poi=pd.read_parquet(base/'poi.parquet')
    meta=json.loads((base/'meta.json').read_text(encoding='utf-8'))
    cutoff=pd.Timestamp(meta['reference_date'])
    cafe=s.loc[s.service.isin(['일반음식점','휴게음식점']) & s.category.isin(['커피숍','까페'])].copy()
    eligible=cafe.loc[cafe.ld.ge('2010-01-01') & cafe.ld.le(cutoff-pd.Timedelta(days=365))].copy()
    unknown=eligible.closed & eligible.cd.isna()
    invalid=eligible.cd.notna() & eligible.cd.lt(eligible.ld)
    known=eligible.loc[~unknown & ~invalid].copy()
    known['event_365']=known.closed & known.cd.notna() & known.cd.le(known.ld+pd.Timedelta(days=365))
    groups=[]
    for label,start,end in [('train','2010-01-01','2018-12-31'),('validation','2020-01-01','2021-12-31'),('test_reserved','2023-01-01','2024-12-31')]:
        d=known.loc[known.ld.between(start,end)]
        groups.append({'split':label,'start':start,'end':end,'rows':len(d),'buildings':int(d.building_key.nunique()),'missing_coords':int(d[['lat','lon']].isna().any(axis=1).sum())})
    result={'checked_date':'2026-10-24','source':'local parquet, no live DB query','reference_date':str(cutoff.date()),
       'license_cafe_definition':{'service':['일반음식점','휴게음식점'],'category':['커피숍','까페']},
       'cafe_license_rows':len(cafe),'eligible_365_rows':len(eligible),'excluded_unknown_close_date':int(unknown.sum()),
       'excluded_invalid_dates':int(invalid.sum()),'known_outcome_rows':len(known),
       'poi_rows':len(poi),'poi_cafe_rows':int(poi.cat_s.eq('카페').sum()),'poi_columns':list(poi.columns),
       'poi_configured_vintage':'2026-06','poi_historical_availability_verified':False,
       'splits_proposed':groups,'model_fitted':False,'test_outcomes_scored':False,
       'input_hashes':{n:snapshot_sha256(base/n) for n in ['stores.parquet','poi.parquet','meta.json']}}
    out=ROOT/'docs/a02';out.mkdir(exist_ok=True)
    (out/'feasibility.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
