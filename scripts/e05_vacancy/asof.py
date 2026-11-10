"""1단계: 시점 기준(as-of) 사례·변수 생성. 계획 docs/e05/vacancy_fill_plan.md 3·5절.

원칙: 사례의 예측 시점 a 에서 쓰는 모든 값은 'a 시점까지 알 수 있던 기록'만으로 계산한다.
  - 개업: ld <= a 인 가게만 존재한다.
  - 폐업: cd <= a 인 것만 폐업으로 안다. 늦은 신고(규칙 2) 때문에 주변 폐업·영업 수는 cd <= a-30일만 폐업으로 센다.
  - 자리 이력은 2003년 이후 기록만 센다(2000년 이전 폐업 누락).
사례 정의(단독 자리 여부)도 폐업 시점 t0 까지의 기록으로 판정한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DAY = pd.Timedelta(days=1)
LAG = 30            # 늦은 신고 보정(일)
TOL = 60            # 양도 겹침 허용(일), 서비스와 동일
HIST_START = pd.Timestamp('2003-01-01')
CELL_M = 100        # 주변 집계 격자(m)
RADIUS_CELLS = 3    # 반경 약 300m

GROUP = {
    '일반음식점': '음식점', '관광식당': '음식점',
    '휴게음식점': '카페·제과', '제과점영업': '카페·제과',
    '단란주점영업': '주점', '유흥주점영업': '주점', '관광유흥음식점업': '주점', '외국인전용유흥음식점업': '주점',
    '즉석판매제조가공업': '식품판매', '축산판매업': '식품판매', '식품판매업(기타)': '식품판매', '건강기능식품일반판매업': '식품판매',
    '미용업': '미용·이용', '이용업': '미용·이용',
    '의원': '의료·약', '병원': '의료·약', '약국': '의료·약', '안경업': '의료·약', '의료유사업': '의료·약',
    '동물병원': '동물', '동물약국': '동물', '동물미용업': '동물', '동물판매업': '동물', '동물위탁관리업': '동물',
    '노래연습장업': '오락', '인터넷컴퓨터게임시설제공업': '오락', '청소년게임제공업': '오락', '일반게임제공업': '오락',
    '복합유통게임제공업': '오락', '비디오물감상실업': '오락', '비디오물소극장업': '오락', '복합영상물제공업': '오락',
    '비디오물시청제공업': '오락',
    '체력단련장업': '운동', '체육도장업': '운동', '골프연습장업': '운동', '당구장업': '운동', '무도학원업': '운동', '무도장업': '운동',
    '세탁업': '생활', '목욕장업': '생활',
    '담배소매업': '담배',
}
GROUPS = sorted(set(GROUP.values()))
BULK = {'동물미용업', '동물위탁관리업'}   # 2018년 제도 도입 일괄 등록(규칙 1)


def load_occupants(stores: pd.DataFrame, units: pd.DataFrame) -> pd.DataFrame:
    """인허가(stores) → 가게(점유자) 표. 좌표는 자리 대표 좌표(units)를 쓴다."""
    g = stores.groupby('occupant_id')
    occ = stores[stores.is_primary].set_index('occupant_id')[
        ['uid', 'building_key', 'service', 'category', 'name', 'gu', 'dong', 'floor', 'area_m2']].copy()
    occ['ld'] = g.ld.min()
    occ['closed'] = g.closed.all()
    occ['cd'] = g.cd.max().where(occ.closed)
    occ['n_licenses'] = g.size()
    occ = occ.reset_index()
    occ['group'] = occ.service.map(GROUP)
    assert occ.group.notna().all(), occ.loc[occ.group.isna(), 'service'].unique()
    xy = units.set_index('uid')[['lat', 'lon']]
    occ = occ.join(xy, on='uid')
    return occ


def floor_class(f) -> str:
    if not isinstance(f, str):
        return '미상'
    if f.startswith('지하'):
        return '지하'
    return '1층' if f in ('1층',) else '2층이상'


# ───────────── 사례(시점 기준 단독 자리) ─────────────
def _max_conc_asof(ld: np.ndarray, cd: np.ndarray, closed: np.ndarray, t0: np.datetime64) -> int:
    """t0 시점까지의 기록으로 센 동시영업 최댓값. t0 이후 폐업은 모르는 것으로 본다."""
    m = ld <= t0
    if not m.any():
        return 0
    s = ld[m]
    known_close = closed[m] & (cd[m] <= t0)
    e = np.where(known_close, cd[m] - np.timedelta64(TOL, 'D'), t0 + np.timedelta64(1, 'D'))
    e = np.maximum(e, s + np.timedelta64(1, 'D'))
    t = np.concatenate([s, e]); d = np.concatenate([np.ones(len(s), int), -np.ones(len(s), int)])
    o = np.lexsort((d, t))
    return int(np.cumsum(d[o]).max())


def build_episodes(occ: pd.DataFrame, ref: pd.Timestamp, years=(2012, 2023)) -> pd.DataFrame:
    """폐업 t0 가 years 범위인 가게 → 사례. 단독 여부는 t0 까지의 기록으로 판정."""
    o = occ.sort_values(['uid', 'ld', 'occupant_id']).reset_index(drop=True)
    nxt = o.groupby('uid')[['occupant_id', 'ld', 'service']].shift(-1)
    o['next_occupant'], o['next_ld'], o['next_service'] = nxt.occupant_id, nxt.ld, nxt.service
    cand = o[o.closed & o.cd.notna() & o.cd.dt.year.between(*years)].copy()
    by_uid = {u: (g.ld.to_numpy('datetime64[ns]'), g.cd.to_numpy('datetime64[ns]'), g.closed.to_numpy())
              for u, g in o[o.uid.isin(cand.uid.unique())].groupby('uid')}
    cand['max_conc_t0'] = [_max_conc_asof(*by_uid[u], np.datetime64(t)) for u, t in zip(cand.uid, cand.cd)]
    cand['single_asof'] = cand.max_conc_t0 <= 1
    e = cand[cand.single_asof].copy()
    e['gap'] = (e.next_ld - e.cd).dt.days
    e = e[~(e.gap < -TOL)].copy()
    e['event'] = e.next_ld.notna()
    e['T'] = np.where(e.event, e.gap, (ref - e.cd).dt.days).astype(float)
    bulk = e.event & e.next_service.isin(BULK) & (e.next_ld.dt.year == 2018)
    e['censor_bulk_registration'] = bulk
    e.loc[bulk, 'event'] = False
    e = e.rename(columns={'cd': 't0'})
    e['close_year'] = e.t0.dt.year
    e['split'] = np.select([e.close_year <= 2019, e.close_year <= 2021], ['train', 'valid'], 'test')
    return e.reset_index(drop=True)


# ───────────── 월별 격자·자리 상태(주변·지역 변수용) ─────────────
MONTH0 = pd.Timestamp('2000-01-01')


def month_idx(ts: pd.Series | pd.Timestamp):
    if isinstance(ts, pd.Timestamp):
        return (ts.year - 2000) * 12 + ts.month - 1
    return ((ts.dt.year - 2000) * 12 + ts.dt.month - 1)


class Panels:
    """월 단위 누적 패널. 월 m 의 값 = m 월 말까지 알 수 있던 상태(조회는 예측 시점 직전 달).
    폐업은 LAG 를 반영해 한 달 늦게 반영한다(cd 월 + 1)."""

    def __init__(self, occ: pd.DataFrame, ref: pd.Timestamp):
        self.M = month_idx(ref) + 2
        o = occ[occ.lat.notna()].copy()
        y = o.lat.to_numpy() * 111000.0
        x = o.lon.to_numpy() * 111000.0 * np.cos(np.radians(35.87))
        o['cx'] = np.floor(x / CELL_M).astype(int); o['cy'] = np.floor(y / CELL_M).astype(int)
        self.cells = {c: i for i, c in enumerate(sorted(set(zip(o.cx, o.cy))))}
        o['ci'] = [self.cells[c] for c in zip(o.cx, o.cy)]
        o['gi'] = o.group.map({g: i for i, g in enumerate(GROUPS)})
        om = month_idx(o.ld).clip(lower=0).to_numpy()
        cm = (month_idx(o.cd.fillna(pd.Timestamp('2100-01-01'))) + 1).clip(lower=0).to_numpy()  # 늦은 신고 1개월
        ok_c = o.closed.to_numpy() & (cm < self.M)
        C, G, M = len(self.cells), len(GROUPS), self.M
        self.open_g = np.zeros((C, M, G), np.int32); self.close_g = np.zeros((C, M, G), np.int32)
        np.add.at(self.open_g, (o.ci.to_numpy(), np.minimum(om, M - 1), o.gi.to_numpy()), 1)
        np.add.at(self.close_g, (o.ci.to_numpy()[ok_c], cm[ok_c], o.gi.to_numpy()[ok_c]), 1)
        self.cum_open = np.cumsum(self.open_g, axis=1, dtype=np.int32); self.cum_close = np.cumsum(self.close_g, axis=1, dtype=np.int32)
        del self.open_g, self.close_g
        # 자리 상태: 자리별 영업 수, 마지막 폐업 월
        u = o.groupby('uid').agg(ci=('ci', 'first')).reset_index()
        self.uidx = {k: i for i, k in enumerate(u.uid)}
        U = len(u)
        ui = o.uid.map(self.uidx).to_numpy()
        uo = np.zeros((U, M), np.int16); uc = np.zeros((U, M), np.int16)
        np.add.at(uo, (ui, np.minimum(om, M - 1)), 1)
        np.add.at(uc, (ui[ok_c], cm[ok_c]), 1)
        active = uo.cumsum(1) - uc.cumsum(1)
        last_close = np.where(uc > 0, np.arange(M)[None, :], -10 ** 6)
        last_close = np.maximum.accumulate(last_close, axis=1)
        since = np.arange(M)[None, :] - last_close
        ever = uo.cumsum(1) > 0
        self.vacant_recent = (active == 0) & ever & (since >= 3) & (since <= 36)     # 유효 공실(90일~3년)
        self.live = ever & ((active > 0) | (since <= 36))                            # 공실률 분모
        self.ucell = u.ci.to_numpy()
        # 격자별 공실·분모 패널
        self.vac_cell = np.zeros((C, M), np.int32); self.live_cell = np.zeros((C, M), np.int32)
        np.add.at(self.vac_cell, self.ucell, self.vacant_recent.astype(np.int32))
        np.add.at(self.live_cell, self.ucell, self.live.astype(np.int32))
        r = RADIUS_CELLS
        self.offsets = [(dx, dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1) if dx * dx + dy * dy <= r * r + 1]
        self.occ_cell = dict(zip(o.occupant_id, o.ci))
        self.cell_xy = np.array(sorted(self.cells, key=self.cells.get))

    def neigh(self, ci: int) -> np.ndarray:
        cx, cy = self.cell_xy[ci]
        idx = [self.cells.get((cx + dx, cy + dy)) for dx, dy in self.offsets]
        return np.array([i for i in idx if i is not None])


def neighbor_features(ep: pd.DataFrame, P: Panels, at: pd.Series, prefix: str) -> pd.DataFrame:
    """반경 약 300m(격자) 주변 변수. at = 예측 시점(사례별). 자기 자리 기여는 빼지 않는다(상대 비교용, 모든 사례 동일)."""
    gi = ep.group.map({g: i for i, g in enumerate(GROUPS)}).to_numpy()
    # 예측 시점이 속한 달의 직전 달 말 상태를 쓴다(같은 달 안의 미래 개업이 섞이지 않게)
    m = (month_idx(at) - 1).clip(lower=0, upper=P.M - 1).to_numpy()
    rows = []
    for k, (oid, mm, g) in enumerate(zip(ep.occupant_id, m, gi)):
        ci = P.occ_cell.get(oid)
        if ci is None:
            rows.append([np.nan] * 8); continue
        nb = P.neigh(ci)
        act = P.cum_open[nb, mm, :].sum(0) - P.cum_close[nb, mm, :].sum(0)
        m12 = max(mm - 12, 0)
        op12 = (P.cum_open[nb, mm, :] - P.cum_open[nb, m12, :]).sum(0)
        cl12 = (P.cum_close[nb, mm, :] - P.cum_close[nb, m12, :]).sum(0)
        vac = P.vac_cell[nb, mm].sum(); live = P.live_cell[nb, mm].sum()
        rows.append([act.sum(), act[g], op12.sum(), cl12.sum(), op12.sum() - cl12.sum(), op12[g] - cl12[g], vac,
                     vac / live if live else np.nan])
    cols = ['nb_active', 'nb_active_same', 'nb_open_12m', 'nb_close_12m', 'nb_net_12m', 'nb_net_same_12m',
            'nb_vacant', 'nb_vacancy_rate']
    return pd.DataFrame(rows, columns=[f'{prefix}{c}' for c in cols], index=ep.index)


def history_features(ep: pd.DataFrame, occ: pd.DataFrame) -> pd.DataFrame:
    """자리 이력(2003년 이후, t0 이전에 시작한 가게만). 사례 가게 자신 포함."""
    o = occ[['occupant_id', 'uid', 'ld', 'cd', 'closed', 'group']].sort_values(['uid', 'ld'])
    o = o[o.uid.isin(ep.uid.unique())]
    first_ld = o.groupby('uid').ld.min()
    nxt_ld = o.groupby('uid').ld.shift(-1)
    o = o.assign(gap=(nxt_ld - o.cd).dt.days, nxt_ld=nxt_ld)
    out = []
    grp = {u: g for u, g in o.groupby('uid')}
    for uid, t0, lf in zip(ep.uid, ep.t0, ep.ld):
        g = grp[uid]
        h = g[(g.ld <= t0) & (g.ld >= HIST_START)]
        # 이전 공실 기간: 폐업과 다음 개업이 모두 t0 이전에 관측된 것
        gaps = h.gap[(h.closed) & (h.cd < t0) & (h.nxt_ld <= t0) & (h.gap >= -TOL)]
        out.append([len(h), int((h.closed & (h.cd <= t0)).sum()), len(gaps),
                    gaps.clip(lower=0).mean() if len(gaps) else np.nan,
                    (t0 - first_ld[uid]).days / 365.25, h.group.nunique()])
    return pd.DataFrame(out, columns=['h_n_occ', 'h_n_closed', 'h_n_turnover', 'h_mean_gap_days', 'h_years_since_first',
                                      'h_n_groups'], index=ep.index)


def dong_features(ep: pd.DataFrame, P: Panels, occ: pd.DataFrame, at: pd.Series, prefix: str) -> pd.DataFrame:
    """동 단위 공실률·3년 순증(그 시점). 동 = 법정동(인허가 주소)."""
    o = occ[occ.lat.notna()]
    u2dong = o.groupby('uid').agg(gu=('gu', 'first'), dong=('dong', 'first'))
    keys = (u2dong.gu.fillna('') + ' ' + u2dong.dong.fillna('')).reindex(list(P.uidx)).to_numpy()
    dkeys = {k: i for i, k in enumerate(sorted(set(keys)))}
    di = np.array([dkeys[k] for k in keys])
    D = len(dkeys)
    vac = np.zeros((D, P.M), np.int32); live = np.zeros((D, P.M), np.int32)
    np.add.at(vac, di, P.vacant_recent.astype(np.int32)); np.add.at(live, di, P.live.astype(np.int32))
    # 예측 시점이 속한 달의 직전 달 말 상태를 쓴다(같은 달 안의 미래 개업이 섞이지 않게)
    m = (month_idx(at) - 1).clip(lower=0, upper=P.M - 1).to_numpy()
    ek = (ep.gu.fillna('') + ' ' + ep.dong.fillna('')).map(dkeys)
    r = []
    for k, mm in zip(ek, m):
        if pd.isna(k):
            r.append([np.nan, np.nan]); continue
        k = int(k); m36 = max(mm - 36, 0)
        r.append([vac[k, mm] / live[k, mm] if live[k, mm] else np.nan,
                  (live[k, mm] - live[k, m36]) / live[k, m36] if live[k, m36] else np.nan])
    return pd.DataFrame(r, columns=[f'{prefix}dong_vacancy_rate', f'{prefix}dong_live_change_3y'], index=ep.index)


def base_features(ep: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=ep.index)
    f['prev_group'] = ep.group
    f['prev_life_years'] = (ep.t0 - ep.ld).dt.days / 365.25
    f['prev_area_m2'] = ep.area_m2.where(ep.area_m2 > 0)
    f['prev_n_licenses'] = ep.n_licenses
    f['floor_class'] = ep.floor.map(floor_class)
    f['f_gu'] = ep.gu
    f['close_month'] = ep.t0.dt.month
    f['covid'] = ep.t0.between(pd.Timestamp('2020-03-01'), pd.Timestamp('2022-04-30')).astype(int)
    return f
