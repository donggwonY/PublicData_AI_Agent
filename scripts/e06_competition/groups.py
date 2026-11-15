"""E-06 저빈도 업종 묶음 검토. 계획 docs/e06/models_plan.md 변경 기록 2 (2026-11-15 고정).

묶음과 낱개 업종 모두 같은 방식(개업 기준선: 동 B4, 구 B2 / 폐업 B2)으로 계산해 단위 규칙을 적용한다.
개발 2014–2019로 단위를 정하고 검증 2020–2022는 보고만 한다. 2022년 이후 사건은 쓰지 않는다.
실행(저장소 루트): C:\\claude_workspace\\e06_env\\Scripts\\python scripts/e06_competition/groups.py
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from snapshot_hashes import snapshot_sha256

SRC = ROOT / 'service/data/processed/stores.parquet'
OUT = ROOT / 'docs/e06/results/groups.json'
LAST_YEAR = 2022
DEV, VAL = list(range(2014, 2020)), [2020, 2021, 2022]
YEARS = list(range(2003, LAST_YEAR + 1))
MERGE = {'통닭(치킨)': '호프/통닭', '까페': '커피숍'}
GROUPS = {
    '카페류': ['커피숍', '다방', '전통찻집', '라이브카페', '키즈카페'],
    '디저트·빵': ['제과점영업', '과자점', '아이스크림', '떡카페'],
    '분식·김밥': ['분식', '김밥(도시락)'],
    '주점': ['호프/통닭', '정종/대포집/소주방', '감성주점'],
    '양식': ['경양식', '패밀리레스트랑'],
    '한식류': ['한식', '냉면집', '탕류(보신용)', '복어취급'],
    '체육도장': ['태권도', '합기도', '검도', '유도', '권투', '우슈', '레슬링', '체육도장업'],
    '세탁': ['일반세탁업', '빨래방업', '운동화전문세탁업', '세탁업 기타'],
}

s0 = pd.read_parquet(SRC)
s0 = s0[s0.is_primary & ~s0.short_event.astype(bool) & s0.dong.notna()].copy()
s0['category'] = s0.category.replace(MERGE)
s0['oy'] = s0.ld.dt.year
s0['cy'] = np.where(s0.closed, s0.cd.dt.year, np.nan)


def panel(d, keys):
    key = d[keys].astype(str).agg('|'.join, axis=1)
    o = d[d.oy.between(YEARS[0], LAST_YEAR)].groupby([key, d.oy]).size()
    c = d[d.cy.between(YEARS[0], LAST_YEAR)].groupby([key, d.cy]).size()
    idx = pd.MultiIndex.from_product([key.unique(), YEARS], names=['key', 'year'])
    P = pd.DataFrame({'opens': o.reindex(idx, fill_value=0).values, 'closes': c.reindex(idx, fill_value=0).values}, index=idx)
    act = {}
    for y in YEARS:
        end = pd.Timestamp(f'{y}-12-31')
        act[y] = d[(d.ld <= end) & (~d.closed | (d.cd > end))].groupby(key).size()
    P['active_end'] = [act[y].get(k, 0) for k, y in P.index]
    P = P.reset_index().sort_values(['key', 'year']).reset_index(drop=True)
    parts = P.key.str.split('|', expand=True)
    for i, k in enumerate(keys):
        P[k] = parts[i]
    g = P.groupby('key')
    P['o_m3'] = g.opens.transform(lambda x: x.shift(1).rolling(3).mean())
    P['c_m3'] = g.closes.transform(lambda x: x.shift(1).rolling(3).mean())
    P['o_s5'] = g.opens.transform(lambda x: x.shift(1).rolling(5).sum())
    P['active_prev'] = g.active_end.shift(1)
    P['net'] = P.opens - P.closes
    P = P[P.year.isin(DEV + VAL)]
    return P[(P.active_prev >= 1) | (P.o_m3 >= 1 / 3)].reset_index(drop=True)


def ppf_counts(q, mu, alpha=0.0):
    mu = np.maximum(np.asarray(mu, float), 1e-9); k = np.zeros_like(mu)
    if alpha <= 0:
        pmf = np.exp(-mu); ratio = lambda i: mu / i
    else:
        r = 1 / alpha; pmf = (r / (r + mu)) ** r; ratio = lambda i: (i - 1 + r) / i * mu / (r + mu)
    cdf = pmf.copy()
    for i in range(1, 5000):
        need = cdf < q
        if not need.any(): break
        pmf = np.where(need, pmf * ratio(i), pmf); cdf = np.where(need, cdf + pmf, cdf); k = np.where(need, i, k)
    return k


def cover(y, mu, a=0.0):
    return float(np.mean((y >= ppf_counts(0.1, mu, a)) & (y <= ppf_counts(0.9, mu, a)))) if len(y) else None


def nb_alpha(y, m):
    return float(max(0.0, ((y - m) ** 2 - m).sum() / max((m ** 2).sum(), 1e-9)))


def tiers(d):
    """d: 한 업종(또는 묶음) 가게들. 구·동 패널과 기준선 예측."""
    T1 = panel(d, ['gu'])
    T2 = panel(d, ['gu', 'dong'])
    gu = T1[['gu', 'year', 'o_m3', 'c_m3', 'o_s5', 'active_prev']].rename(
        columns={'o_m3': 'gu_o', 'c_m3': 'gu_c', 'o_s5': 'gu_s5', 'active_prev': 'gu_act'})
    T2 = T2.merge(gu, on=['gu', 'year'], how='left')
    share = np.where(T2.gu_s5 > 0, T2.o_s5 / T2.gu_s5, np.where(T2.gu_act > 0, T2.active_prev / T2.gu_act, 0.0))
    T2['po'], T2['pc'] = T2.gu_o * share, T2.gu_c * share         # B4 (동 개업·폐업)
    T1['po'], T1['pc'] = T1.o_m3, T1.c_m3                         # B2 (구)
    return {'구': T1.dropna(subset=['po']), '동': T2.dropna(subset=['po'])}


def metrics(T):
    D, V = T[T.year.isin(DEV)], T[T.year.isin(VAL)]
    if len(V) == 0: return None
    a = nb_alpha(D.opens.values, D.po.values)
    y, mu = V.opens.values, V.po.values
    pn, nz = V.po - V.pc, V.net != 0
    acc = float(np.mean((pn[nz] > 0) == (V.net[nz] > 0))) if nz.sum() else None
    maj = float(max(np.mean(V.net[nz] > 0), np.mean(V.net[nz] < 0))) if nz.sum() else None
    return {'cells': int(len(V)), 'mean_opens': round(float(y.mean()), 2),
            'wape': round(float(np.abs(y - mu).sum() / max(y.sum(), 1)), 3),
            'cov80_poisson': round(cover(y, mu), 3), 'cov80_negbin': round(cover(y, mu, a), 3), 'alpha_dev': round(a, 4),
            'net_sign_acc': None if acc is None else round(acc, 3), 'net_majority': None if maj is None else round(maj, 3),
            'net_nonzero': int(nz.sum()), 'show_direction': bool(acc is not None and acc >= 0.65 and acc >= maj + 0.05)}


def judge(d):
    t = tiers(d)
    D2, D1 = t['동'][t['동'].year.isin(DEV)], t['구'][t['구'].year.isin(DEV)]
    m_dong = float(D2.opens.mean()) if len(D2) else 0.0
    cov_dong = cover(D2.opens.values, D2.po.values) if len(D2) else None
    m_gu = float(D1.opens.mean()) if len(D1) else 0.0
    unit = ('동' if m_dong >= 2 and cov_dong is not None and 0.75 <= cov_dong <= 0.90
            else '구' if m_gu >= 2 else '대구 추세만')
    return {'unit': unit, 'dev_mean_opens_dong': round(m_dong, 2), 'dev_cov80_B4_dong': None if cov_dong is None else round(cov_dong, 3),
            'dev_mean_opens_gu': round(m_gu, 2), 'val_dong': metrics(t['동']), 'val_gu': metrics(t['구'])}


res = {'plan': 'docs/e06/models_plan.md#변경-기록 (2)', 'input_sha256': snapshot_sha256(SRC), 'groups': {}}
for gname, members in GROUPS.items():
    present = [m for m in members if (s0.category == m).any()]
    r = {'members_present': present, 'members_missing': [m for m in members if m not in present],
         'group': judge(s0[s0.category.isin(present)]),
         'members': {m: judge(s0[s0.category == m]) for m in present}}
    r['newly_local'] = [m for m in present if r['members'][m]['unit'] == '대구 추세만' and r['group']['unit'] != '대구 추세만']
    res['groups'][gname] = r
    g = r['group']; mu = g['val_' + ('dong' if g['unit'] == '동' else 'gu')]
    print(gname, g['unit'], g['dev_mean_opens_dong'], g['dev_cov80_B4_dong'], g['dev_mean_opens_gu'], '| val', mu)
    for m in present:
        x = r['members'][m]; xm = x['val_' + ('dong' if x['unit'] == '동' else 'gu')]
        print('   ', m, x['unit'], x['dev_mean_opens_dong'], x['dev_cov80_B4_dong'], x['dev_mean_opens_gu'],
              '| val', None if xm is None else {k: xm[k] for k in ('cells', 'wape', 'cov80_poisson', 'cov80_negbin', 'net_sign_acc', 'net_majority')})
OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
