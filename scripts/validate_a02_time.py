"""Fixed expanding-window checks; 2023-2024 holdout excluded."""
import json,warnings
import numpy as np
import pandas as pd
import sklearn
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.exceptions import ConvergenceWarning
from fit_a02 import ROOT,OUT,scores
from snapshot_hashes import verify_snapshot_hash
# Preselected nonoverlapping validation windows; no tuning by results.
WINDOWS=[(2013,2015,2016),(2015,2017,2018),(2018,2020,2021)]
def main():
    audit=json.loads((OUT/'feasibility.json').read_text(encoding='utf-8'))
    path=ROOT/'service/data/processed/stores.parquet'
    verify_snapshot_hash(path,audit['input_hashes']['stores.parquet'])
    s=pd.read_parquet(path)
    s=s.loc[s.ld.between('2010-01-01','2021-12-31') & s.service.isin(['일반음식점','휴게음식점']) & s.category.isin(['커피숍','까페'])].copy()
    s=s.loc[~(s.closed & s.cd.isna()) & ~(s.cd.notna() & s.cd.lt(s.ld))].copy()
    s['month']=s.ld.dt.month.astype(str)
    s['target']=(s.closed & s.cd.notna() & s.cd.le(s.ld+pd.Timedelta(days=365))).astype(int)
    assert not s[['org_code','mgmt_no','service']].duplicated().any()
    results=[]; seen=set()
    for end,first,last in WINDOWS:
        tr=s.loc[s.ld.le(f'{end}-12-31')];v=s.loc[s.ld.between(f'{first}-01-01',f'{last}-12-31')]
        assert len(tr)>0 and len(v)>0 and tr.target.nunique()==2
        assert tr.ld.max()+pd.Timedelta(days=365)<v.ld.min()
        assert not seen.intersection(v.index);seen.update(v.index)
        cols=['category','gu','month']
        m=make_pipeline(OneHotEncoder(handle_unknown='ignore'),LogisticRegression(C=1,max_iter=2000,solver='lbfgs',random_state=0))
        with warnings.catch_warnings():
            warnings.simplefilter('error',ConvergenceWarning)
            m.fit(tr[cols].fillna('MISSING').astype(str),tr.target)
        pred=m.predict_proba(v[cols].fillna('MISSING').astype(str))[:,1]
        base=np.full(len(v),tr.target.mean())
        assert np.isfinite(pred).all() and ((pred>0)&(pred<1)).all()
        new=v.building_key.notna() & ~v.building_key.isin(set(tr.building_key.dropna()))
        result={'train_period':f'2010-{end}','validation_period':f'{first}-{last}',
            'train_n':len(tr),'train_events':int(tr.target.sum()),'iterations':int(m[-1].n_iter_[0]),
            'baseline':scores(v.target,base),'logistic':scores(v.target,pred),
            'new_buildings':{'baseline':scores(v.loc[new,'target'],base[new]),'logistic':scores(v.loc[new,'target'],pred[new])}}
        result['mean_overprediction_pp']=100*(result['logistic']['mean_prediction']-result['logistic']['observed_rate'])
        results.append(result)
    original=json.loads((OUT/'baseline_validation.json').read_text(encoding='utf-8'))
    for k in ['auc','brier','log_loss']:
        assert abs(results[-1]['logistic'][k]-original['validation_logistic'][k])<1e-12
    out={'date':'2026-10-24','windows':results,'features':['category','gu','month'],'C':1,
         'input_hash':audit['input_hashes']['stores.parquet'],'sklearn_version':sklearn.__version__,
         'final_test_used':False,'prior_validation_reused':'2020-2021; confirmatory reproduction, not new independent evidence',
         'hyperparameters_tuned':False,'db_written':False}
    (OUT/'time_validation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for r in results: print(r['validation_period'],r['baseline'],r['logistic'],'overprediction_pp',r['mean_overprediction_pp'])
if __name__=='__main__':main()
