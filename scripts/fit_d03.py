"""Fit the predeclared D-03 baseline and logistic candidate; validation only."""
import json,platform,warnings
from pathlib import Path
import numpy as np
import pandas as pd
import sklearn,scipy
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.metrics import brier_score_loss,log_loss,roc_auc_score,average_precision_score
from sklearn.exceptions import ConvergenceWarning
from snapshot_hashes import snapshot_sha256,verify_snapshot_hash
ROOT=Path(__file__).resolve().parents[1]

def metrics(y,p):
    return {'n':len(y),'events':int(np.sum(y)),'actual_pct':float(np.mean(y)*100),'predicted_pct':float(np.mean(p)*100),
            'brier':float(brier_score_loss(y,p)),'log_loss':float(log_loss(y,p,labels=[0,1])),
            'roc_auc':float(roc_auc_score(y,p)) if len(np.unique(y))==2 else None,
            'average_precision':float(average_precision_score(y,p)) if np.sum(y)>0 else None}

def main():
    out=ROOT/'docs/d03'
    protocol=json.loads((out/'protocol.json').read_text(encoding='utf-8'))
    for name,digest in protocol['hashes'].items():verify_snapshot_hash(ROOT/name,digest)
    st=pd.read_parquet(ROOT/'service/data/processed/stores.parquet')
    # Do not form labels or predictions for test years in this experiment.
    f=st[st.service.eq('일반음식점') & st.ld.dt.year.between(2010,2021)].copy()
    train=f[f.ld.dt.year.between(2010,2018)].copy()
    val=f[f.ld.dt.year.between(2020,2021)].copy()
    assert len(train)==22960 and len(val)==5681
    assert (train.ld+pd.Timedelta(days=365)).max()<val.ld.min()
    cols=['category','gu','open_month']
    assert cols==protocol['features']
    def features(frame):
        return frame.assign(open_month=frame.ld.dt.month)[cols].astype('string').fillna('__MISSING__').astype(str)
    def target(frame):return (frame.closed & (frame.cd-frame.ld).dt.days.le(365)).astype(int).to_numpy()
    x=features(train);xv=features(val);y=target(train);yv=target(val)
    model=Pipeline([('onehot',OneHotEncoder(handle_unknown='ignore')),('logistic',LogisticRegression(C=1.0,class_weight=None,solver='lbfgs',max_iter=2000,random_state=0))])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        model.fit(x,y)
    assert not any(issubclass(w.category,ConvergenceWarning) for w in caught),'Convergence failure'
    p=model.predict_proba(xv)[:,1]
    base=np.full(len(val),float(y.mean()))
    assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all()
    assert np.allclose(p,model.predict_proba(xv)[:,1])
    scores={'constant':metrics(yv,base),'logistic':metrics(yv,p)}
    regions=[]
    for gu,idx in val.reset_index(drop=True).groupby('gu',dropna=False).groups.items():
        ix=np.asarray(list(idx));regions.append({'gu':str(gu),'constant':metrics(yv[ix],base[ix]),'logistic':metrics(yv[ix],p[ix]),'small_n':len(ix)<30})
    # Fixed probability bins, not selected using outcomes.
    bins=pd.cut(p,[-0.000001,.05,.10,.15,.20,.30,.50,1.0],include_lowest=True)
    cal=pd.DataFrame({'bin':bins,'pred':p,'actual':yv}).groupby('bin',observed=True).agg(n=('actual','size'),mean_pred=('pred','mean'),actual_rate=('actual','mean')).reset_index()
    cal['bin']=cal['bin'].astype(str)
    unknown={c:int((~xv[c].isin(x[c].unique())).sum()) for c in cols}
    result={'scope':'validation only; test set not predicted or scored','features':cols,'train_n':len(train),'train_events':int(y.sum()),'validation':scores,
            'probability_bins':json.loads(cal.to_json(orient='records')),'regions':regions,'unseen_feature_rows':unknown,
            'iterations':model.named_steps['logistic'].n_iter_.tolist(),'params':{'C':1.0,'solver':'lbfgs','max_iter':2000,'class_weight':None,'random_state':0},
            'versions':{'python':platform.python_version(),'pandas':pd.__version__,'numpy':np.__version__,'scipy':scipy.__version__,'scikit-learn':sklearn.__version__},
            'hashes':{'protocol':snapshot_sha256(out/'protocol.json'),'script':snapshot_sha256(Path(__file__)),'stores':protocol['hashes']['service/data/processed/stores.parquet']}}
    (out/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    b=scores['constant'];m=scores['logistic']
    lines=['# D-03 첫 모델 검증 결과','', '일반음식점 2010~2018년 개업 기록으로 학습하고 2020~2021년 개업 기록으로 검증했다. 최종 평가(2023~2024년)는 예측·채점하지 않았다.', '',
           '입력은 업태·구군·개업 월뿐이다. 범주 인코더와 모델 모두 학습 자료에만 적합했다. 수렴 검사와 예측 확률 범위·재호출 일치 검사 통과.', '',
           '```text',pd.DataFrame(scores).T.to_string(),'```','',
           f'로지스틱 회귀의 Brier 변화(모델−상수)는 {m["brier"]-b["brier"]:.6f}, log loss 변화는 {m["log_loss"]-b["log_loss"]:.6f}이다. 두 지표는 작을수록 좋다. ROC-AUC와 average precision은 클수록 좋으며, 상수 예측의 ROC-AUC는 0.5다.', '',
           '## 확률 구간별 점검','','```text',cal.to_string(index=False),'```','',
           '## 구군별 모델 오차','','```text',pd.DataFrame([{'gu':r['gu'],**r['logistic'],'small_n':r['small_n']} for r in regions]).to_string(index=False),'```','',
           '## 해석 제한과 다음 단계','','모델 성능은 현재 스냅샷에 남은 인허가의 과거 기간 검증 결과다. 실제 개업 당시 속성 이력, 원천 누락, 신고 지연은 미검증이다. 인허가 간 동일 건물 의존성도 있어 관측값을 독립 표본으로 가정한 유의성 주장은 하지 않는다.',
           '검증기간은 2020~2021년으로 특수한 시기다. 작은 확률 오차 개선만으로 서비스 채택을 결정하지 않는다. 낮은 예측 확률을 안전한 창업이라는 보증으로 설명하지 않는다.',
           '다음은 검증 결과로 후보 유지/보류 방침을 기록하고 고정된 최종 평가와 새 건물 하위집단 평가를 실행한다. 이번에는 보정 모델 추가·최종 평가·운영 적용을 하지 않았다.', '',
           '재현: Python 3.12 분석 가상환경에서 `python scripts/fit_d03.py`. 패키지 버전과 입력 해시는 validation.json에 기록했다.','']
    (out/'validation.md').write_text('\n'.join(l.rstrip() for l in '\n'.join(lines).splitlines())+'\n',encoding='utf-8')
    print(json.dumps({'scores':scores,'unseen':unknown,'iterations':result['iterations']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
