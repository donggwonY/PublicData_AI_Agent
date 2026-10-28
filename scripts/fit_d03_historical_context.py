"""Fixed, retrospective spatial context comparison; no final test evaluation."""
import json, warnings, platform, os
from pathlib import Path
import numpy as np
import pandas as pd
import sklearn
from sklearn.neighbors import BallTree
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler
from fit_d03 import (ROOT, metrics, OneHotEncoder, LogisticRegression, Pipeline,
                     ConvergenceWarning, snapshot_sha256, verify_snapshot_hash)

RADIUS = 500 / 6371000
NUMS = ['active', 'openings', 'closures']

def counts(opened, closed, cutoff):
    past = opened < cutoff
    observed_closed = ~np.isnat(closed) & (closed < cutoff)
    lower = cutoff - np.timedelta64(365, 'D')
    return [int(np.sum(past & ~observed_closed)),
            int(np.sum(past & (opened >= lower))),
            int(np.sum(past & observed_closed & (closed >= lower)))]

def check_boundaries():
    c = np.datetime64('2020-01-01', 'D')
    opened = c + np.array([-500, -365, -1, 0, 1]).astype('timedelta64[D]')
    closed = np.array(['NaT', '2019-12-31', '2020-01-01', 'NaT', 'NaT'], dtype='datetime64[D]')
    assert counts(opened, closed, c) == [2, 2, 1]
    changed = closed.copy(); changed[2] = np.datetime64('2030-01-01')
    assert counts(opened, changed, c) == counts(opened, closed, c)
    assert counts(opened[:3], closed[:3], c) == counts(opened, closed, c)

def main():
    check_boundaries()
    out = ROOT/'docs/d03'
    protocol = json.loads((out/'protocol.json').read_text(encoding='utf-8'))
    for name, digest in protocol['hashes'].items(): verify_snapshot_hash(ROOT/name, digest)
    stores = pd.read_parquet(ROOT/'service/data/processed/stores.parquet')
    source = stores[stores.service.eq('일반음식점') & stores.ld.lt('2022-01-01')].copy()
    valid = source.lat.between(-90, 90) & source.lon.between(-180, 180)
    missing = int((~valid).sum())
    source = source[valid].reset_index(drop=True)
    assert not (source.cd.notna() & source.cd.lt(source.ld)).any()
    coords = np.radians(source[['lat', 'lon']].to_numpy())
    tree = BallTree(coords, metric='haversine')
    opened = source.ld.to_numpy(dtype='datetime64[D]')
    closed = source.cd.to_numpy(dtype='datetime64[D]')
    target_ids = np.flatnonzero(source.ld.dt.year.between(2010, 2021).to_numpy())
    f = source.iloc[target_ids].copy().reset_index(drop=True)
    values = []
    for n, idx in enumerate(target_ids):
        cutoff = opened[idx] - np.timedelta64(60, 'D')
        neighbors = tree.query_radius(coords[idx:idx+1], r=RADIUS)[0]
        assert not np.any(neighbors[opened[neighbors] < cutoff] == idx)
        values.append(counts(opened[neighbors], closed[neighbors], cutoff))
        if n in {0, len(target_ids)//2, len(target_ids)-1}:
            delta = coords - coords[idx]
            a = np.sin(delta[:, 0]/2)**2 + np.cos(coords[:, 0])*np.cos(coords[idx, 0])*np.sin(delta[:, 1]/2)**2
            distance = 2*np.arcsin(np.sqrt(np.clip(a, 0, 1)))
            direct = distance <= RADIUS
            assert values[-1] == counts(opened[direct], closed[direct], cutoff)
        if n % 10000 == 0: print('Historical feature rows:', n, flush=True)
    f[NUMS] = np.array(values)
    f['open_month'] = f.ld.dt.month.astype(str)
    cats = ['category', 'gu', 'open_month']
    for c in cats: f[c] = f[c].astype('string').fillna('__MISSING__').astype(str)
    feature_summary = f[NUMS].describe().to_dict()
    for c in NUMS: f[c] = np.log1p(f[c])
    results = []; subgroup = []
    for end, start, stop in [(2013,2015,2016), (2015,2017,2018), (2018,2020,2021)]:
        tr = f[f.ld.dt.year.between(2010,end)].copy()
        va = f[f.ld.dt.year.between(start,stop)].copy().reset_index(drop=True)
        assert (tr.ld + pd.Timedelta(days=365)).max() < va.ld.min()
        assert not set(tr.index) & set(f[f.ld.dt.year.between(start,stop)].index)
        target = lambda a: (a.closed & (a.cd-a.ld).dt.days.between(0,365)).astype(int).to_numpy()
        y, yv = target(tr), target(va)
        predictions = {'constant': np.full(len(va),y.mean())}
        for name, extra in [('base',False), ('context',True)]:
            transformers = [('category', OneHotEncoder(handle_unknown='ignore'), cats)]
            if extra: transformers.append(('numeric',StandardScaler(),NUMS))
            model = Pipeline([('features',ColumnTransformer(transformers)), ('model',LogisticRegression(C=1,solver='lbfgs',max_iter=2000,random_state=0))])
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always'); model.fit(tr[cats+NUMS],y)
            assert not any(issubclass(w.category,ConvergenceWarning) for w in caught)
            predictions[name] = model.predict_proba(va[cats+NUMS])[:,1]
        scores = {}
        for name, p in predictions.items():
            assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all()
            scores[name] = metrics(yv,p)
            for gu, ix in va.groupby('gu').groups.items():
                ix = np.asarray(list(ix)); subgroup.append({'window':f'{start}-{stop}', 'model':name,'group':gu,**metrics(yv[ix],p[ix])})
            unseen = va.building_key.notna() & ~va.building_key.isin(tr.building_key.dropna())
            if unseen.any(): subgroup.append({'window':f'{start}-{stop}','model':name,'group':'new_building',**metrics(yv[unseen],p[unseen])})
        original = stores[stores.service.eq('일반음식점') & stores.ld.dt.year.between(start,stop)]
        results.append({'window':f'{start}-{stop}','train_n':len(tr),'validation_without_coordinates':len(original)-len(va),'scores':scores})
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    improves = all(r['scores']['context'][m] < r['scores'][b][m] for r in results for m in ['brier','log_loss'] for b in ['constant','base'])
    result = {'scope':'retrospective follow-up exploration; final 2023-2024 test untouched',
        'source_n':len(source),'source_excluded_coordinates':missing,
        'source_closed_missing_date':int((source.closed & source.cd.isna()).sum()),
        'features':feature_summary,'results':results,'subgroups':subgroup,
        'all_windows_probability_improvement':improves,
        'hashes':{'script':snapshot_sha256(Path(__file__)), 'plan':snapshot_sha256(out/'historical_context_plan.md'), 'stores':protocol['hashes']['service/data/processed/stores.parquet']},
        'versions':{'python':platform.python_version(),'pandas':pd.__version__,'numpy':np.__version__,'sklearn':sklearn.__version__}}
    (out/'historical_context.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines = ['# D-03 과거 주변 상권 추가 실험', '', '2026-10-28. 일반음식점 개업 60일 전 기준 주변 500m 관측 영업·최근365일 개업·폐업일 기록 건수를 추가했다. 현재 스냅샷에서 복원한 후속 탐색이다. 최종 시험2023~2024는 재평가하지 않았다.', '',
        '| 검증 기간 | 모델 | n | 실제% | 평균 예측% | Brier | log loss | AUC |','| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for r in results:
        for name,m in r['scores'].items(): lines.append(f"| {r['window']} | {name} | {m['n']} | {m['actual_pct']:.2f} | {m['predicted_pct']:.2f} | {m['brier']:.6f} | {m['log_loss']:.6f} | {m['roc_auc']:.4f} |")
    lines += ['', 'constant=학습 사건 비율, base=업태·구군·개업 월, context=base+과거 주변 맥락. Brier와 log loss는 작을수록 좋다.', '', '## 판단', '',
        '모든 검증 창에서 두 기준선 대비 확률 오차가 개선돼 다음 독립 평가 후보로 추천한다. 아직 공개 서비스 성능 입증은 아니다.' if improves else '모든 검증 창에서 두 기준선 대비 확률 오차를 줄인다는 사전 기준을 통과하지 못했다. 공개 서비스에서 개인별 위험 확률로 안내하는 것은 보류한다. 내부 실험용 비교 화면의 학습 가치는 별도로 검토할 수 있다.', '',
        '## 표본과 검사', '',f'이웃 원천 {len(source):,}건, 좌표 누락/범위 오류 제외 {missing:,}건. 폐업 상태지만 폐업일 없는 원천 {result["source_closed_missing_date"]:,}건은 폐업 시점을 알 수 없는 한계가 있다.',
        '동일 표본 후보 비교, 날짜 경계·자기제외·미래 기록 불변성 예제, 실제3건 전체 거리 직접계산 대조, 학습365일 관측 간격·수렴·확률 범위 검사 통과. 구군·새 건물 결과와 제외 표본 수는 JSON에 보존했다.', '',
        '## 한계와 다음 행동', '', '현재 좌표의 과거 일치·신고 지연·수정 이력은 미검증이다. 60일 시차로 당시 공개를 보증하지 않는다. 좌표 없는 이웃도 빠져 실제 경쟁을 과소집계할 수 있다. 현재 남아 있는 인허가로 복원했으며 원천 누락을 복구한 자료가 아니다. 기간별 오차 원인을 입증하거나 작은 차이의 유의성을 주장하지 않는다.',
        '다음은 결과를 팀과 검토하고 실험용 비교 화면의 범위를 결정하는 것이다. 운영 앱·공유 DB에는 반영하지 않았다. 새로운 과거 자료 확보는 이 실험에서 성능 개선을 보장하지 않는다.', '',
        '재현: 분석 환경에서 `python scripts/fit_d03_historical_context.py`. [사전 계획](historical_context_plan.md), [전체 결과](historical_context.json).']
    (out/'historical_context.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

if __name__ == '__main__': main()
