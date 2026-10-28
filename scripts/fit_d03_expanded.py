"""Predeclared 14-candidate temporal comparison, without reusing final test."""
import json, warnings, platform
from pathlib import Path
import numpy as np
import pandas as pd
import sklearn, scipy
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.neighbors import BallTree
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler
from fit_d03 import ROOT, metrics, OneHotEncoder, LogisticRegression, Pipeline, ConvergenceWarning, snapshot_sha256, verify_snapshot_hash
from fit_d03_historical_context import counts, check_boundaries, RADIUS, NUMS

CATS = ['category','gu','open_month']
LABELS = {'constant':'전체 학습 평균','recent_constant':'최근3년 평균','category_mean':'업태별 수축 평균',
'base':'기존 회귀','recent_base':'최근3년 회귀','context':'주변 맥락 회귀','recent_context':'최근3년 주변 회귀',
'interaction':'업태×구군 회귀','forest_base':'기존 입력 랜덤포레스트','forest_context':'주변 입력 랜덤포레스트',
'boost_context':'주변 입력 부스팅','calibration_base':'보정 비교용 과거 회귀','sigmoid':'시간 분리 sigmoid 보정','isotonic':'시간 분리 isotonic 보정'}


def target(frame):
    return (frame.closed & (frame.cd-frame.ld).dt.days.between(0,365)).astype(int).to_numpy()


def pipeline(kind='logistic', extra=False, interaction=False):
    cats = CATS + (['category_gu'] if interaction else [])
    tf = [('cats',OneHotEncoder(handle_unknown='ignore',sparse_output=False),cats)]
    if extra: tf.append(('nums',StandardScaler(),NUMS))
    if kind=='forest':
        model=RandomForestClassifier(n_estimators=150,max_depth=8,min_samples_leaf=30,max_features='sqrt',random_state=0,n_jobs=2)
    elif kind=='boost':
        model=HistGradientBoostingClassifier(max_iter=150,learning_rate=.05,max_leaf_nodes=15,min_samples_leaf=30,l2_regularization=1,early_stopping=False,random_state=0)
    else: model=LogisticRegression(C=1,max_iter=2000,random_state=0)
    return Pipeline([('features',ColumnTransformer(tf)),('model',model)])


def fit(model, x, y):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always');model.fit(x,y)
    assert not any(issubclass(w.category,ConvergenceWarning) for w in caught)
    return model


def logit(p):
    p=np.clip(p,1e-6,1-1e-6)
    return np.log(p/(1-p)).reshape(-1,1)


def make_features(stores):
    s=stores[stores.service.eq('일반음식점') & stores.ld.lt('2022-01-01')].copy()
    s=s[s.lat.between(-90,90)&s.lon.between(-180,180)].reset_index(drop=True)
    assert not (s.cd.notna()&s.cd.lt(s.ld)).any()
    coords=np.radians(s[['lat','lon']].to_numpy());tree=BallTree(coords,metric='haversine')
    opened=s.ld.to_numpy(dtype='datetime64[D]');closed=s.cd.to_numpy(dtype='datetime64[D]')
    ids=np.flatnonzero(s.ld.dt.year.between(2010,2021).to_numpy());f=s.iloc[ids].copy()
    values=[]
    for idx in ids:
        cutoff=opened[idx]-np.timedelta64(60,'D');near=tree.query_radius(coords[idx:idx+1],r=RADIUS)[0]
        assert not np.any(near[opened[near]<cutoff]==idx)
        values.append(counts(opened[near],closed[near],cutoff))
    f[NUMS]=np.log1p(np.array(values))
    f['open_month']=f.ld.dt.month.astype(str)
    for c in CATS:f[c]=f[c].astype('string').fillna('__MISSING__').astype(str)
    f['category_gu']=f.category+' | '+f.gu
    return f


def main():
    check_boundaries();out=ROOT/'docs/d03'
    old=json.loads((out/'historical_context.json').read_text(encoding='utf-8'))
    verify_snapshot_hash(ROOT/'service/data/processed/stores.parquet',old['hashes']['stores'])
    f=make_features(pd.read_parquet(ROOT/'service/data/processed/stores.parquet'))
    print('Features ready:',len(f),flush=True)
    windows=[];subgroups=[]
    for end,start,stop in [(2013,2015,2016),(2015,2017,2018),(2018,2020,2021)]:
        tr=f[f.ld.dt.year.between(2010,end)].copy();recent=tr[tr.ld.dt.year.ge(end-2)].copy()
        va=f[f.ld.dt.year.between(start,stop)].copy();y=target(tr);yv=target(va)
        assert not set(tr.index)&set(va.index)
        assert (tr.ld+pd.Timedelta(days=365)).max()<va.ld.min()
        p={'constant':np.full(len(va),y.mean()),'recent_constant':np.full(len(va),target(recent).mean())}
        sums=pd.DataFrame({'cat':tr.category.to_numpy(),'y':y}).groupby('cat').y.agg(['sum','count'])
        shrink=(sums['sum']+50*y.mean())/(sums['count']+50)
        p['category_mean']=va.category.map(shrink).fillna(y.mean()).to_numpy()
        specs=[('base','logistic',False,False,tr),('recent_base','logistic',False,False,recent),
            ('context','logistic',True,False,tr),('recent_context','logistic',True,False,recent),
            ('interaction','logistic',True,True,tr),('forest_base','forest',False,False,tr),
            ('forest_context','forest',True,False,tr),('boost_context','boost',True,False,tr)]
        for name,kind,extra,interaction,train in specs:
            model=fit(pipeline(kind,extra,interaction),train,target(train))
            p[name]=model.predict_proba(va)[:,1]
            print(f'{start}-{stop}: {name} done',flush=True)
        earlier=tr[tr.ld.dt.year.le(end-2)].copy();cal=tr[tr.ld.dt.year.eq(end)].copy()
        assert len(earlier)>0 and len(cal)>0
        assert (earlier.ld+pd.Timedelta(days=365)).max()<cal.ld.min()
        assert (cal.ld+pd.Timedelta(days=365)).max()<va.ld.min()
        assert not set(earlier.index)&set(cal.index) and not set(cal.index)&set(va.index)
        base=fit(pipeline(extra=True),earlier,target(earlier))
        pc=base.predict_proba(cal)[:,1];pv=base.predict_proba(va)[:,1];yc=target(cal)
        p['calibration_base']=pv
        sig=fit(LogisticRegression(C=1000000,max_iter=2000,random_state=0),logit(pc),yc)
        p['sigmoid']=sig.predict_proba(logit(pv))[:,1]
        iso=IsotonicRegression(out_of_bounds='clip').fit(pc,yc);p['isotonic']=iso.predict(pv)
        assert set(p)==set(LABELS)
        scores={}
        for name,prob in p.items():
            assert np.isfinite(prob).all() and ((prob>=0)&(prob<=1)).all()
            scores[name]=metrics(yv,prob)
            for gu in sorted(va.gu.unique()):
                mask=va.gu.eq(gu).to_numpy();subgroups.append({'window':f'{start}-{stop}','model':name,'group':gu,**metrics(yv[mask],prob[mask])})
            mask=(va.building_key.notna()&~va.building_key.isin(tr.building_key.dropna())).to_numpy()
            if mask.any():subgroups.append({'window':f'{start}-{stop}','model':name,'group':'new_building',**metrics(yv[mask],prob[mask])})
        previous=next(r for r in old['results'] if r['window']==f'{start}-{stop}')
        for name in ['constant','base','context']:
            for key in ['n','events','brier','log_loss','predicted_pct','roc_auc']:
                assert np.isclose(scores[name][key],previous['scores'][name][key],atol=1e-5,rtol=1e-4),(name,key)
        windows.append({'window':f'{start}-{stop}','train_n':len(tr),'recent_n':len(recent),'calibration_train_n':len(earlier),'calibration_n':len(cal),'calibration_year':end,'scores':scores})
        print('Window complete',start,flush=True)
    ranking=[]
    for name in LABELS:
        beats=sum(all(w['scores'][name][k]<w['scores']['constant'][k] for k in ['brier','log_loss']) for w in windows)
        ranking.append({'model':name,'label':LABELS[name],'windows_better_than_constant_both_errors':beats,
            'mean_brier':float(np.mean([w['scores'][name]['brier'] for w in windows])),
            'mean_log_loss':float(np.mean([w['scores'][name]['log_loss'] for w in windows]))})
    ranking.sort(key=lambda x:x['mean_brier'])
    result={'scope':'14 predeclared candidates; exploratory temporal validation only; final 2023-2024 untouched',
        'windows':windows,'ranking':ranking,'subgroups':subgroups,
        'candidates_for_independent_evaluation':[r['model'] for r in ranking if r['windows_better_than_constant_both_errors']==3],
        'versions':{'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,'sklearn':sklearn.__version__,'scipy':scipy.__version__},
        'hashes':{'script':snapshot_sha256(Path(__file__)),'plan':snapshot_sha256(out/'expanded_experiments_plan.md'),
            'historical_helper':snapshot_sha256(ROOT/'scripts/fit_d03_historical_context.py'),'metrics_helper':snapshot_sha256(ROOT/'scripts/fit_d03.py'),'stores':old['hashes']['stores']}}
    (out/'expanded_experiments.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# D-03 14候補 후속 비교'.replace('候補','개 후보'),'','2026-10-28. 기존 자료 기반 탐색이며 새 최종 성능 입증이 아니다. 개별 후보 설정은 [사전 계획](expanded_experiments_plan.md)을 참조한다.','','## 기간별 확률 오차','',
        '| 모델 | 2015~2016 Brier | 2017~2018 Brier | 2020~2021 Brier | 상수보다 두 오차 개선한 기간 |','| --- | ---: | ---: | ---: | ---: |']
    for r in ranking:
        name=r['model'];v=[w['scores'][name]['brier'] for w in windows]
        lines.append(f"| {r['label']} | {v[0]:.6f} | {v[1]:.6f} | {v[2]:.6f} | {r['windows_better_than_constant_both_errors']}/3 |")
    lines+=['','평균 Brier 순으로 나열했으나 기간별 안정성을 우선한다. Brier·log loss는 작을수록 좋다. 아래 상세표와 JSON에 다른 지표를 함께 보존한다.','','## 기간별 상세']
    for w in windows:
        lines+=['',f"### {w['window']} (학습 {w['train_n']:,}건, 최근3년 {w['recent_n']:,}건)",'',
            '| 모델 | 평균 예측% | 실제% | log loss | AUC |','| --- | ---: | ---: | ---: | ---: |']
        for name in LABELS:
            m=w['scores'][name];lines.append(f"| {LABELS[name]} | {m['predicted_pct']:.2f} | {m['actual_pct']:.2f} | {m['log_loss']:.6f} | {m['roc_auc']:.4f} |")
        lines+=['',f"보정 기초 학습 {w['calibration_train_n']:,}건, 별도 {w['calibration_year']}년 보정 {w['calibration_n']:,}건. 기초 학습·보정·검증 사이365일 관측 간격 확인."]
    names=result['candidates_for_independent_evaluation']
    lines+=['','## 판단','',('세 기간 모두 두 확률 오차가 상수보다 작은 후보: '+', '.join(LABELS[n] for n in names)+'. 다음 독립 평가 후보이지 서비스 채택 완료가 아니다.') if names else '세 기간 모두 두 확률 오차가 상수 기준선보다 작은 후보는 없었다. 공개 개인별 확률 안내를 보류한다. 내부 실험 비교 화면은 결과 설명용으로 사용할 수 있다.',
        '', '## 검증·한계', '', '기존 상수·기본 회귀·주변 회귀의 각 기간 지표를 재현 대조했다(범주 행렬 저장 방식 차이를 고려한 허용오차). 경계값 예제·자기제외·시간 간격·보정 기간 분리·표본 비중복·수렴·확률 범위 검사를 통과했다. 구군 및 새 건물 결과는 JSON에 보존했다.',
        '기존 검증 결과를 본 뒤 정한14후보의 탐색이다. 이미 본 기간에서 선택했으므로 작은 차이는 독립적 입증이나 통계적 유의성을 의미하지 않는다. 현재 주소·신고 지연·최신 스냅샷 누락·좌표 제외와 같은 한계는 모델 변경으로 해결되지 않는다. 새 외부 과거 데이터는 추가하지 않았다.',
        'isotonic은 끝값0/1을 출력할 수 있고 그 경우 log loss가 커질 수 있다. 지표 계산의 표준 수치 클리핑 외 별도 검증 기반 조정은 하지 않는다. 보정 자체 효과는 보정 비교용 과거 회귀와 비교해야 하며, 전체기간 후보와 학습량이 다르다.',
        '평가 결과를 보고 추가 파라미터 탐색이나 기존2023~2024 시험 재평가는 하지 않았다. DB 적재·운영 배포는 미수행. 실행: 분석 환경에서 python scripts/fit_d03_expanded.py.']
    (out/'expanded_experiments.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'ranking':ranking,'next_candidates':names},ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__': main()
