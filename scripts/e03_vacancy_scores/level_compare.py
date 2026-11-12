"""E-03 화면 수준(1~5) 기준 비교 백테스트. 모델·점수 변경 없음(화면 설계용 진단).

과거 기준일 D마다: D까지의 자료로만 M3+상가정보(같은 설정) 학습 → D 시점 공백 후보(폐업 후 90~1,095일, 아직 미채움)에
조건부 1년 확률 → 세 가지 수준 기준을 매기고 D 이후 1년 실제 재입점과 비교.
  가 all  : D 시점 전체 후보 중 5등분
  나 band : 같은 공백 기간대(90~180일, 180일~1년, 1~2년, 2~3년) 안 5등분
  다 fixed: 고정 확률 구간(2·4·6·8%)
후보 정의(근사): 폐업 시점 기준 단독 자리 사례 중 D에 공백 90~1,095일이고 D까지 다음 가게가 없는 사례(앱의 최종 기록 기준 단일 점포 판정과 약간 다름).
입력: $E03_OUT/asof_episodes_2026.parquet, sangga_features_2026.parquet, $E05_REF/models_sangga.json. 결과: $E03_OUT/level_compare.json
"""
import json, os, sys, time, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, 'scripts', 'e05_vacancy'))
import mlib as L  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

OUT = os.environ['E03_OUT']; REF_DIR = os.environ['E05_REF']
t00 = time.time(); log = lambda *a: print(f'[{time.time()-t00:6.0f}s]', *a, flush=True)
SGC = ['sg_floor_total', 'sg_floor_other', 'sg_bldg_other', 'sg_floor_new_other', 'sg_nb_total', 'sg_nb_other_share', 'sg_nb_change_1y']
L.LOG |= {'sg_floor_total', 'sg_floor_other', 'sg_bldg_other', 'sg_floor_new_other', 'sg_nb_total'}
NUM = L.numeric_cols('s2') + ['s2_' + c for c in SGC]
P_M3 = json.load(open(os.path.join(REF_DIR, 'models_sangga.json'), encoding='utf-8'))['stage2']['params']['M3_rsf|sangga']
X = pd.read_parquet(os.path.join(OUT, 'asof_episodes_2026.parquet')).merge(
    pd.read_parquet(os.path.join(OUT, 'sangga_features_2026.parquet')), on='occupant_id', how='left', validate='one_to_one')
DATES = ['2023-07-01', '2024-01-01', '2024-07-01', '2025-01-01', '2025-07-01']
BANDS = [89, 180, 365, 730, 1095]; BL = ['90~180일', '180일~1년', '1~2년', '2~3년']
FIXED = [0.02, 0.04, 0.06, 0.08]


def eval_fns(fns, T):
    out = np.empty(T.shape)
    for i, f in enumerate(fns):
        t = T[i]; v = np.ones_like(t); m = t >= f.x[0]
        v[m] = f(np.minimum(t[m], f.x[-1])); out[i] = v
    return out


rows = []
for ds in DATES:
    D = pd.Timestamp(ds)
    # 학습: D 이전 폐업(2016~), 관측 종료 D
    tr = L.censor(X[(X.close_year >= 2016) & (X.t0 < D - pd.Timedelta(days=90))], D)
    s2 = L.stage2(tr)
    pr = L.Prep(NUM, False).fit(s2); m = L.M3RSF(**P_M3).fit(pr.transform(s2), s2)
    # D 시점 후보
    el = (D - X.t0).dt.days
    c = X[(el >= 90) & (el <= 1095) & (X['T'] > el)].copy()
    c['elapsed'] = el[c.index]
    a = (c.elapsed - 90).to_numpy(float)
    S = eval_fns(m.m.predict_survival_function(pr.transform(c).to_numpy(np.float32)), np.column_stack([a, a + 365]))
    c['p'] = 1 - S[:, 1] / np.clip(S[:, 0], 1e-9, None)
    c['y'] = (c.event & (c['T'] <= c.elapsed + 365)).astype(int)
    c['band'] = pd.cut(c.elapsed, BANDS, labels=BL).astype(str)
    c['lv_all'] = pd.qcut(c.p, 5, labels=False) + 1
    c['lv_band'] = c.groupby('band').p.transform(lambda s: pd.qcut(s, 5, labels=False) + 1)
    c['lv_fixed'] = np.digitize(c.p, FIXED) + 1
    c['D'] = ds
    rows.append(c[['occupant_id', 'uid', 'D', 'elapsed', 'band', 'p', 'y', 'lv_all', 'lv_band', 'lv_fixed']])
    log(ds, 'train', len(s2), 'cand', len(c), 'fill1y', round(c.y.mean(), 4), 'pred', round(c.p.mean(), 4))
B = pd.concat(rows, ignore_index=True)
B.to_parquet(os.path.join(OUT, 'level_compare_backtest.parquet'), index=False)
SCH = {'all': 'lv_all', 'band': 'lv_band', 'fixed': 'lv_fixed'}
res = {'dates': DATES, 'fixed_cutpoints': FIXED, 'n_by_date': B.groupby('D').size().to_dict(),
       'obs_fill1y_by_date': B.groupby('D').y.mean().round(4).to_dict(), 'pred_by_date': B.groupby('D').p.mean().round(4).to_dict()}

# 1. 실제 재입점률: 수준별, 수준×기간대별(전 기준일 합산)
res['obs_by_level'] = {k: B.groupby(v).y.agg(['mean', 'size']).round(4).to_dict('index') for k, v in SCH.items()}
res['obs_by_band_level'] = {k: {b: g.groupby(v).y.agg(['mean', 'size']).round(4).to_dict('index') for b, g in B.groupby('band')}
                            for k, v in SCH.items()}
res['pred_by_band_level'] = {k: {b: g.groupby(v).p.mean().round(4).to_dict() for b, g in B.groupby('band')} for k, v in SCH.items()}
# 같은 수준의 의미가 기간대마다 얼마나 다른가: 수준별 기간대 간 실제 비율 범위(표본 50 이상 칸)
spread = {}
for k, v in SCH.items():
    t = B.groupby([v, 'band']).y.agg(['mean', 'size']); t = t[t['size'] >= 50]
    spread[k] = {int(lv): round(float(g['mean'].max() - g['mean'].min()), 4) for lv, g in t.groupby(level=0)}
res['same_level_obs_range_across_bands'] = spread

# 2. 구분력: 전체 후보 AUC, 기간대 안 AUC(기간대별 평균)
def auc(y, s):
    return float(roc_auc_score(y, s)) if y.nunique() == 2 else np.nan
band_code = B.band.map({b: i for i, b in enumerate(BL)})
res['auc_all_candidates'] = {'p': auc(B.y, B.p), 'band_only': auc(B.y, -band_code),
                             **{k: auc(B.y, B[v]) for k, v in SCH.items()},
                             'band_plus_lv_band': auc(B.y, -band_code * 10 + B.lv_band)}
res['auc_within_band'] = {k: {b: round(auc(g.y, g[v]), 4) for b, g in B.groupby('band')} for k, v in {'p': 'p', **SCH}.items()}
# 기간대 안에서 실제로 쓰이는 수준 수·가장 많은 수준 비율(해상도)
res['level_share_within_band'] = {k: {b: (g[v].value_counts(normalize=True).sort_index().round(3)).to_dict() for b, g in B.groupby('band')}
                                  for k, v in SCH.items()}

# 3. 배치 안정성: 기준일별 경계
res['cutpoints_all'] = {d: [round(float(x), 4) for x in np.quantile(g.p, [.2, .4, .6, .8])] for d, g in B.groupby('D')}
res['cutpoints_band'] = {d: {b: [round(float(x), 4) for x in np.quantile(h.p, [.2, .4, .6, .8])] for b, h in g.groupby('band')}
                         for d, g in B.groupby('D')}

# 4. 같은 자리가 6개월 뒤 다음 기준일에도 후보일 때 수준 변화
chg = {}
for d1, d2 in zip(DATES[:-1], DATES[1:]):
    j = B[B.D == d1].merge(B[B.D == d2], on='occupant_id', suffixes=('1', '2'))
    chg[f'{d1}->{d2}'] = {'n': len(j), 'band_changed_pct': round(float((j.band1 != j.band2).mean() * 100), 1),
                          **{k: {'same_pct': round(float((j[v + '1'] == j[v + '2']).mean() * 100), 1),
                                 'down_pct': round(float((j[v + '2'] < j[v + '1']).mean() * 100), 1),
                                 'up_pct': round(float((j[v + '2'] > j[v + '1']).mean() * 100), 1),
                                 'jump2plus_pct': round(float(((j[v + '2'] - j[v + '1']).abs() >= 2).mean() * 100), 1)}
                             for k, v in SCH.items()}}
res['level_change_6m_same_unit'] = chg
res['seconds'] = round(time.time() - t00)
json.dump(res, open(os.path.join(OUT, 'level_compare.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
log('done')
