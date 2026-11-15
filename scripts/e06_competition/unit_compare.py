"""E-06 단위 비교: 지역·업종·기간 단위를 바꿔 같은 기준선(3년 평균)의 품질을 비교한다.

baseline.py 와 같은 정제·분류 이어 붙이기·시간 분할을 쓴다. 2022년 이후 사건은 쓰지 않는다(시험 구간 봉인).
지역: 법정동 / 구 / 500m·1km 격자(가게 좌표 기준). 업종: 세부 업종(category) / 인허가 종류(service).
기간: 1년 / 2년 합계(검증 목표 2020–21만, 2022년까지로 끝남).
실행(저장소 루트): service/.venv/Scripts/python scripts/e06_competition/unit_compare.py
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from snapshot_hashes import snapshot_sha256

SRC = ROOT / 'service/data/processed/stores.parquet'
OUT = ROOT / 'docs/e06/results/unit_compare.json'
LAST_YEAR = 2022
MERGE = {'통닭(치킨)': '호프/통닭', '까페': '커피숍'}
FOCUS = ['한식', '커피숍', '일반미용업', '편의점', '호프/통닭']


def poisson_ppf(q, mu):
    mu = np.asarray(mu, float); k = np.zeros_like(mu); pmf = np.exp(-mu); cdf = pmf.copy()
    for i in range(1, 2000):
        need = cdf < q
        if not need.any(): break
        pmf = np.where(need, pmf * mu / i, pmf); cdf = np.where(need, cdf + pmf, cdf); k = np.where(need, i, k)
    return k


s = pd.read_parquet(SRC)
s = s[s.is_primary & ~s.short_event.astype(bool)].copy()
s['category'] = s.category.replace(MERGE)
s['oy'] = s.ld.dt.year
s['cy'] = np.where(s.closed, s.cd.dt.year, np.nan)
LAT_M, LON_M = 111_000, 90_200          # 대구(북위 약 35.9도) 1도당 m
for m in (500, 1000):
    ok = s.lat.notna() & s.lon.notna()
    s[f'grid{m}'] = np.where(ok, (np.floor(s.lat * LAT_M / m)).astype('Int64').astype(str) + '_' +
                             (np.floor(s.lon * LON_M / m)).astype('Int64').astype(str), None)
REGION = {'법정동': ['gu', 'dong'], '구': ['gu'], '격자500m': ['grid500'], '격자1km': ['grid1000']}
INDUSTRY = {'세부업종': 'category', '인허가종류': 'service'}


def panel(region, industry, horizon):
    d = s.dropna(subset=REGION[region]).copy()
    d['key'] = d[REGION[region]].astype(str).agg('|'.join, axis=1) + '|' + d[INDUSTRY[industry]]
    d['ind'] = d[INDUSTRY[industry]]
    years = list(range(2004, LAST_YEAR + 1))
    o = d[d.oy.between(years[0], LAST_YEAR)].groupby(['key', 'oy']).size()
    c = d[d.cy.between(years[0], LAST_YEAR)].groupby(['key', 'cy']).size()
    idx = pd.MultiIndex.from_product([d.key.unique(), years], names=['key', 'year'])
    P = pd.DataFrame({'opens': o.reindex(idx, fill_value=0).values,
                      'closes': c.reindex(idx, fill_value=0).values}, index=idx)
    act = {}
    for y in years:
        end = pd.Timestamp(f'{y}-12-31')
        act[y] = d[(d.ld <= end) & (~d.closed | (d.cd > end))].groupby('key').size()
    P['active_end'] = [act[y].get(k, 0) for k, y in P.index]
    P['net'] = P.opens - P.closes
    P = P.reset_index().sort_values(['key', 'year'])
    g = P.groupby('key')
    for col in ('opens', 'net'):
        # 목표: y ~ y+horizon-1 합계, 예측: 직전 3년 연평균 × horizon (전년 말 기준)
        P[f'{col}_T'] = sum(g[col].shift(-h) for h in range(horizon))
        P[f'{col}_B2'] = g[col].transform(lambda x: x.shift(1).rolling(3).mean()) * horizon
    P['active_prev'] = g.active_end.shift(1)
    P['opens_prev3'] = g.opens.transform(lambda x: x.shift(1).rolling(3).sum())
    val_years = [y for y in range(2020, 2023) if y + horizon - 1 <= LAST_YEAR]
    P = P[P.year.isin(val_years) & ((P.active_prev >= 1) | (P.opens_prev3 >= 1))].dropna(subset=['opens_T'])
    P['ind'] = P.key.str.split('|').str[-1]
    return P, val_years, len(s) - len(d)


def metrics(P):
    y, b = P.opens_T.values, P.opens_B2.values
    lo, hi = poisson_ppf(0.1, b), poisson_ppf(0.9, b)
    nz = P[P.net_T != 0]
    big = P[P.active_prev >= 5]
    rate = lambda col: big[col] / big.active_prev
    return {
        'cells': int(len(P)),
        'mean_opens': round(float(y.mean()), 2),
        'opens_wape': round(float(np.abs(y - b).sum() / y.sum()), 3),          # 상대 오차: Σ|오차| / Σ실제
        'opens_cov80_poisson': round(float(np.mean((y >= lo) & (y <= hi))), 3),
        'opens_rate_spearman': round(float(rate('opens_B2').rank().corr(rate('opens_T').rank())), 3) if len(big) > 30 else None,
        'net_mae_B2_over_B0': round(float(np.abs(P.net_T - P.net_B2).mean() / np.abs(P.net_T).mean()), 3),
        'net_sign_acc': round(float(np.mean((nz.net_B2 > 0) == (nz.net_T > 0))), 3),
        'net_increase_share': round(float(np.mean(nz.net_T > 0)), 3),
    }


res = {'input_sha256': snapshot_sha256(SRC), 'baseline': 'B2(직전 3년 평균 × 기간)', 'runs': []}
for region in REGION:
    for industry in INDUSTRY:
        for horizon in (1, 2):
            P, vy, dropped = panel(region, industry, horizon)
            r = {'region': region, 'industry': industry, 'horizon_years': horizon, 'val_years': vy,
                 'rows_dropped_no_region': int(dropped), **metrics(P)}
            if industry == '세부업종':
                r['focus'] = {c: metrics(P[P.ind == c]) for c in FOCUS if (P.ind == c).sum() > 30}
            res['runs'].append(r)
            print({k: v for k, v in r.items() if k != 'focus'})
OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
