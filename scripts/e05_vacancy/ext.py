"""보조 변수(시점 기준): 지하철 월별 승차, 행정동 인구.

공통 규칙: 예측 시점 a 가 속한 달의 '직전 달'까지 값만 쓴다(asof.py 와 동일).
  - 지하철: 직전 달까지 승차 기록이 양수인 역만 '개통'으로 본다(최초 양수 월 = 개통 근사).
  - 인구: 직전 달 말 기준 주민등록 인구. 공개 시차(통상 다음 달 초)는 직전 달을 쓰면 대부분 흡수된다.
"""
from __future__ import annotations

import glob
import os
import re

import numpy as np
import pandas as pd

from asof import month_idx

RENAME = {'대공원': '수성알파시티'}


def _base(name: str) -> str:
    return re.sub(r'\(.*?\)', '', str(name)).strip()


def load_subway(sub_csv: str, loc_xlsx: str):
    r = pd.read_csv(sub_csv, encoding='cp949')
    r['m'] = (r['년'] - 2000) * 12 + r['월'] - 1
    r = r[r.m >= 0]                                # 패널 기준 2000-01, 사례는 2012~
    cols = [c for c in r.columns if c not in ('년', '월', 'm')]
    long = r.melt(id_vars='m', value_vars=cols, var_name='col', value_name='board')
    long['board'] = pd.to_numeric(long.board.astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    long['station'] = long.col.str.replace(r'\d$', '', regex=True).map(lambda s: RENAME.get(s, s))
    rid = long.groupby(['station', 'm']).board.sum().unstack('m').fillna(0)   # 환승역은 노선 합산
    loc = pd.read_excel(loc_xlsx)
    loc['station'] = loc['역명'].map(_base)
    loc = loc.groupby('station')[['위도', '경도']].mean()
    common = rid.index.intersection(loc.index)
    missing = sorted(set(rid.index) - set(loc.index))
    rid = rid.loc[common]
    loc = loc.loc[common]
    months = rid.columns.to_numpy()
    full = np.zeros((len(common), months.max() + 2))
    full[:, months] = rid.to_numpy()
    cum = np.cumsum(full > 0, axis=1)              # 양수 기록 누적(개통 판정)
    return {'names': list(common), 'lat': loc['위도'].to_numpy(), 'lon': loc['경도'].to_numpy(),
            'board': full, 'opened': cum > 0, 'missing_coord': missing}


def subway_features(ep: pd.DataFrame, S: dict, at: pd.Series, prefix: str) -> pd.DataFrame:
    m = (month_idx(at) - 1).clip(lower=0, upper=S['board'].shape[1] - 1).to_numpy()
    ky = 111000.0; kx = 111000.0 * np.cos(np.radians(35.87))
    sy, sx = S['lat'] * ky, S['lon'] * kx
    out = []
    for lat, lon, mm in zip(ep.lat, ep.lon, m):
        if not np.isfinite(lat):
            out.append([np.nan] * 3); continue
        ok = S['opened'][:, mm]
        if not ok.any():
            out.append([np.nan] * 3); continue
        d = np.hypot(sy - lat * ky, sx - lon * kx)
        d = np.where(ok, d, np.inf)
        j = int(np.argmin(d))
        b = S['board'][j]
        last12 = b[max(mm - 11, 0): mm + 1]; prev12 = b[max(mm - 23, 0): max(mm - 11, 0)]
        mean12 = last12[last12 > 0].mean() if (last12 > 0).any() else np.nan
        meanp = prev12[prev12 > 0].mean() if (prev12 > 0).any() else np.nan
        out.append([d[j], mean12, (mean12 / meanp - 1) if meanp and np.isfinite(meanp) else np.nan])
    return pd.DataFrame(out, columns=[f'{prefix}sub_dist_m', f'{prefix}sub_board_12m', f'{prefix}sub_board_yoy'],
                        index=ep.index)


# ───────────── 인구 ─────────────
_ROW = re.compile(r'^대구광역시\s*(?P<gu>\S+?(구|군))?\s*(?P<dong>\S+)?\s*\((?P<code>\d{10})\)$')


def load_population(folder: str) -> pd.DataFrame:
    """행안부 연령별 인구(월간, 10세 구간) → 긴 표: code, gu, dong, m, pop, p2039, p60."""
    rows = []
    for f in sorted(glob.glob(os.path.join(folder, 'pop_*.csv'))):
        d = pd.read_csv(f, dtype=str)
        area = d['행정구역'].str.strip()
        for col_tot in [c for c in d.columns if c.endswith('_계_총인구수')]:
            ym = col_tot.split('_')[0]                       # 2011년01월
            y, mo = int(ym[:4]), int(ym[5:7])
            g = lambda s: pd.to_numeric(d[f'{ym}_계_{s}'].str.replace(',', ''), errors='coerce')
            pop = g('총인구수')
            p2039 = g('20~29세') + g('30~39세')
            p60 = g('60~69세') + g('70~79세') + g('80~89세') + g('90~99세') + g('100세 이상')
            rows.append(pd.DataFrame({'area': area, 'm': (y - 2000) * 12 + mo - 1, 'pop': pop, 'p2039': p2039,
                                      'p60': p60}))
    p = pd.concat(rows, ignore_index=True)
    mt = p.area.str.extract(_ROW)
    p['code'] = mt.code; p['gu'] = mt.gu; p['dong'] = mt.dong
    p['level'] = np.where(p.dong.notna(), 'dong', np.where(p.gu.notna(), 'gu', 'city'))
    return p[p['pop'] > 0].drop_duplicates(['code', 'm'])


def population_features(ep: pd.DataFrame, pop: pd.DataFrame, lmap: pd.DataFrame, at: pd.Series,
                        prefix: str) -> pd.DataFrame:
    """법정동 → 행정동(상가정보에서 학습한 대표 매핑) → 그 시점 인구. 행정동을 못 찾으면 구 값으로 대체."""
    top = lmap.sort_values('share').drop_duplicates(['gu', 'legal_dong'], keep='last').set_index(['gu', 'legal_dong'])['admin_dong']
    dong = pop[pop.level == 'dong'].set_index(['gu', 'dong', 'm'])[['pop', 'p2039', 'p60']]
    gu = pop[pop.level == 'gu'].set_index(['gu', 'm'])[['pop', 'p2039', 'p60']]
    m = (month_idx(at) - 1).to_numpy()
    dk, gk = set(dong.index), set(gu.index)
    out = []
    for g, ld, mm in zip(ep.gu, ep.dong, m):
        ad = top.get((g, ld))
        src = None
        if ad is not None and (g, ad, mm) in dk and (g, ad, mm - 12) in dk:
            cur, prv, src = dong.loc[(g, ad, mm)], dong.loc[(g, ad, mm - 12)], 'dong'
        elif (g, mm) in gk and (g, mm - 12) in gk:
            cur, prv, src = gu.loc[(g, mm)], gu.loc[(g, mm - 12)], 'gu'
        if src is None:
            out.append([np.nan] * 4 + [0]); continue
        out.append([cur['pop'], cur.p2039 / cur['pop'], cur.p60 / cur['pop'], cur['pop'] / prv['pop'] - 1,
                    int(src == 'dong')])
    return pd.DataFrame(out, columns=[f'{prefix}pop', f'{prefix}pop_2039_share', f'{prefix}pop_60plus_share',
                                      f'{prefix}pop_change_12m', f'{prefix}pop_is_dong'], index=ep.index)
