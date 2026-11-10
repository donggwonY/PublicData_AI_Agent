"""1단계 누수 테스트: 예측 시점 이후 기록을 지운 데이터로 다시 계산해도 변수 값이 같아야 한다.

T1 단독 여부·자리 이력: 사례 400건 표본, 사례별로 '폐업일 t0 시점에서 잘라낸' 가게 표로 재계산.
T2 주변·동 변수: 기준 달 3개(2015-06, 2019-03, 2022-09). 예측 시점이 기준 달 다음 달에 있는 사례를 고르고,
   기준 달 말일에서 잘라낸 데이터로 격자 패널을 새로 만들어 재계산.
"""
import json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as E5P
import asof as A
import ext as E

VF, IN = E5P.VF, E5P.IN
REF = pd.Timestamp(json.load(open(os.path.join(IN, 'meta.json'), encoding='utf-8'))['reference_date'])
stores = pd.read_parquet(os.path.join(IN, 'stores.parquet'))
units = pd.read_parquet(os.path.join(IN, 'units.parquet'), columns=['uid', 'lat', 'lon'])
occ = A.load_occupants(stores, units)
X = pd.read_parquet(os.path.join(VF, 'asof_episodes.parquet'))
AUX = E5P.AUX
SUB = E.load_subway(os.path.join(AUX, 'subway', 'subway_monthly.csv'), os.path.join(AUX, 'station', 'daegu_station_location.xlsx'))
POP = E.load_population(os.path.join(AUX, 'population'))
LMAP = pd.read_parquet(E5P.LMAP)


def cut(o: pd.DataFrame, c: pd.Timestamp) -> pd.DataFrame:
    o = o[o.ld <= c].copy()
    fut = o.closed & (o.cd > c)
    o.loc[fut, 'closed'] = False
    o.loc[fut, 'cd'] = pd.NaT
    return o


def eq(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return np.allclose(np.nan_to_num(a, nan=-999), np.nan_to_num(b, nan=-999))


res = {}
# T1
rng = np.random.default_rng(0)
smp = X.iloc[rng.choice(len(X), 400, replace=False)]
bad = 0
hcols = ['h_n_occ', 'h_n_closed', 'h_n_turnover', 'h_mean_gap_days', 'h_years_since_first', 'h_n_groups']
for _, r in smp.iterrows():
    o = cut(occ[occ.uid == r.uid], r.t0)
    g = o.sort_values('ld')
    mc = A._max_conc_asof(g.ld.to_numpy('datetime64[ns]'), g.cd.to_numpy('datetime64[ns]'), g.closed.to_numpy(),
                          np.datetime64(r.t0))
    ep1 = pd.DataFrame([r])
    h = A.history_features(ep1, o)
    if mc != r.max_conc_t0 or not eq(h.iloc[0][hcols].values, r[hcols].values):
        bad += 1
res['T1_history_single'] = {'n': len(smp), 'mismatch': bad}

# T2
ncols = [c for c in X.columns if c.startswith('s2_')]
t2 = {}
for month in ['2015-06', '2019-03', '2022-09']:
    c = pd.Period(month).end_time.normalize()
    nxt = pd.Period(month) + 1
    at = X.t0 + pd.Timedelta(days=90)
    sel = X[(at.dt.to_period('M') == nxt)]
    o = cut(occ, c)
    P = A.Panels(o, REF)
    nb = A.neighbor_features(sel, P, sel.t0 + pd.Timedelta(days=90), 's2_')
    dg = A.dong_features(sel, P, o, sel.t0 + pd.Timedelta(days=90), 's2_')
    mc = A.month_idx(c)
    sub_c = dict(SUB); sub_c['board'] = SUB['board'].copy(); sub_c['board'][:, mc + 1:] = 0
    sub_c['opened'] = np.cumsum(sub_c['board'] > 0, axis=1) > 0
    pop_c = POP[POP.m <= mc]
    at2 = sel.t0 + pd.Timedelta(days=90)
    sb = E.subway_features(sel, sub_c, at2, 's2_'); pp = E.population_features(sel, pop_c, LMAP, at2, 's2_')
    got = pd.concat([nb, dg, sb, pp], axis=1)[ncols]
    mism = int((~np.isclose(np.nan_to_num(got.values.astype(float), nan=-999),
                            np.nan_to_num(sel[ncols].values.astype(float), nan=-999))).any(axis=1).sum())
    t2[month] = {'n': len(sel), 'mismatch': mism}
res['T2_neighbor_dong'] = t2
# T3 정답 없이 변수만 쓰는지: 변수 열에 next_* / T / event 파생이 없는지 이름 점검
feat_cols = [c for c in X.columns if c.startswith(('prev_', 'h_', 's1_', 's2_', 'f_', 'floor_', 'close_month', 'covid'))]
label_cols = {'gap', 'event', 'T', 'next_occupant', 'next_ld', 'next_service', 'censor_bulk_registration'}
res['T3_feature_names_clean'] = not (set(feat_cols) & label_cols) and not any(c.startswith('next') for c in feat_cols)
print(json.dumps(res, ensure_ascii=False, indent=1))
json.dump(res, open(os.path.join(VF, 'test_asof_result.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
ok = res['T1_history_single']['mismatch'] == 0 and all(v['mismatch'] == 0 for v in t2.values()) and res['T3_feature_names_clean']
print('PASS' if ok else 'FAIL'); sys.exit(0 if ok else 1)
