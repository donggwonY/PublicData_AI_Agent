"""Fixed three-year mean; historical validation reuse, no final test."""
import json
import numpy as np
import pandas as pd
from fit_a02 import ROOT, OUT, scores
from validate_a02_time import WINDOWS
from snapshot_hashes import verify_snapshot_hash

def main():
    old=json.loads((OUT/'time_validation.json').read_text(encoding='utf-8'))
    path=ROOT/'service/data/processed/stores.parquet'
    verify_snapshot_hash(path,old['input_hash'])
    s=pd.read_parquet(path)
    s=s.loc[s.ld.between('2010-01-01','2021-12-31') & s.service.isin(['일반음식점','휴게음식점']) & s.category.isin(['커피숍','까페'])].copy()
    s=s.loc[~(s.closed & s.cd.isna()) & ~(s.cd.notna() & s.cd.lt(s.ld))].copy()
    s['target']=(s.closed & s.cd.notna() & s.cd.le(s.ld+pd.Timedelta(days=365))).astype(int)
    assert not s[['org_code','mgmt_no','service']].duplicated().any()
    results=[]
    for end,first,last in WINDOWS:
        train=s.loc[s.ld.le(f'{end}-12-31')]
        recent=train.loc[train.ld.ge(f'{end-2}-01-01')]
        val=s.loc[s.ld.between(f'{first}-01-01',f'{last}-12-31')]
        assert len(recent)>0 and recent.ld.max()+pd.Timedelta(days=365)<val.ld.min()
        assert set(recent.index)<=set(train.index) and not set(train.index)&set(val.index)
        prev=next(w for w in old['windows'] if w['validation_period']==f'{first}-{last}')
        base=scores(val.target,np.full(len(val),train.target.mean()))
        for key in ['n','events','brier','log_loss']:
            assert abs(base[key]-prev['baseline'][key])<1e-12
        p=np.full(len(val),recent.target.mean())
        new=val.building_key.notna() & ~val.building_key.isin(set(train.building_key.dropna()))
        results.append({'validation_period':f'{first}-{last}','recent_train_period':f'{end-2}-{end}',
          'recent_train_n':len(recent),'recent_train_events':int(recent.target.sum()),
          'full_mean':base,'recent_mean':scores(val.target,p),'logistic':prev['logistic'],
          'new_buildings':{'recent_mean':scores(val.loc[new,'target'],p[new]),**prev['new_buildings']}})
    out={'date':'2026-10-24','window_years_fixed':3,'input_hash':old['input_hash'],
         'validation_reused':True,'final_test_used':False,'db_written':False,'windows':results}
    (OUT/'recent_baseline.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for w in results:
        print(w['validation_period'],w['recent_train_period'],w['recent_train_n'],w['recent_mean'])
if __name__=='__main__': main()
