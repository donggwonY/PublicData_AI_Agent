"""상가정보 시점 기준 변수. 계획 docs/e05/sangga_plan.md.

규칙: 분기 자료는 분기 말 + 60일부터 사용 가능. 사례는 예측 시점 a 에 사용 가능한 가장 최근 분기를 쓴다.
"""
from __future__ import annotations

import glob
import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'service'))
from core.address import parse_jibun  # noqa: E402

AVAIL_LAG = pd.Timedelta(days=60)
CELL_M, R = 100, 3
KY = 111000.0
KX = 111000.0 * np.cos(np.radians(35.87))
COLS = ['상가업소번호', '상권업종소분류코드', '지번주소', '층정보', '경도', '위도']


def norm_floor_sg(v) -> str | None:
    if not isinstance(v, str) or not v.strip():
        return None
    v = v.strip().upper()
    m = re.fullmatch(r'(\d+)', v)
    if m:
        return f'{int(m[1])}층'
    m = re.fullmatch(r'(?:B|지하|지)(\d*)', v)
    if m:
        return f'지하{int(m[1]) if m[1] else 1}층'
    return None


def load_quarters(folder: str, catmap_csv: str) -> pd.DataFrame:
    cm = pd.read_csv(catmap_csv, dtype=str)
    other = set(cm.loc[cm['구분'] == '42종 밖', '상권업종소분류코드'])
    known = set(cm['상권업종소분류코드'])
    cache: dict[str, str | None] = {}
    fr = []
    for f in sorted(glob.glob(os.path.join(folder, 'sangga_daegu_*.csv'))):
        q = pd.Timestamp(re.search(r'sangga_daegu_(\d{8})', os.path.basename(f))[1])
        x = pd.read_csv(f, encoding='utf-8-sig', dtype=str, usecols=COLS)
        for a in x['지번주소'].dropna().unique():
            if a not in cache:
                cache[a] = (parse_jibun(a) or {}).get('key')
        fr.append(pd.DataFrame({
            'q': q, 'sid': x['상가업소번호'].to_numpy(),
            'other': x['상권업종소분류코드'].isin(other).to_numpy(),
            'unknown_code': (~x['상권업종소분류코드'].isin(known)).to_numpy(),
            'bkey': x['지번주소'].map(cache).to_numpy(),
            'floor': x['층정보'].map(norm_floor_sg).to_numpy(),
            'lat': pd.to_numeric(x['위도'], errors='coerce').to_numpy(),
            'lon': pd.to_numeric(x['경도'], errors='coerce').to_numpy()}))
    d = pd.concat(fr, ignore_index=True)
    qs = sorted(d.q.unique())
    d['qi'] = d.q.map({q: i for i, q in enumerate(qs)})
    # 직전 분기에 없던 상가업소번호 = 새로 나타난 점포
    prev = {i: set(d.loc[d.qi == i - 1, 'sid']) for i in range(1, len(qs))}
    d['new'] = [False if qi == 0 else sid not in prev[qi] for qi, sid in zip(d.qi, d.sid)]
    return d


class SG:
    def __init__(self, d: pd.DataFrame):
        self.d = d
        self.qs = sorted(d.q.unique())
        self.avail = np.array([q + AVAIL_LAG for q in self.qs], dtype='datetime64[ns]')
        f = d[d.bkey.notna()]
        self.floor = f[f.floor.notna()].groupby(['qi', 'bkey', 'floor']).agg(
            total=('sid', 'size'), other=('other', 'sum'), new_other=('new', lambda s: 0)).copy()
        no = f[f.floor.notna() & f.new & f.other].groupby(['qi', 'bkey', 'floor']).size()
        self.floor['new_other'] = no.reindex(self.floor.index).fillna(0)
        self.bldg = f.groupby(['qi', 'bkey']).agg(total=('sid', 'size'), other=('other', 'sum'))
        g = d[d.lat.notna() & d.lon.notna()].copy()
        g['cx'] = np.floor(g.lon * KX / CELL_M).astype(int); g['cy'] = np.floor(g.lat * KY / CELL_M).astype(int)
        self.cell = g.groupby(['qi', 'cx', 'cy']).agg(total=('sid', 'size'), other=('other', 'sum'))
        self.cell_d = {k: (int(v.total), int(v.other)) for k, v in self.cell.iterrows()}
        self.offsets = [(dx, dy) for dx in range(-R, R + 1) for dy in range(-R, R + 1) if dx * dx + dy * dy <= R * R + 1]
        self.floor_d = self.floor.to_dict('index'); self.bldg_d = self.bldg.to_dict('index')

    def qidx(self, a: pd.Series) -> np.ndarray:
        i = np.searchsorted(self.avail, a.to_numpy('datetime64[ns]'), side='right') - 1
        return i                                            # -1 = 사용 가능한 분기 없음

    def _nb(self, qi, lat, lon):
        cx, cy = int(np.floor(lon * KX / CELL_M)), int(np.floor(lat * KY / CELL_M))
        t = o = 0
        for dx, dy in self.offsets:
            v = self.cell_d.get((qi, cx + dx, cy + dy))
            if v:
                t += v[0]; o += v[1]
        return t, o

    def features(self, ep: pd.DataFrame, at: pd.Series, prefix: str) -> pd.DataFrame:
        qi = self.qidx(at)
        # 4분기 전: 사용 가능 분기 중 분기 말이 330일 이상 앞선 가장 가까운 분기
        qdates = np.array(self.qs, dtype='datetime64[ns]')
        rows = []
        for i, bk, fl, lat, lon in zip(qi, ep.building_key, ep.floor, ep.lat, ep.lon):
            if i < 0:
                rows.append([np.nan] * 7); continue
            fv = self.floor_d.get((i, bk, fl)) if isinstance(fl, str) else None
            ft = fv['total'] if fv else (0 if isinstance(fl, str) else np.nan)
            fo = fv['other'] if fv else (0 if isinstance(fl, str) else np.nan)
            fn = fv['new_other'] if fv else (0 if isinstance(fl, str) else np.nan)
            bv = self.bldg_d.get((i, bk))
            bo = bv['other'] if bv else 0
            if np.isfinite(lat):
                t, o = self._nb(i, lat, lon)
                j = np.searchsorted(qdates, qdates[i] - np.timedelta64(330, 'D'), side='right') - 1
                t0 = self._nb(j, lat, lon)[0] if j >= 0 else 0
                share = o / t if t else np.nan
                chg = (t / t0 - 1) if (j >= 0 and t0) else np.nan
            else:
                t = share = chg = np.nan
            rows.append([ft, fo, bo, fn, t, share, chg])
        cols = ['sg_floor_total', 'sg_floor_other', 'sg_bldg_other', 'sg_floor_new_other', 'sg_nb_total',
                'sg_nb_other_share', 'sg_nb_change_1y']
        return pd.DataFrame(rows, columns=[prefix + c for c in cols], index=ep.index)
