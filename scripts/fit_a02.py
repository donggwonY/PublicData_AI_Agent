"""Fixed cafe baseline experiment. Final-test rows never enter outcome construction."""
import json, warnings
from pathlib import Path
import numpy as np
import pandas as pd
import sklearn
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss
from sklearn.exceptions import ConvergenceWarning
from snapshot_hashes import snapshot_sha256, verify_snapshot_hash
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/a02'
def scores(y,p):
    return {'n':len(y),'events':int(y.sum()),'observed_rate':float(y.mean()),'mean_prediction':float(np.mean(p)),
            'auc':float(roc_auc_score(y,p)) if len(set(y))==2 else None,
            'brier':float(brier_score_loss(y,p)),'log_loss':float(log_loss(y,p,labels=[0,1]))}
def main():
    path=ROOT/'service/data/processed/stores.parquet'
    audit=json.loads((OUT/'feasibility.json').read_text(encoding='utf-8'))
    verify_snapshot_hash(path,audit['input_hashes']['stores.parquet'])
    s=pd.read_parquet(path)
    # Exclude reserved years before creating labels or inspecting outcomes.
    s=s.loc[s.ld.between('2010-01-01','2021-12-31') & s.service.isin(['일반음식점','휴게음식점']) & s.category.isin(['커피숍','까페'])].copy()
    s=s.loc[~(s.closed & s.cd.isna()) & ~(s.cd.notna() & s.cd.lt(s.ld))].copy()
    s['month']=s.ld.dt.month.astype(str)
    s['target']=(s.closed & s.cd.notna() & s.cd.le(s.ld+pd.Timedelta(days=365))).astype(int)
    train=s.loc[s.ld.le('2018-12-31')].copy()
    val=s.loc[s.ld.between('2020-01-01','2021-12-31')].copy()
    assert len(train)==5047 and len(val)==1502
    assert train.ld.max()+pd.Timedelta(days=365)<val.ld.min()
    assert not train[['org_code','mgmt_no','service']].duplicated().any()
    cols=['category','gu','month']
    X=train[cols].fillna('MISSING').astype(str); V=val[cols].fillna('MISSING').astype(str)
    model=make_pipeline(OneHotEncoder(handle_unknown='ignore'),LogisticRegression(C=1.0,max_iter=2000,solver='lbfgs',random_state=0))
    with warnings.catch_warnings():
        warnings.simplefilter('error',ConvergenceWarning)
        model.fit(X,train.target)
    p=model.predict_proba(V)[:,1];b=np.full(len(val),train.target.mean())
    assert np.isfinite(p).all() and ((p>0)&(p<1)).all()
    unseen=val.building_key.notna() & ~val.building_key.isin(set(train.building_key.dropna()))
    result={'date':'2026-10-24','sklearn_version':sklearn.__version__,'input_sha256':snapshot_sha256(path),
      'features':cols,'C':1.0,'max_iter':2000,'n_iter':int(model[-1].n_iter_[0]),
      'train_rows':len(train),'train_events':int(train.target.sum()),'train_rate':float(train.target.mean()),
      'validation_baseline':scores(val.target,b),'validation_logistic':scores(val.target,p),
      'new_building_validation':{'baseline':scores(val.loc[unseen,'target'],b[unseen]),'logistic':scores(val.loc[unseen,'target'],p[unseen])},
      'validation_seen_building_rows':int((~unseen & val.building_key.notna()).sum()),
      'validation_missing_building_rows':int(val.building_key.isna().sum()),
      'by_gu':[], 'calibration':[], 'final_test_evaluated':False,'db_written':False}
    for gu in sorted(V.gu.unique()):
        m=V.gu.eq(gu).to_numpy()
        result['by_gu'].append({'gu':gu,'baseline':scores(val.loc[m,'target'],b[m]),'logistic':scores(val.loc[m,'target'],p[m])})
    for low,high in zip([0,.05,.1,.15,.2,.3,.5],[.05,.1,.15,.2,.3,.5,1.0001]):
        m=(p>=low)&(p<high)
        if m.any(): result['calibration'].append({'low':low,'high':min(high,1),'n':int(m.sum()),'predicted':float(p[m].mean()),'observed':float(val.loc[m,'target'].mean())})
    (OUT/'baseline_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
