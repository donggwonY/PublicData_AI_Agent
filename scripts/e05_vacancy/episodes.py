"""0단계: 공실 사례 표. 입력 = $E05_WORK/input (C 빌드 고정본). 계획: docs/e05/vacancy_fill_plan.md"""
import sys, os, json, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as E5P
VF, IN = E5P.VF, E5P.IN
REF = pd.Timestamp(json.load(open(os.path.join(IN, 'meta.json'), encoding='utf-8'))['reference_date'])
s = pd.read_parquet(os.path.join(IN, 'stores.parquet'))
u = pd.read_parquet(os.path.join(IN, 'units.parquet'), columns=['uid', 'is_single_unit'])
g = s.groupby('occupant_id')
occ = s[s.is_primary].set_index('occupant_id')[['uid', 'service', 'category', 'name', 'gu', 'dong', 'floor', 'area_m2', 'lat', 'lon']].copy()
occ['ld'] = g.ld.min(); occ['closed'] = g.closed.all(); occ['cd'] = g.cd.max().where(occ.closed)
occ['n_licenses'] = g.size(); occ = occ.reset_index()
single = set(u.loc[u.is_single_unit, 'uid'])          # 0단계 재현용(최종 기록 기준). 1단계에서 시점 기준으로 교체
o = occ[occ.uid.isin(single)].sort_values(['uid', 'ld']).reset_index(drop=True)
nx = o.groupby('uid')[['occupant_id', 'ld', 'service']].shift(-1)
e = o[o.closed & o.cd.notna()].copy()
e['next_occupant'] = nx.loc[e.index, 'occupant_id']; e['next_ld'] = nx.loc[e.index, 'ld']; e['next_service'] = nx.loc[e.index, 'service']
e['gap'] = (e.next_ld - e.cd).dt.days
e = e[~(e.gap < -60)].copy()
e['event'] = e.next_ld.notna()
e['T'] = np.where(e.event, e.gap, (REF - e.cd).dt.days).astype(float)
e = e[e.cd.dt.year.between(2012, 2023)].copy()
n0, l0 = len(e), int((e['T'] > 90).sum())
# 규칙 1: 제도 도입 첫해 일괄 등록(동물미용·동물위탁관리 2018 인허가)이 다음 가게면 그 날짜에서 중도절단
bulk = e.event & e.next_service.isin(['동물미용업', '동물위탁관리업']) & (e.next_ld.dt.year == 2018)
e['censor_bulk_registration'] = bulk
e.loc[bulk, 'event'] = False
e['close_year'] = e.cd.dt.year
e['split'] = np.select([e.close_year <= 2019, e.close_year <= 2021], ['train', 'valid'], 'test')
e = e.rename(columns={'cd': 't0'}).reset_index(drop=True)
cols = ['occupant_id', 'uid', 'gu', 'dong', 'floor', 'service', 'category', 'name', 'area_m2', 'lat', 'lon', 'n_licenses',
        'ld', 't0', 'close_year', 'split', 'next_occupant', 'next_ld', 'next_service', 'gap', 'event', 'T', 'censor_bulk_registration']
e[cols].to_parquet(os.path.join(VF, 'episodes.parquet'), index=False)
l = e[e['T'] > 90]
rep = {'reference_date': str(REF.date()), 'episodes_before_rule': n0, 'landmark90_before_rule': l0,
       'episodes': len(e), 'bulk_registration_censored': int(bulk.sum()),
       'event_pct': round(e.event.mean() * 100, 1), 'filled_within_90d_pct': round((e.event & (e['T'] <= 90)).mean() * 100, 1),
       'landmark90': len(l), 'landmark_events': int(l.event.sum()),
       'by_split': e.groupby('split').agg(n=('event', 'size'), events=('event', 'sum')).to_dict('index'),
       'landmark_by_split': l.groupby('split').agg(n=('event', 'size'), events=('event', 'sum')).to_dict('index')}
json.dump(rep, open(os.path.join(VF, 'episodes_report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2, default=int)
print(json.dumps(rep, ensure_ascii=False, indent=1, default=int))
