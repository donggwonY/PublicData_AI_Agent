"""누수 비교(논문용): 같은 사례·같은 모델로 ⓐ 시점 재계산 변수 vs ⓑ 최종 기록 변수. 계획 final_test_plan.md 6절.
ⓑ: 자리 이력 = units 최종 값, 주변·동·지하철·인구·상가정보 = 기준일(2026-11-06) 값. 직전 가게 변수는 동일."""
import json, os, sys, time, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as E5P
import mlib as L, asof as A, ext as E, sangga as G

VF, IN = E5P.VF, E5P.IN; OUT = os.path.join(VF, 'leakage_compare.json')
t0 = time.time(); log = lambda *a: print(f'[{time.time()-t0:6.0f}s]', *a, flush=True)
REF = pd.Timestamp('2026-11-06')
SGC = ['sg_floor_total', 'sg_floor_other', 'sg_bldg_other', 'sg_floor_new_other', 'sg_nb_total', 'sg_nb_other_share', 'sg_nb_change_1y']
L.LOG |= {'sg_floor_total', 'sg_floor_other', 'sg_bldg_other', 'sg_floor_new_other', 'sg_nb_total'}
Xa = pd.read_parquet(os.path.join(VF, 'asof_episodes.parquet')).merge(
    pd.read_parquet(os.path.join(VF, 'sangga_features.parquet')), on='occupant_id', how='left', validate='one_to_one')

# ⓑ 최종 기록 변수
Xb = Xa.copy()
units = pd.read_parquet(os.path.join(IN, 'units.parquet')).set_index('uid')
tr_final = pd.read_parquet(os.path.join(IN, 'transitions.parquet'))
gap_mean = tr_final.groupby('uid').gap_days.apply(lambda s: s.clip(lower=0).mean())
u = units.reindex(Xb.uid)
Xb['h_n_occ'] = u.n_records.to_numpy(); Xb['h_n_closed'] = u.n_closed.to_numpy()
Xb['h_n_turnover'] = (u.n_records - 1).clip(lower=0).to_numpy()
Xb['h_mean_gap_days'] = gap_mean.reindex(Xb.uid).to_numpy()
Xb['h_years_since_first'] = ((REF - u.first_open).dt.days / 365.25).to_numpy()
Xb['h_n_groups'] = u.n_categories.to_numpy()
stores = pd.read_parquet(os.path.join(IN, 'stores.parquet'))
occ = A.load_occupants(stores, pd.read_parquet(os.path.join(IN, 'units.parquet'), columns=['uid', 'lat', 'lon']))
P = A.Panels(occ, REF)
AUX = E5P.AUX
SUB = E.load_subway(os.path.join(AUX, 'subway', 'subway_monthly.csv'), os.path.join(AUX, 'station', 'daegu_station_location.xlsx'))
POP = E.load_population(os.path.join(AUX, 'population'))
LMAP = pd.read_parquet(E5P.LMAP)
SG = G.SG(pd.read_parquet(os.path.join(VF, 'sangga_quarters.parquet')))
at = pd.Series(REF + pd.Timedelta(days=31), index=Xb.index)   # 직전 달 = 기준일이 속한 달
for f in (A.neighbor_features(Xb, P, at, 's2_'), A.dong_features(Xb, P, occ, at, 's2_'),
          E.subway_features(Xb, SUB, at, 's2_'), E.population_features(Xb, POP, LMAP, pd.Series(REF, index=Xb.index), 's2_'),
          SG.features(Xb, pd.Series(REF, index=Xb.index), 's2_')):
    Xb[f.columns] = f.to_numpy()
log('final-record features built')

NUM = L.numeric_cols('s2') + ['s2_' + c for c in SGC]
prev = json.load(open(os.path.join(VF, 'models_sangga.json'), encoding='utf-8'))
MODELS = {'M3': (False, lambda: L.M3RSF(**prev['stage2']['params']['M3_rsf|sangga'])),
          'M1': (True, lambda: L.M1Cox(**prev['stage2']['params']['M1_cox|sangga']))}
PERIODS = {'valid': (((2016, 2019), '2021-12-31'), ((2020, 2021), '2023-12-31')),
           'test': (((2016, 2021), '2023-12-31'), ((2022, 2023), '2026-11-06'))}
res = {'definition_b': __doc__, 'periods': {}}
ci = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
for per, ((ytr_, etr), (yte_, ete)) in PERIODS.items():
    out = {}
    S = {}
    for fs, XX in (('asof', Xa), ('final_record', Xb)):
        dtr = L.stage2(L.split(XX, ytr_, etr)); dte = L.stage2(L.split(XX, yte_, ete))
        ytr, yte = L.surv_y(dtr), L.surv_y(dte)
        for mn, (scale, mk) in MODELS.items():
            pr = L.Prep(NUM, scale).fit(dtr)
            m = mk().fit(pr.transform(dtr), dtr)
            S[f'{mn}|{fs}'] = m.surv(pr.transform(dte))
            out[f'{mn}|{fs}'] = L.s2_metrics(S[f'{mn}|{fs}'], yte, ytr)
            log(per, mn, fs, round(out[f'{mn}|{fs}']['c_index'], 4))
    rng = np.random.default_rng(0); n = len(yte); bt = {k: [] for k in S}
    for b in range(500):
        i = rng.integers(0, n, n)
        for k, v in S.items():
            bt[k].append(L.s2_metrics(v[i], yte[i], ytr)['c_index'])
    out['final_minus_asof_c_index'] = {mn: {'point': out[f'{mn}|final_record']['c_index'] - out[f'{mn}|asof']['c_index'],
                                            'ci': ci(np.array(bt[f'{mn}|final_record']) - np.array(bt[f'{mn}|asof']))}
                                       for mn in MODELS}
    out['n'] = {'n': len(dte), 'events': int(dte.ev.sum())}
    res['periods'][per] = out
    json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
# 사례 선택 누수(참고)
res['episode_selection'] = {'final_record_single_unit_episodes': 28063, 'asof_single_unit_episodes': int(len(Xa))}
res['seconds'] = round(time.time() - t0)
json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
log('done')
