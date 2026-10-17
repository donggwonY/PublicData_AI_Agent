"""Freeze first D-03 experiment scope and audit temporal/address separation."""
import json
import pandas as pd
from pathlib import Path
from snapshot_hashes import verify_snapshot_hash,snapshot_sha256
ROOT=Path(__file__).resolve().parents[1]

def main():
    baseline=json.loads((ROOT/'docs/d03/baseline.json').read_text(encoding='utf-8'))
    for name,digest in baseline['hashes'].items():verify_snapshot_hash(ROOT/name,digest)
    st=pd.read_parquet(ROOT/'service/data/processed/stores.parquet')
    ref=pd.Timestamp(baseline['reference_date'])
    f=st[st.service.eq('일반음식점') & st.ld.ge('2010-01-01') & st.ld.le(ref-pd.Timedelta(days=365))].copy()
    f['open_year']=f.ld.dt.year
    f['target365']=(f.closed & (f.cd-f.ld).dt.days.le(365)).astype(int)
    masks={'train':f.open_year.between(2010,2018),'validation':f.open_year.between(2020,2021),'test':f.open_year.between(2023,2024)}
    frames={k:f[v].copy() for k,v in masks.items()}
    assert sum(int(m.sum()) for m in masks.values())==int(pd.concat(masks,axis=1).any(axis=1).sum())
    assert (frames['train'].ld+pd.Timedelta(days=365)).max()<frames['validation'].ld.min()
    assert (frames['validation'].ld+pd.Timedelta(days=365)).max()<frames['test'].ld.min()
    assert (frames['test'].ld+pd.Timedelta(days=365)).max()<=ref
    summaries=[]
    train=frames['train']
    for name,g in frames.items():
        row={'split':name,'n':len(g),'min_open':str(g.ld.min().date()),'max_open':str(g.ld.max().date()),
             'missing_gu':int(g.gu.isna().sum()),'missing_category':int(g.category.isna().sum()),
             'uid_overlap_train_rows':int(g.uid.isin(train.uid).sum()) if name!='train' else None,
             'building_overlap_train_rows':int(g.building_key.isin(train.building_key).sum()) if name!='train' else None}
        # Do not create additional test-label summaries during protocol selection.
        if name!='test':row['events365']=int(g.target365.sum())
        summaries.append(row)
    prior_keys=set(train.building_key.dropna())|set(frames['validation'].building_key.dropna())
    new_building=frames['test'].building_key.notna() & ~frames['test'].building_key.isin(prior_keys)
    result={'reference_date':str(ref.date()),'service':'일반음식점','target':'closed and cd-ld <=365 days; full opportunity >=365 days',
            'splits':summaries,'unused_years':[2019,2022,2025],'test_new_building_rows':int(new_building.sum()),
            'features':['category','gu','open_month'],'forbidden':['uid','building_key','name','cd','closed','dur_days','end','current status','units summaries','current auxiliary data'],
            'models_planned':['training prevalence','logistic regression with one-hot categories'],
            'test_policy':'freeze now; prior baseline already contains annual test outcomes, not a fully blind holdout; no model tuning on test',
            'hashes':{'service/data/processed/stores.parquet':snapshot_sha256(ROOT/'service/data/processed/stores.parquet')}}
    (ROOT/'docs/d03/protocol.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
