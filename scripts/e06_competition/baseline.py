"""E-06 1단계: 동네×업종 연간 개업·폐업·순증감 기준선 점검. 계획 docs/e06/plan.md (2026-11-15 고정).

개발 2014–2019, 검증 2020–2022. 시험 구간(2023–2025)은 계산하지 않는다(2022년 이후 사건은 집계 전에 버림).
실행(저장소 루트): service/.venv/Scripts/python scripts/e06_competition/baseline.py
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd


def poisson_ppf(q, mu):
    """포아송 분위수(벡터): P(X<=k) >= q 를 만족하는 가장 작은 k."""
    mu = np.asarray(mu, float); k = np.zeros_like(mu); pmf = np.exp(-mu); cdf = pmf.copy()
    for i in range(1, 400):
        need = cdf < q
        if not need.any(): break
        pmf = np.where(need, pmf * mu / i, pmf); cdf = np.where(need, cdf + pmf, cdf); k = np.where(need, i, k)
    return k


def spearman(a, b):
    return pd.Series(np.asarray(a)).rank().corr(pd.Series(np.asarray(b)).rank())

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from snapshot_hashes import snapshot_sha256

SRC = ROOT / 'service/data/processed/stores.parquet'
OUT = ROOT / 'docs/e06/results/baseline.json'
FIRST_HIST, LAST_YEAR = 2009, 2022          # 2022 = 검증 마지막 목표 연도. 그 뒤 사건은 쓰지 않음
DEV, VAL = range(2014, 2020), range(2020, 2023)
FOCUS = ['한식', '커피숍', '일반미용업', '호프/통닭', '분식', '중국식', '경양식',
         '일식', '제과점영업', '네일아트업', '피부미용업', '편의점']
# 2016년 분류 이름 변경으로 끊긴 업종을 잇는다(service/config.py CATEGORY_ALIASES 와 같은 방향). plan.md 변경 기록 1
MERGE = {'통닭(치킨)': '호프/통닭', '까페': '커피숍'}
SIZE_BINS, SIZE_LABELS = [-1, 4, 19, np.inf], ['0-4', '5-19', '20+']

# ── 1. 정제 ────────────────────────────────────────────────
s = pd.read_parquet(SRC)
counts = {'rows': len(s)}
s = s[s.is_primary]; counts['primary'] = len(s)
s = s[~s.short_event.astype(bool)]; counts['no_short_event'] = len(s)
counts['dong_missing_dropped'] = int(s.dong.isna().sum())
s = s[s.dong.notna()].copy()
counts['merged_rows'] = {k: int((s.category == k).sum()) for k in MERGE}
s['category'] = s.category.replace(MERGE)
s['key'] = s.gu + '|' + s.dong + '|' + s.category
s['oy'] = s.ld.dt.year
s['cy'] = np.where(s.closed, s.cd.dt.year, np.nan)

# ── 2. 연간 패널 (2022년까지만) ─────────────────────────────
years = list(range(FIRST_HIST - 5, LAST_YEAR + 1))
o = s[s.oy.between(years[0], LAST_YEAR)].groupby(['key', 'oy']).size()
c = s[s.cy.between(years[0], LAST_YEAR)].groupby(['key', 'cy']).size()
keys = s.key.unique()
idx = pd.MultiIndex.from_product([keys, years], names=['key', 'year'])
P = pd.DataFrame(index=idx)
P['opens'] = o.reindex(idx, fill_value=0).values
P['closes'] = c.reindex(idx, fill_value=0).values
act = {}
for y in years:
    end = pd.Timestamp(f'{y}-12-31')
    alive = (s.ld <= end) & (~s.closed | (s.cd > end))
    act[y] = s[alive].groupby('key').size()
P['active_end'] = [act[y].get(k, 0) for k, y in P.index]
P['net'] = P.opens - P.closes
P = P.reset_index().sort_values(['key', 'year'])
g = P.groupby('key')
for col in ['opens', 'closes', 'net']:
    sh = g[col].shift(1)
    P[f'{col}_B1'] = sh
    P[f'{col}_B2'] = g[col].transform(lambda x: x.shift(1).rolling(3).mean())
    P[f'{col}_B3'] = g[col].transform(lambda x: x.shift(1).rolling(5).mean())
P['net_B0'] = 0.0
P['active_prev'] = g.active_end.shift(1)
P['opens_prev3'] = g.opens.transform(lambda x: x.shift(1).rolling(3).sum())
P = P[P.year.isin(list(DEV) + list(VAL))]
P = P[(P.active_prev >= 1) | (P.opens_prev3 >= 1)].copy()
P['size'] = pd.cut(P.active_prev, SIZE_BINS, labels=SIZE_LABELS).astype(str)
P['category'] = P.key.str.split('|').str[2]
P['split'] = np.where(P.year.isin(DEV), 'dev', 'val')

# ── 3. 데이터 점검: 대구 업종별 개업 급증(일괄 등록 의심) ──────
dy = s[s.oy.between(years[0], LAST_YEAR)].groupby(['category', 'oy']).size().unstack(fill_value=0)
jumps = []
for cat, row in dy.iterrows():
    for y in range(2014, LAST_YEAR + 1):
        prev = row[[y - 3, y - 2, y - 1]].mean() if all(v in row.index for v in (y-3, y-2, y-1)) else 0
        if row.get(y, 0) >= 30 and row.get(y, 0) > 3 * max(prev, 1):
            jumps.append({'category': cat, 'year': y, 'opens': int(row[y]), 'prev3_mean': round(float(prev), 1)})

# ── 4. 평가 ────────────────────────────────────────────────
def mae(d, col, b):
    return float(np.mean(np.abs(d[col] - d[f'{col}_{b}'])))

def block(d):
    r = {'cells': int(len(d))}
    for col, bs in (('opens', ['B1', 'B2', 'B3']), ('closes', ['B1', 'B2', 'B3']), ('net', ['B0', 'B1', 'B2', 'B3'])):
        m = {b: round(mae(d, col, b), 4) for b in bs}
        r[col] = {'mean_actual': round(float(d[col].mean()), 3), 'mae': m,
                  'ratio_vs_B1': {b: round(v / m['B1'], 3) for b, v in m.items()} if m['B1'] > 0 else None}
    return r

# 경험적 80% 구간: 개발 구간의 (실제 − B2) 오차 분위수, 규모별
dev = P[P.split == 'dev']
q = dev.assign(err=dev.opens - dev.opens_B2).groupby('size').err.quantile([0.1, 0.9]).unstack()

def coverage(d):
    mu = d.opens_B2.values
    lo_p, hi_p = poisson_ppf(0.1, mu), poisson_ppf(0.9, mu)
    lo_e = np.floor(np.maximum(0, mu + d['size'].map(q[0.1]).values))
    hi_e = np.ceil(mu + d['size'].map(q[0.9]).values)
    y = d.opens.values
    return {'poisson': round(float(np.mean((y >= lo_p) & (y <= hi_p))), 3),
            'empirical': round(float(np.mean((y >= lo_e) & (y <= hi_e))), 3),
            'empirical_mean_width': round(float(np.mean(hi_e - lo_e)), 2)}

def rank_and_sign(d):
    r = {}
    big = d[d.active_prev >= 5]
    for b in ['B1', 'B2', 'B3']:
        rho = spearman(big[f'opens_{b}'] / big.active_prev, big.opens / big.active_prev)
        r[f'opens_rate_spearman_{b}'] = round(float(rho), 3)
    nz = d[d.net != 0]
    for b in ['B0', 'B1', 'B2', 'B3']:
        r[f'net_sign_acc_{b}'] = round(float(np.mean((nz[f'net_{b}'] > 0) == (nz.net > 0))), 3)
    r['net_nonzero_cells'] = int(len(nz)); r['net_increase_share'] = round(float(np.mean(nz.net > 0)), 3)
    r['big_cells'] = int(len(big))
    return r

res = {'plan': 'docs/e06/plan.md', 'input': {'path': 'service/data/processed/stores.parquet',
       'sha256': snapshot_sha256(SRC)}, 'filter_counts': counts, 'bulk_jump_flags': jumps,
       'empirical_q_dev': {k: {'q10': float(v[0.1]), 'q90': float(v[0.9])} for k, v in q.iterrows()},
       'category_merge': MERGE, 'by_year': {}, 'val_by_size': {}, 'val_focus': {}}
for y in list(DEV) + list(VAL):
    d = P[P.year == y]
    res['by_year'][str(y)] = {**block(d), **rank_and_sign(d), 'coverage80': coverage(d)}
val = P[P.split == 'val']
res['val_all'] = {**block(val), **rank_and_sign(val), 'coverage80': coverage(val)}
res['dev_all'] = {**block(dev), 'coverage80': coverage(dev)}
for sz in SIZE_LABELS:
    d = val[val['size'] == sz]
    res['val_by_size'][sz] = {**block(d), 'coverage80': coverage(d)}
for cat in FOCUS:
    d = val[val.category == cat]
    if len(d):
        res['val_focus'][cat] = {'cells': int(len(d)), 'mean_opens': round(float(d.opens.mean()), 2),
                                 'opens_mae': {b: round(mae(d, 'opens', b), 3) for b in ['B1', 'B2', 'B3']},
                                 'coverage80': coverage(d)}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
print(json.dumps({k: res[k] for k in ['filter_counts', 'val_all', 'val_by_size']}, ensure_ascii=False, indent=1))
print('jumps', len(jumps), jumps[:15])
