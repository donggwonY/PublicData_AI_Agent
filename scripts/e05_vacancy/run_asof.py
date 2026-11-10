"""1단계 실행: 시점 기준 사례 + 변수 표 생성 → $E05_WORK/asof_episodes.parquet, $E05_WORK/asof_report.json"""
import json, os, sys, time
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as E5P
import asof as A
import ext as E

VF, IN = E5P.VF, E5P.IN
t = time.time()
REF = pd.Timestamp(json.load(open(os.path.join(IN, 'meta.json'), encoding='utf-8'))['reference_date'])
stores = pd.read_parquet(os.path.join(IN, 'stores.parquet'))
units = pd.read_parquet(os.path.join(IN, 'units.parquet'), columns=['uid', 'lat', 'lon'])
occ = A.load_occupants(stores, units)
ep = A.build_episodes(occ, REF)
print('episodes(as-of single)', len(ep), f'{time.time()-t:.0f}s', flush=True)
P = A.Panels(occ, REF)
AUX = E5P.AUX
SUB = E.load_subway(os.path.join(AUX, 'subway', 'subway_monthly.csv'), os.path.join(AUX, 'station', 'daegu_station_location.xlsx'))
POP = E.load_population(os.path.join(AUX, 'population'))
# 법정동→행정동 대표 매핑(상가정보 2026-06 에서 학습한 서비스 표). 행정구역 매핑이라 시점 민감도가 낮다.
LMAP = pd.read_parquet(E5P.LMAP)
print('panels', len(P.cells), 'cells', f'{time.time()-t:.0f}s', flush=True)
feats = [A.base_features(ep), A.history_features(ep, occ)]
for name, off in (('s1_', 0), ('s2_', 90)):
    at = ep.t0 + pd.Timedelta(days=off)
    feats.append(A.neighbor_features(ep, P, at, name))
    feats.append(A.dong_features(ep, P, occ, at, name))
    feats.append(E.subway_features(ep, SUB, at, name))
    feats.append(E.population_features(ep, POP, LMAP, at, name))
X = pd.concat([ep] + feats, axis=1)
X.to_parquet(os.path.join(VF, 'asof_episodes.parquet'), index=False)
l = X[X['T'] > 90]
final_single = set(pd.read_parquet(os.path.join(IN, 'units.parquet'), columns=['uid', 'is_single_unit']).query('is_single_unit').uid)
old = pd.read_parquet(os.path.join(VF, 'episodes.parquet'), columns=['occupant_id'])
rep = {'episodes': len(X), 'landmark90': len(l), 'events': int(X.event.sum()), 'landmark_events': int(l.event.sum()),
       'bulk_censored': int(X.censor_bulk_registration.sum()),
       'vs_final_single_episodes': {'final_only': len(set(old.occupant_id) - set(X.occupant_id)),
                                    'asof_only': len(set(X.occupant_id) - set(old.occupant_id))},
       'by_split': X.groupby('split').agg(n=('event', 'size'), events=('event', 'sum')).to_dict('index'),
       'landmark_by_split': l.groupby('split').agg(n=('event', 'size'), events=('event', 'sum')).to_dict('index'),
       'missing_pct': (X[[c for f in feats for c in f.columns]].isna().mean() * 100).round(1).to_dict(),
       'seconds': round(time.time() - t)}
json.dump(rep, open(os.path.join(VF, 'asof_report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2, default=int)
print(json.dumps(rep, ensure_ascii=False, indent=1, default=int))
