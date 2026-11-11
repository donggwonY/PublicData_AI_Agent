"""E-03 공실 점수 3단계: 서비스용 재학습 + 현재 공백 후보 조건부 확률·단계 계산.

- 모델 A(평가받은 모델): M3+상가정보, 2016–2021 폐업 학습, 관측 종료 2023-12-31 (E-05 final_test 와 같은 설정)
- 모델 B(서비스용): 같은 설정, 2016–2023 폐업 학습, 관측 종료 = 데이터 기준일(2026-11-06)
- 현재 후보: 앱 find_vacant_units 기본 정의(공백 90~1,095일, 단일 점포 자리)의 마지막 가게 사례
- 조건부 확률(사후 점검 docs/e05/conditional_check.md): a = 공백일 − 90, p(h) = 1 − S(a+h)/S(a)
입력: $E03_OUT/asof_episodes_2026.parquet, sangga_features_2026.parquet(2단계), $E05_REF/models_sangga.json·final_test.json
결과: $E03_OUT/scores/vacancy_scores_<생성일>.parquet, step3_scores.json
"""
import json, os, sys, time, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, 'scripts', 'e05_vacancy'))
import mlib as L  # noqa: E402

OUT = os.environ['E03_OUT']; REF_DIR = os.environ['E05_REF']
V5 = os.environ.get('V5_DIR', os.path.join(REPO, 'service', 'data', 'processed'))
t00 = time.time(); log = lambda *a: print(f'[{time.time()-t00:6.0f}s]', *a, flush=True)
SGC = ['sg_floor_total', 'sg_floor_other', 'sg_bldg_other', 'sg_floor_new_other', 'sg_nb_total', 'sg_nb_other_share',
       'sg_nb_change_1y']
L.LOG |= {'sg_floor_total', 'sg_floor_other', 'sg_bldg_other', 'sg_floor_new_other', 'sg_nb_total'}
NUM = L.numeric_cols('s2') + ['s2_' + c for c in SGC]
P_M3 = json.load(open(os.path.join(REF_DIR, 'models_sangga.json'), encoding='utf-8'))['stage2']['params']['M3_rsf|sangga']
FT = json.load(open(os.path.join(REF_DIR, 'final_test.json'), encoding='utf-8'))
meta = json.load(open(os.path.join(V5, 'meta.json'), encoding='utf-8'))
REF = meta['reference_date']; GEN = time.strftime('%Y-%m-%d')
HZ = {'6m': 182, '1y': 365, '2y': 730}

X = pd.read_parquet(os.path.join(OUT, 'asof_episodes_2026.parquet')).merge(
    pd.read_parquet(os.path.join(OUT, 'sangga_features_2026.parquet')), on='occupant_id', how='left', validate='one_to_one')

# 현재 후보(1단계와 같은 정의)
units = pd.read_parquet(os.path.join(V5, 'units.parquet'))
cand_u = units[units.vacant & units.vacant_days.between(90, 1095) & units.is_single_unit][['uid', 'vacant_days', 'addr', 'gu', 'dong']]
lastocc = X.sort_values(['uid', 'ld', 'occupant_id']).groupby('uid').tail(1)[['uid', 'occupant_id']]
C = cand_u.merge(lastocc, on='uid', how='left').merge(X, on=['occupant_id'], how='left', suffixes=('', '_ep'), validate='one_to_one')
assert C.occupant_id.notna().all() and (~C.event).all() and (C['T'] == C.vacant_days).all(), '후보-사례 연결 불일치'
a = (C.vacant_days - 90).to_numpy(float)


def eval_fns(fns, T):
    """사례별 시점 배열 T[i, :]에서 생존 함수 값. 첫 사건 시점 전은 1, 학습 최대 시간 이후는 마지막 값."""
    out = np.empty(T.shape)
    for i, f in enumerate(fns):
        t = T[i]; v = np.ones_like(t); m = t >= f.x[0]
        v[m] = f(np.minimum(t[m], f.x[-1])); out[i] = v
    return out


def fit(years, end):
    s2 = L.stage2(L.split(X, years, end))
    pr = L.Prep(NUM, False).fit(s2)
    m = L.M3RSF(**P_M3).fit(pr.transform(s2), s2)
    return s2, pr, m


def score(pr, m):
    fns = m.m.predict_survival_function(pr.transform(C).to_numpy(np.float32))
    T = np.column_stack([a] + [a + h for h in HZ.values()])
    S = eval_fns(fns, T)
    base = np.clip(S[:, 0], 1e-9, None)
    return {k: 1 - S[:, j + 1] / base for j, k in enumerate(HZ)}, {'max_train_time': float(fns[0].x[-1])}


res = {'generated': GEN, 'data_reference_date': REF, 'data_built_at': meta.get('built_at'), 'params_M3': P_M3,
       'candidates': len(C)}
# 모델 A(평가받은 모델) + 재현 확인
s2A, prA, mA = fit((2016, 2021), '2023-12-31')
teA = L.stage2(L.split(X, (2022, 2023), REF))
pA_test = 1 - mA.surv(prA.transform(teA))[:, list(L.TIMES).index(365)]
res['model_A'] = {'train': {'n': len(s2A), 'events': int(s2A.ev.sum())},
                  'reproduce_test_p_fill_365_mean': {'now': float(pA_test.mean()), 'final_test': FT['test']['M3']['p_fill_365_mean']}}
PA, infoA = score(prA, mA); res['model_A'].update(infoA)
log('model A', res['model_A'])
# 모델 B(서비스용)
s2B, prB, mB = fit((2016, 2023), REF)
PB, infoB = score(prB, mB)
res['model_B'] = {'train': {'n': len(s2B), 'events': int(s2B.ev.sum())}, **infoB}
log('model B', res['model_B'])

# 점수표
band = pd.cut(C.vacant_days, [89, 180, 365, 730, 1095], labels=['90~180일', '180일~1년', '1~2년', '2~3년'])
S_ = pd.DataFrame({
    'uid': C.uid, 'occupant_id': C.occupant_id, 'addr': C.addr, 'gu': C.gu, 'dong': C.dong, 'prev_group': C.prev_group,
    'vacant_days': C.vacant_days.astype(int), 'vacant_band': band.astype(str),
    'p_fill_6m': PB['6m'], 'p_fill_1y': PB['1y'], 'p_fill_2y': PB['2y'], 'p_fill_1y_modelA': PA['1y'],
    'level_all': pd.qcut(PB['1y'], 5, labels=False).astype(int) + 1,
    'level_in_band': pd.Series(PB['1y']).groupby(band.to_numpy()).transform(lambda s: pd.qcut(s, 5, labels=False) + 1).astype(int),
    'thin_evidence': C.vacant_days > 730,
    'data_reference_date': REF, 'generated': GEN, 'model_version': f'E05-M3sangga-train2016_2023-obs{REF}'})
os.makedirs(os.path.join(OUT, 'scores'), exist_ok=True)
S_.to_parquet(os.path.join(OUT, 'scores', f'vacancy_scores_{GEN}.parquet'), index=False)

# 요약·A/B 비교
q = lambda v: [round(float(x), 4) for x in np.quantile(v, [0.1, 0.5, 0.9])]
res['scores_B'] = {k: {'mean': round(float(v.mean()), 4), 'p10_p50_p90': q(v)} for k, v in PB.items()}
res['by_band'] = {str(b): {'n': len(g), 'p1y_B_mean': round(float(g.p_fill_1y.mean()), 4),
                           'p1y_A_mean': round(float(g.p_fill_1y_modelA.mean()), 4)}
                  for b, g in S_.groupby('vacant_band', sort=False)}
res['level_all_by_band'] = pd.crosstab(S_.vacant_band, S_.level_all).to_dict('index')
res['level_cutpoints_1y'] = [round(float(x), 4) for x in np.quantile(PB['1y'], [0.2, 0.4, 0.6, 0.8])]
lvA = pd.qcut(PA['1y'], 5, labels=False) + 1
res['A_vs_B'] = {'spearman_p1y': round(float(pd.Series(PA['1y']).corr(pd.Series(PB['1y']), method='spearman')), 4),
                 'pearson_p1y': round(float(np.corrcoef(PA['1y'], PB['1y'])[0, 1]), 4),
                 'mean_p1y': {'A': round(float(PA['1y'].mean()), 4), 'B': round(float(PB['1y'].mean()), 4)},
                 'level_same_pct': round(float((lvA == S_.level_all.to_numpy()).mean() * 100), 1),
                 'level_within1_pct': round(float((np.abs(lvA - S_.level_all.to_numpy()) <= 1).mean() * 100), 1)}
res['by_prev_group_top'] = {g: {'n': len(d), 'p1y_B_mean': round(float(d.p_fill_1y.mean()), 4)}
                            for g, d in sorted(S_.groupby('prev_group'), key=lambda x: -len(x[1]))[:8]}
res['seconds'] = round(time.time() - t00)
json.dump(res, open(os.path.join(OUT, 'step3_scores.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=int)
log('done', json.dumps({k: res[k] for k in ('scores_B', 'by_band', 'A_vs_B')}, ensure_ascii=False))
