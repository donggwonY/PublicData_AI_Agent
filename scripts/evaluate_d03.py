"""Final evaluation of frozen D-03 candidate; no tuning or validation refit."""
from fit_d03 import *

def main():
    out=ROOT/'docs/d03'
    v=json.loads((out/'validation.json').read_text(encoding='utf-8'))
    protocol=json.loads((out/'protocol.json').read_text(encoding='utf-8'))
    verify_snapshot_hash(out/'protocol.json',v['hashes']['protocol'])
    verify_snapshot_hash(ROOT/'scripts/fit_d03.py',v['hashes']['script'])
    for name,digest in protocol['hashes'].items():verify_snapshot_hash(ROOT/name,digest)
    st=pd.read_parquet(ROOT/'service/data/processed/stores.parquet')
    st=st[st.service.eq('일반음식점')]
    train=st[st.ld.dt.year.between(2010,2018)].copy()
    val=st[st.ld.dt.year.between(2020,2021)].copy()
    test=st[st.ld.dt.year.between(2023,2024)].copy().reset_index(drop=True)
    assert len(test)==5837 and (test.ld+pd.Timedelta(days=365)).max()<=pd.Timestamp(protocol['reference_date'])
    def x(f):return f.assign(open_month=f.ld.dt.month)[protocol['features']].astype('string').fillna('__MISSING__').astype(str)
    def y(f):return (f.closed & (f.cd-f.ld).dt.days.le(365)).astype(int).to_numpy()
    model=Pipeline([('onehot',OneHotEncoder(handle_unknown='ignore')),('logistic',LogisticRegression(**v['params']))])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always');model.fit(x(train),y(train))
    assert not any(issubclass(w.category,ConvergenceWarning) for w in caught)
    reproduced=metrics(y(val),model.predict_proba(x(val))[:,1])
    for key,value in v['validation']['logistic'].items():
        if value is not None:assert np.isclose(reproduced[key],value,rtol=1e-8,atol=1e-10),key
    p=model.predict_proba(x(test))[:,1];truth=y(test)
    assert np.isfinite(p).all() and ((0<=p)&(p<=1)).all()
    b=np.full(len(test),float(y(train).mean()))
    previous=set(train.building_key.dropna())|set(val.building_key.dropna())
    new=test.building_key.notna() & ~test.building_key.isin(previous)
    assert int(new.sum())==protocol['test_new_building_rows']
    scores={}
    for name,mask in [('all',np.ones(len(test),dtype=bool)),('new_buildings',new.to_numpy())]:
        scores[name]={'constant':metrics(truth[mask],b[mask]),'logistic':metrics(truth[mask],p[mask])}
    subgroups=[]
    for col in ['gu','category']:
        for label,indices in test.groupby(col,dropna=False).groups.items():
            ix=np.asarray(list(indices));subgroups.append({'dimension':col,'group':str(label),'small_n':len(ix)<30,'constant':metrics(truth[ix],b[ix]),'logistic':metrics(truth[ix],p[ix])})
    bins=pd.cut(p,[-0.000001,.05,.10,.15,.20,.30,.50,1.0],include_lowest=True)
    cal=pd.DataFrame({'bin':bins,'pred':p,'actual':truth}).groupby('bin',observed=True).agg(n=('actual','size'),predicted=('pred','mean'),actual=('actual','mean')).reset_index()
    cal['bin']=cal['bin'].astype(str)
    # Aggregate failure examples only, no shop-level risk claims.
    errors={'events_predicted_below_10pct':int(((truth==1)&(p<.1)).sum()),'nonevents_predicted_at_least_20pct':int(((truth==0)&(p>=.2)).sum())}
    result={'scope':'frozen final evaluation; test was not used for fitting/tuning; prior annual summaries were visible','test':scores,'subgroups':subgroups,
            'probability_bins':json.loads(cal.to_json(orient='records')),'failure_examples':errors,'validation_reproduction':'PASS',
            'versions':v['versions'],'hashes':{'script':snapshot_sha256(Path(__file__)),'validation':snapshot_sha256(out/'validation.json'),'protocol':snapshot_sha256(out/'protocol.json')}}
    (out/'final_evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# D-03 고정 후보 최종 평가','','학습·전처리는 2010~2018년만 사용. 2020~2021년 검증 수치 재현 일치. 설정을 변경하거나 검증자료로 재학습하지 않고 2023~2024년을 평가했다. 이전 연도별 결과 요약은 이미 확인한 상태로 완전한 블라인드 시험은 아니다.','','```text',pd.DataFrame([{'subset':k,'model':m,**r} for k,rows in scores.items() for m,r in rows.items()]).to_string(index=False),'```','',
           '## 확률 구간별 실제 사건 비율','','```text',cal.to_string(index=False),'```','',
           '## 구군별 결과','','```text',pd.DataFrame([{'group':r['group'],**r['logistic'],'small_n':r['small_n']} for r in subgroups if r['dimension']=='gu']).to_string(index=False),'```','',
           '업태별 결과는 final_evaluation.json의 subgroups에 저장했다. 작은 집단 및 사건 한 종류뿐인 집단은 순위 지표를 해석하지 않는다.','','## 실패 사례 집계','','```text',json.dumps(errors,ensure_ascii=False,indent=2),'```','',
           '10%·20% 기준은 오류를 설명하기 위한 집계 구간이며 서비스 분류 임계값으로 최적화한 것이 아니다. 새 건물 집단은 학습·검증에 없던 건물의 인허가이며 고유 건물 수가 아니다. 전체와 구성 자체가 다르므로 성능 차이를 주소 누출 효과로 단정하지 않는다.','','## 해석 제한','','실제 사건 비율과 평균 예측 확률 차이는 기간 이동에서의 확률 오차를 보여준다. 업태 구성·신고 지연·최신 스냅샷 선택·사회환경 변화 중 어느 원인이 얼마나 기여했는지는 이 실험만으로 분리할 수 없다. 인과적 설명 또는 실제 영업 실패 확률로 사용하지 않는다. 동일 건물 반복 관측을 독립 표본으로 간주한 유의성 주장을 하지 않았다.', '',
           '최종 평가 점수로 이 후보를 다시 튜닝하지 않는다. 추가 변수·최근 학습 기간 등의 개선 실험은 별도 프로토콜과 새 평가 설계를 요구한다. 운영 DB·앱에는 적용하지 않았다.','','재현: `python scripts/evaluate_d03.py`. 검증 결과·입력 해시 불일치 시 중단한다.','']
    (out/'final_evaluation.md').write_text('\n'.join(l.rstrip() for l in '\n'.join(lines).splitlines())+'\n',encoding='utf-8')
    print(json.dumps({'test':scores,'failure_examples':errors},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
