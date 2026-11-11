"""E-03 공실 점수 2단계: 2012–2026 폐업 사례의 시점 기준 변수 + 재현·누수 테스트 + 현재 후보 결측 점검.

E-05 코드(asof.py·ext.py·sangga.py)를 그대로 쓰고 사례 폐업 연도만 2026년까지 넓힌다. 모델·학습 없음.
입력
  - 인허가: service/data/processed (v5, 1단계에서 E-05 고정 빌드와 값 동일 확인) — $V5_DIR 로 변경 가능
  - 법정동→행정동 대응표: $E05_WORK/input/legal_admin_map.parquet (E-05 실험 당시 버전, 학습·점수 일관성)
  - 보조 자료: $E05_AUX (지하철·역 좌표·인구·상가정보)
  - 재현 기준: $E05_REF/asof_episodes.parquet, sangga_features.parquet (E-05 실험 산출물)
결과: $E03_OUT/asof_episodes_2026.parquet, sangga_features_2026.parquet, step2_features.json
"""
import json, os, sys, time
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, 'scripts', 'e05_vacancy'))
import asof as A   # noqa: E402
import ext as E    # noqa: E402
import sangga as G  # noqa: E402

V5 = os.environ.get('V5_DIR', os.path.join(REPO, 'service', 'data', 'processed'))
LMAP_P = os.path.join(os.environ['E05_WORK'], 'input', 'legal_admin_map.parquet')
AUX = os.environ['E05_AUX']; REF_DIR = os.environ['E05_REF']; OUT = os.environ['E03_OUT']
SANGGA_MAP = os.path.join(REPO, 'docs', 'e05', 'sangga_category_map.csv')
YEARS = (2012, 2026)
t00 = time.time()
log = lambda *a: print(f'[{time.time()-t00:6.0f}s]', *a, flush=True)

REF = pd.Timestamp(json.load(open(os.path.join(V5, 'meta.json'), encoding='utf-8'))['reference_date'])
stores = pd.read_parquet(os.path.join(V5, 'stores.parquet'))
units = pd.read_parquet(os.path.join(V5, 'units.parquet'))
occ = A.load_occupants(stores, units[['uid', 'lat', 'lon']])
ep = A.build_episodes(occ, REF, years=YEARS)
log('episodes', len(ep))
P = A.Panels(occ, REF)
SUB = E.load_subway(os.path.join(AUX, 'subway', 'subway_monthly.csv'), os.path.join(AUX, 'station', 'daegu_station_location.xlsx'))
POP = E.load_population(os.path.join(AUX, 'population'))
LMAP = pd.read_parquet(LMAP_P)
feats = [A.base_features(ep), A.history_features(ep, occ)]
for name, off in (('s1_', 0), ('s2_', 90)):
    at = ep.t0 + pd.Timedelta(days=off)
    feats += [A.neighbor_features(ep, P, at, name), A.dong_features(ep, P, occ, at, name),
              E.subway_features(ep, SUB, at, name), E.population_features(ep, POP, LMAP, at, name)]
X = pd.concat([ep] + feats, axis=1)
X.to_parquet(os.path.join(OUT, 'asof_episodes_2026.parquet'), index=False)
log('asof features', X.shape)
d = pd.read_parquet(os.path.join(REF_DIR, 'sangga_quarters.parquet'))   # 같은 44분기 원본에서 만든 E-05 중간표


def coord_qa(d):
    """분기별 좌표 점검: 직전 분기와 같은 점포번호의 좌표 이동(중앙값, m)과 좌표 중앙값."""
    qs = sorted(d.q.unique()); out = {}
    for p, q in zip(qs[:-1], qs[1:]):
        j = d[d.q == p].set_index('sid')[['lat', 'lon']].join(d[d.q == q].set_index('sid')[['lat', 'lon']], rsuffix='2', how='inner')
        mv = np.hypot((j.lat2 - j.lat) * G.KY, (j.lon2 - j.lon) * G.KX)
        out[str(q.date())] = {'matched': len(j), 'median_move_m': round(float(mv.median()), 1),
                              'lat_median': round(float(d.loc[d.q == q, 'lat'].median()), 4)}
    return out


# 원본 오류 보정(2026-11-11 발견): 2025-03-31 분기 파일만 좌표가 대구 밖(위도 +0.86·경도 +1.25 안팎, 위치마다 다름)으로 어긋남.
# 주소·업종은 정상. 같은 점포번호의 직전 분기(2024-12-31) 좌표로 대체하고, 직전 분기에 없는 점포는 좌표 결측으로 둔다
# (미래 분기 좌표는 쓰지 않음). 2012–2023 폐업 사례는 이 분기를 쓰지 않으므로 E-05 결과에 영향 없음.
BAD_Q, PREV_Q = pd.Timestamp('2025-03-31'), pd.Timestamp('2024-12-31')
qa_before = coord_qa(d)
bad = d.q == BAD_Q
prev_xy = d[d.q == PREV_Q].drop_duplicates('sid').set_index('sid')[['lat', 'lon']]
fill = prev_xy.reindex(d.loc[bad, 'sid'])
d.loc[bad, 'lat'] = fill.lat.to_numpy(); d.loc[bad, 'lon'] = fill.lon.to_numpy()
coord_fix = {'quarter': str(BAD_Q.date()), 'rows': int(bad.sum()), 'replaced_from_prev_quarter': int(fill.lat.notna().sum()),
             'left_missing_new_stores': int(fill.lat.isna().sum()),
             'qa_before': {k: v for k, v in qa_before.items() if v['median_move_m'] > 1 or abs(v['lat_median'] - 35.86) > 0.1}}
coord_fix['qa_after_max_median_move_m'] = max(v['median_move_m'] for v in coord_qa(d).values())
log('sangga coord fix', coord_fix)
sg = G.SG(d)
F = pd.concat([sg.features(X, X.t0, 's1_'), sg.features(X, X.t0 + pd.Timedelta(days=90), 's2_')], axis=1)
F.insert(0, 'occupant_id', X.occupant_id.to_numpy())
F.to_parquet(os.path.join(OUT, 'sangga_features_2026.parquet'), index=False)
log('sangga features', F.shape)
res = {'reference_date': str(REF.date()), 'years': YEARS, 'episodes': len(X), 'landmark90': int((X['T'] > 90).sum()),
       'aux_last_month': {'subway': f'{2000 + (SUB["board"].shape[1] - 2) // 12}-{(SUB["board"].shape[1] - 2) % 12 + 1:02d}',
                          'population': f'{2000 + POP.m.max() // 12}-{POP.m.max() % 12 + 1:02d}',
                          'sangga_quarter': str(max(sg.qs).date())},
       'sangga_coord_fix': coord_fix}


def same(a: pd.DataFrame, b: pd.DataFrame):
    a = a.apply(pd.to_numeric, errors='coerce').to_numpy(float); b = b.apply(pd.to_numeric, errors='coerce').to_numpy(float)
    return int((~np.isclose(np.nan_to_num(a, nan=-999), np.nan_to_num(b, nan=-999))).any(axis=1).sum())


# ── 1. 재현: 2012–2023 사례 변수가 E-05 실험 값과 같은가 ──
R = pd.read_parquet(os.path.join(REF_DIR, 'asof_episodes.parquet')).set_index('occupant_id')
RF = pd.read_parquet(os.path.join(REF_DIR, 'sangga_features.parquet')).set_index('occupant_id')
Xi = X.set_index('occupant_id'); Fi = F.set_index('occupant_id')
ids = R.index
num = [c for c in R.columns if c.startswith(('prev_life', 'prev_area', 'prev_n', 'h_', 's1_', 's2_', 'close_month', 'covid'))
       or c in ('T', 'event')]
cat = ['prev_group', 'floor_class', 'f_gu', 'split']
res['reproduce_2012_2023'] = {
    'ids_equal': bool(set(ids) == set(X.loc[X.close_year <= 2023, 'occupant_id'])),
    'numeric_cols': len(num), 'rows_numeric_mismatch': same(Xi.loc[ids, num], R[num]),
    'rows_category_mismatch': int((Xi.loc[ids, cat].astype(str) != R[cat].astype(str)).any(axis=1).sum()),
    'sangga_rows_mismatch': same(Fi.loc[RF.index, RF.columns], RF)}
log('reproduce', res['reproduce_2012_2023'])


# ── 2. 누수 테스트(E-05 test_asof·test_sangga 와 같은 방법, 최근 시점 추가) ──
def cut(o, c):
    o = o[o.ld <= c].copy(); fut = o.closed & (o.cd > c)
    o.loc[fut, 'closed'] = False; o.loc[fut, 'cd'] = pd.NaT
    return o


rng = np.random.default_rng(0)
recent = X[X.close_year >= 2024]
smp = recent.iloc[rng.choice(len(recent), 400, replace=False)]
hcols = ['h_n_occ', 'h_n_closed', 'h_n_turnover', 'h_mean_gap_days', 'h_years_since_first', 'h_n_groups']
bad = 0
for _, r in smp.iterrows():
    o = cut(occ[occ.uid == r.uid], r.t0).sort_values('ld')
    mc = A._max_conc_asof(o.ld.to_numpy('datetime64[ns]'), o.cd.to_numpy('datetime64[ns]'), o.closed.to_numpy(), np.datetime64(r.t0))
    h = A.history_features(pd.DataFrame([r]), o)
    if mc != r.max_conc_t0 or same(h[hcols], pd.DataFrame([r[hcols]])):
        bad += 1
res['T1_history_single_2024_2026'] = {'n': len(smp), 'mismatch': bad}
log('T1', res['T1_history_single_2024_2026'])
ncols = [c for c in X.columns if c.startswith('s2_')]
t2 = {}
for month in ['2024-03', '2025-06', '2026-08']:
    c = pd.Period(month).end_time.normalize(); nxt = pd.Period(month) + 1
    at = X.t0 + pd.Timedelta(days=90)
    sel = X[at.dt.to_period('M') == nxt]
    o = cut(occ, c); Pc = A.Panels(o, REF)
    a2 = sel.t0 + pd.Timedelta(days=90); mc = A.month_idx(c)
    sub_c = dict(SUB); sub_c['board'] = SUB['board'].copy(); sub_c['board'][:, mc + 1:] = 0
    sub_c['opened'] = np.cumsum(sub_c['board'] > 0, axis=1) > 0
    got = pd.concat([A.neighbor_features(sel, Pc, a2, 's2_'), A.dong_features(sel, Pc, o, a2, 's2_'),
                     E.subway_features(sel, sub_c, a2, 's2_'), E.population_features(sel, POP[POP.m <= mc], LMAP, a2, 's2_')], axis=1)[ncols]
    t2[month] = {'n': len(sel), 'mismatch': same(got, sel[ncols])}
    log('T2', month, t2[month])
res['T2_neighbor_dong_sub_pop'] = t2
t3 = {}
for qend in ['2024-03-31', '2025-06-30', '2026-06-30']:
    q = pd.Timestamp(qend); i = sg.qs.index(q)
    lo, hi = q + G.AVAIL_LAG, sg.qs[i + 1] + G.AVAIL_LAG
    at = X.t0 + pd.Timedelta(days=90); sel = (at >= lo) & (at < hi)
    got = G.SG(d[d.q <= q].copy()).features(X[sel], at[sel], 's2_')
    t3[qend] = {'n': int(sel.sum()), 'mismatch': same(got, F.loc[sel.to_numpy(), got.columns])}
    log('T3', qend, t3[qend])
res['T3_sangga'] = t3
feat_cols = [c for c in X.columns if c.startswith(('prev_', 'h_', 's1_', 's2_', 'f_', 'floor_', 'close_month', 'covid'))]
res['T4_feature_names_clean'] = not any(c in {'gap', 'event', 'T'} or c.startswith('next') for c in feat_cols)
res['leakage_pass'] = (bad == 0 and all(v['mismatch'] == 0 and v['n'] > 0 for v in list(t2.values()) + list(t3.values()))
                       and res['T4_feature_names_clean'])

# ── 3. 현재 후보 변수 결측: 학습 사례(2016–2023, 90일 넘게 빈)와 비교 ──
cand = units[units.vacant & units.vacant_days.between(90, 1095) & units.is_single_unit]
last = occ.sort_values(['uid', 'ld', 'occupant_id']).groupby('uid').tail(1)
cid = set(last[last.uid.isin(cand.uid)].occupant_id)
XF = X.merge(F, on='occupant_id', validate='one_to_one')
s2 = [c for c in XF.columns if c.startswith('s2_')]
cur = XF[XF.occupant_id.isin(cid)]; trn = XF[XF.close_year.between(2016, 2023) & (XF['T'] > 90)]
res['current_candidates'] = {'n': len(cur), 'all_open_T_equals_vacant_days': bool((~cur.event).all())}
res['missing_pct_s2'] = {c: {'train_2016_2023': round(trn[c].isna().mean() * 100, 1), 'current': round(cur[c].isna().mean() * 100, 1)}
                         for c in s2 if max(trn[c].isna().mean(), cur[c].isna().mean()) > 0}
res['current_sangga_quarter_used'] = pd.Series(np.array(sg.qs, dtype='datetime64[ns]')[sg.qidx(cur.t0 + pd.Timedelta(days=90))]
                                               ).dt.date.astype(str).value_counts().sort_index().to_dict()
res['seconds'] = round(time.time() - t00)
json.dump(res, open(os.path.join(OUT, 'step2_features.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=int)
log('done', json.dumps({k: v for k, v in res.items() if k not in ('missing_pct_s2',)}, ensure_ascii=False, default=int))
