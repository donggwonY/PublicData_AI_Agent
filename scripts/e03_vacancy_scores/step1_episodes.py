"""E-03 공실 점수 1단계: v5 서비스 데이터로 사례를 다시 만들고, 현재 공백 후보와 모델 사례의 연결률을 확인한다.

모델·학습 없음. 입력
  - 실험 고정 빌드: $E05_WORK/input (E-05 실험 입력)
  - v5 서비스 데이터: service/data/processed (기본값, $V5_DIR 로 바꿀 수 있음)
결과: $E03_OUT/step1_episodes.json (+ 연결표 parquet)
"""
import json, os, sys, time
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, 'scripts', 'e05_vacancy'))
import asof as A  # noqa: E402  (paths.py 는 import 하지 않음)

FROZEN = os.path.join(os.environ['E05_WORK'], 'input')
V5 = os.environ.get('V5_DIR', os.path.join(REPO, 'service', 'data', 'processed'))
OUT = os.environ['E03_OUT']
os.makedirs(OUT, exist_ok=True)
VMIN, VMAX = 90, 1095          # service/config.py VACANCY_MIN_DAYS·MAX_DAYS 와 같은 값(아래에서 확인)
t0 = time.time()
log = lambda *a: print(f'[{time.time()-t0:5.0f}s]', *a, flush=True)


def load(d):
    meta = json.load(open(os.path.join(d, 'meta.json'), encoding='utf-8'))
    s = pd.read_parquet(os.path.join(d, 'stores.parquet'))
    u = pd.read_parquet(os.path.join(d, 'units.parquet'))
    return meta, s, u


mf, sf, uf = load(FROZEN)
mv, sv, uv = load(V5)
ref = pd.Timestamp(mv['reference_date'])
res = {'inputs': {'frozen': {'reference_date': mf['reference_date'], 'built_at': mf.get('built_at')},
                  'v5': {'dir': os.path.relpath(V5, REPO), 'reference_date': mv['reference_date'], 'built_at': mv.get('built_at')}}}

# ── A. 고정 빌드 vs v5: 공통 열 값이 같은가 ──
key = ['occupant_id', 'mgmt_no', 'org_code', 'service']
common = [c for c in sf.columns if c in sv.columns]
a = sf.sort_values(key).reset_index(drop=True)[common]; b = sv.sort_values(key).reset_index(drop=True)[common]
diff = {c: int((~((a[c] == b[c]) | (a[c].isna() & b[c].isna()))).sum()) for c in common}
ucommon = [c for c in uf.columns if c in uv.columns]
ua = uf.sort_values('uid').reset_index(drop=True)[ucommon]; ub = uv.sort_values('uid').reset_index(drop=True)[ucommon]
udiff = {c: int((~((ua[c] == ub[c]) | (ua[c].isna() & ub[c].isna()))).sum()) for c in ucommon}
res['frozen_vs_v5'] = {
    'stores_rows': [len(sf), len(sv)], 'units_rows': [len(uf), len(uv)],
    'stores_only_in_v5': [c for c in sv.columns if c not in sf.columns],
    'stores_cols_with_diff': {c: n for c, n in diff.items() if n}, 'units_cols_with_diff': {c: n for c, n in udiff.items() if n},
    'short_event_occupants': int(sv.drop_duplicates('occupant_id').short_event.sum()) if 'short_event' in sv else None}
log('frozen vs v5', res['frozen_vs_v5'])

# ── B. v5로 사례 재생성: 실험 범위(2012–2023) + 서비스용 확장(2012–2026) ──
occ = A.load_occupants(sv, uv[['uid', 'lat', 'lon']])
ep = A.build_episodes(occ, ref, years=(2012, 2026))
ep['T'] = ep['T'].astype(float)
exp_rng = ep.close_year.between(2012, 2023)
occf = A.load_occupants(sf, uf[['uid', 'lat', 'lon']])
epf = A.build_episodes(occf, pd.Timestamp(mf['reference_date']))
cnt = lambda e: {'episodes': len(e), 'events': int(e.event.sum()), 'landmark90': int((e['T'] > 90).sum()),
                 'landmark90_events': int(((e['T'] > 90) & e.event).sum())}
same = set(ep[exp_rng].occupant_id) == set(epf.occupant_id)
res['episodes'] = {'frozen_2012_2023': cnt(epf), 'v5_2012_2023': cnt(ep[exp_rng]), 'v5_2012_2023_same_ids_as_frozen': same,
                   'v5_2012_2026': cnt(ep),
                   'v5_by_close_year': ep.groupby('close_year').apply(lambda e: cnt(e), include_groups=False).to_dict()}
if same:
    m = ep[exp_rng].set_index('occupant_id')[['event', 'T']].join(epf.set_index('occupant_id')[['event', 'T']], rsuffix='_f')
    res['episodes']['v5_vs_frozen_event_or_T_diff'] = int(((m.event != m.event_f) | (m['T'] != m['T_f'])).sum())
log('episodes', {k: v for k, v in res['episodes'].items() if k != 'v5_by_close_year'})

# ── C. 현재 공백 후보(서비스 정의) ↔ 모델 사례 연결 ──
cand = uv[uv.vacant & uv.vacant_days.between(VMIN, VMAX) & uv.is_single_unit].copy()
res['candidates'] = {'n': len(cand), 'definition': f'vacant & {VMIN}<=vacant_days<={VMAX} & is_single_unit (find_vacant_units 기본값)'}
# 자리의 마지막 가게(가장 늦게 개업) = 사례 후보
last = occ.sort_values(['uid', 'ld', 'occupant_id']).groupby('uid').tail(1).set_index('uid')
c = cand[['uid', 'vacant_days', 'last_close', 'last_service']].join(last[['occupant_id', 'cd', 'closed', 'service']], on='uid')
epi = ep.set_index('occupant_id')
c['in_episodes'] = c.occupant_id.isin(epi.index)
c = c.join(epi[['T', 'event', 'single_asof', 'max_conc_t0', 'close_year']], on='occupant_id')
reason = np.select(
    [c.occupant_id.isna(), ~c.closed.fillna(False).astype(bool), c.cd != c.last_close, ~c.in_episodes,
     c.event.fillna(False).astype(bool), (c['T'] - c.vacant_days).abs() > 0],
    ['자리에 가게 없음', '마지막 가게가 폐업 아님', '마지막 가게 폐업일≠자리 마지막 폐업일', '사례에 없음(시점 기준 다점포 등)',
     '사례에서는 이미 채워짐', '공백 일수 불일치'], 'ok')
c['link'] = reason
c['band'] = pd.cut(c.vacant_days, [89, 180, 365, 730, 1095], labels=['90~180일', '180일~1년', '1~2년', '2~3년'])
res['candidates']['link'] = c.link.value_counts().to_dict()
res['candidates']['linked'] = int((c.link == 'ok').sum())
res['candidates']['linked_pct'] = round((c.link == 'ok').mean() * 100, 2)
res['candidates']['by_band'] = {str(k): {'n': len(g), 'linked': int((g.link == 'ok').sum())}
                                for k, g in c.groupby('band', observed=True)}
res['candidates']['close_year_of_linked'] = c[c.link == 'ok'].close_year.value_counts().sort_index().to_dict()
res['candidates']['by_last_service_top'] = c.last_service.value_counts().head(10).to_dict()
c.to_parquet(os.path.join(OUT, 'step1_candidate_links.parquet'), index=False)
ep.to_parquet(os.path.join(OUT, 'step1_episodes_v5.parquet'), index=False)
res['seconds'] = round(time.time() - t0)
json.dump(res, open(os.path.join(OUT, 'step1_episodes.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=int)
log('candidates', {k: v for k, v in res['candidates'].items() if k not in ('by_last_service_top',)})
