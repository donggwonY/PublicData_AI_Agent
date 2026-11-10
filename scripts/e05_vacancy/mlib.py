"""3단계 공통 도구: 분할·전처리·모델·지표. 계획 docs/e05/models_plan.md"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from sklearn.linear_model import LogisticRegression
from sksurv.linear_model import CoxPHSurvivalAnalysis
from sksurv.ensemble import RandomSurvivalForest
from sksurv.metrics import concordance_index_ipcw, cumulative_dynamic_auc, integrated_brier_score
from sksurv.nonparametric import kaplan_meier_estimator
from sksurv.util import Surv
import lightgbm as lgb

H = [180, 365, 730]
GRID = np.arange(30, 721, 30)
TIMES = np.unique(np.concatenate([GRID, H]))
TAU = 730
MIN_N = 30
K_MAX = 24          # 이산시간 구간 수(30일 × 24 = 720일)

CAT = ['prev_group', 'floor_class', 'f_gu']
BASE_NUM = ['prev_life_years', 'prev_area_m2', 'prev_n_licenses', 'covid']
HIST = ['h_n_occ', 'h_n_closed', 'h_n_turnover', 'h_mean_gap_days', 'h_years_since_first', 'h_n_groups']
NB = ['nb_active', 'nb_active_same', 'nb_open_12m', 'nb_close_12m', 'nb_net_12m', 'nb_net_same_12m', 'nb_vacant',
      'nb_vacancy_rate', 'dong_vacancy_rate', 'dong_live_change_3y']
SUB = ['sub_dist_m', 'sub_board_12m', 'sub_board_yoy']
POP = ['pop', 'pop_2039_share', 'pop_60plus_share', 'pop_change_12m', 'pop_is_dong']
LOG = {'prev_area_m2', 'prev_n_licenses', 'h_n_occ', 'h_n_closed', 'h_n_turnover', 'h_mean_gap_days', 'nb_active',
       'nb_active_same', 'nb_open_12m', 'nb_close_12m', 'nb_vacant', 'sub_dist_m', 'sub_board_12m', 'pop'}
GROUPS = {'직전가게': CAT + BASE_NUM + ['month_sin', 'month_cos'], '자리이력': HIST, '주변·동': NB, '지하철': SUB, '인구': POP}


def numeric_cols(stage: str, sets=('L', 'S', 'P')) -> list[str]:
    p = 's2_' if stage == 's2' else 's1_'
    cols = BASE_NUM + HIST + [p + c for c in NB]
    if 'S' in sets:
        cols += [p + c for c in SUB]
    if 'P' in sets:
        cols += [p + c for c in POP]
    return cols


def censor(d: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
    d = d.copy()
    lim = (end - d.t0).dt.days
    d['ev'] = d.event & (d['T'] <= lim)
    d['tt'] = np.where(d.ev, d['T'], np.minimum(d['T'], lim)).astype(float)
    return d


def split(X: pd.DataFrame, years: tuple[int, int], end: str) -> pd.DataFrame:
    return censor(X[X.close_year.between(*years)], pd.Timestamp(end))


def stage2(d: pd.DataFrame) -> pd.DataFrame:
    d = d[d.tt > 90].copy(); d['dur'] = d.tt - 90; return d


def stage1(d: pd.DataFrame) -> pd.DataFrame:
    d = d[(d.ev & (d.tt <= 90)) | (d.tt > 90)].copy(); d['y'] = (d.ev & (d.tt <= 90)).astype(int); return d


class Prep:
    """학습 구간 기준 전처리(중앙값 대치 + 결측 표시, log1p, 원-핫, 표준화)."""

    def __init__(self, num: list[str], scale: bool):
        self.num, self.scale = num, scale

    def _raw(self, d: pd.DataFrame) -> pd.DataFrame:
        f = pd.DataFrame(index=d.index)
        for c in self.num:
            key = c.split('_', 1)[1] if c.startswith(('s1_', 's2_')) else c
            v = d[c].astype(float)
            f[c] = np.log1p(v.clip(lower=0)) if key in LOG else v
        f['month_sin'] = np.sin(2 * np.pi * d.close_month / 12)
        f['month_cos'] = np.cos(2 * np.pi * d.close_month / 12)
        return f

    def fit(self, d: pd.DataFrame):
        f = self._raw(d)
        self.med = f.median()
        self.miss = [c for c in f.columns if f[c].isna().any()]
        self.cats = {c: sorted(d[c].fillna('?').unique()) for c in CAT}
        z = self._tf(d, fit=True)
        self.mu, self.sd = z.mean(), z.std().replace(0, 1)
        return self

    def _tf(self, d, fit=False):
        f = self._raw(d)
        for c in self.miss:
            f[c + '_na'] = f[c].isna().astype(float)
        f = f.fillna(self.med).fillna(0.0)          # 학습 구간 전체 결측 열 방어
        for c in CAT:
            v = d[c].fillna('?')
            for k in self.cats[c][1:]:                      # 첫 범주 = 기준
                f[f'{c}={k}'] = (v == k).astype(float)
        return f

    def transform(self, d: pd.DataFrame) -> pd.DataFrame:
        z = self._tf(d)
        return (z - self.mu) / self.sd if self.scale else z


# ───────────── 기준선 B1 ─────────────
def km(ev, t):
    return kaplan_meier_estimator(np.asarray(ev, bool), np.asarray(t, float))


def km_at(curve, times):
    x, s = curve
    i = np.searchsorted(x, times, side='right') - 1
    return np.where(i >= 0, s[np.clip(i, 0, None)], 1.0)


def b1_surv(tr: pd.DataFrame, te: pd.DataFrame) -> pd.DataFrame:
    allc = km(tr.ev, tr.dur)
    cell = lambda d: d.f_gu.fillna('?') + '|' + d.prev_group
    cur = {c: km(g.ev, g.dur) for c, g in tr.groupby(cell(tr)) if len(g) >= MIN_N}
    grp = {c: km(g.ev, g.dur) for c, g in tr.groupby('prev_group') if len(g) >= MIN_N}
    rows = [km_at(cur.get(c) or grp.get(g) or allc, TIMES) for c, g in zip(cell(te), te.prev_group)]
    return pd.DataFrame(np.array(rows), columns=TIMES, index=te.index)


# ───────────── 2단계 모델 ─────────────
def surv_y(d):
    return Surv.from_arrays(d.ev.to_numpy(), d.dur.to_numpy())


def step_to_matrix(fns) -> np.ndarray:
    return np.vstack([f(np.minimum(TIMES, f.x[-1])) for f in fns])


class M1Cox:
    def __init__(self, alpha): self.alpha = alpha

    def fit(self, Xd, d):
        self.m = CoxPHSurvivalAnalysis(alpha=self.alpha, ties='efron', n_iter=200).fit(Xd.to_numpy(), surv_y(d)); return self

    def surv(self, Xd):
        return step_to_matrix(self.m.predict_survival_function(Xd.to_numpy()))


def person_period(Xd: pd.DataFrame, d: pd.DataFrame):
    k = np.minimum(np.ceil(d.dur.to_numpy() / 30).astype(int), K_MAX).clip(min=1)
    idx = np.repeat(np.arange(len(d)), k)
    per = np.concatenate([np.arange(1, n + 1) for n in k])
    last = np.concatenate([np.arange(1, n + 1) == n for n in k])
    ev = np.repeat(d.ev.to_numpy() & (d.dur.to_numpy() <= K_MAX * 30), k) & last
    return Xd.to_numpy()[idx], per, ev.astype(int)


def per_design(Xm, per, onehot: bool):
    if onehot:
        P = np.zeros((len(per), K_MAX)); P[np.arange(len(per)), per - 1] = 1
        return np.hstack([Xm, P])
    return np.hstack([Xm, per[:, None]])


class M2Discrete:
    def __init__(self, kind, **kw): self.kind, self.kw = kind, kw

    def fit(self, Xd, d):
        Xm, per, y = person_period(Xd, d)
        A = per_design(Xm, per, self.kind == 'logit')
        if self.kind == 'logit':
            self.m = LogisticRegression(C=self.kw['C'], max_iter=3000, fit_intercept=False).fit(A, y)
        else:
            self.m = lgb.LGBMClassifier(num_leaves=self.kw['leaves'], n_estimators=self.kw['trees'], learning_rate=0.05,
                                        min_child_samples=100, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                                        random_state=0, verbose=-1).fit(A, y)
        return self

    def surv(self, Xd):
        n = len(Xd); Xm = Xd.to_numpy()
        haz = np.zeros((n, K_MAX))
        for k in range(1, K_MAX + 1):
            A = per_design(Xm, np.full(n, k), self.kind == 'logit')
            haz[:, k - 1] = self.m.predict_proba(A)[:, 1]
        S = np.cumprod(1 - haz, axis=1)                    # S(30k)
        kk = np.clip(np.floor(TIMES / 30).astype(int), 0, K_MAX)
        S0 = np.hstack([np.ones((n, 1)), S])
        return S0[:, kk]


class M3RSF:
    def __init__(self, leaf, mf): self.leaf, self.mf = leaf, mf

    def fit(self, Xd, d):
        dd = d.copy(); dd['dur'] = np.ceil(dd.dur / 10) * 10
        self.m = RandomSurvivalForest(n_estimators=300, min_samples_leaf=self.leaf, max_features=self.mf, n_jobs=-1,
                                      random_state=0).fit(Xd.to_numpy(np.float32), surv_y(dd))
        return self

    def surv(self, Xd):
        return step_to_matrix(self.m.predict_survival_function(Xd.to_numpy(np.float32)))


class M4Cure:
    """S(t|x) = 1 - u(x) + u(x) exp(-(t/λ(x))^k). u = 언젠가 채워질 확률, λ = exp(x·b), k = exp(c)."""

    def __init__(self, l2): self.l2 = l2

    def _unpack(self, w, p):
        return w[:p], w[p:2 * p], w[2 * p]

    def _nll(self, w, X, t, e):
        p = X.shape[1]; a, b, c = self._unpack(w, p)
        s = X @ a; u = expit(s); k = np.exp(c); lt = np.log(t); xb = X @ b
        q = np.clip(k * (lt - xb), -50, 50); z = np.exp(q); ez = np.exp(-z)
        D = np.clip(1 - u + u * ez, 1e-12, None)
        ll = np.where(e, np.log(np.clip(u, 1e-12, None)) + c - lt + q - z, np.log(D))
        ds = np.where(e, 1 - u, u * (1 - u) * (ez - 1) / D)
        dw = np.where(e, k * (z - 1), u * ez * k * z / D)
        dc = np.where(e, 1 + q * (1 - z), -u * ez * z * q / D)
        reg = np.r_[a[1:], b[1:]]
        f = -ll.sum() + 0.5 * self.l2 * (reg @ reg)
        ga = -(X.T @ ds); gb = -(X.T @ dw); gc = -dc.sum()
        ga[1:] += self.l2 * a[1:]; gb[1:] += self.l2 * b[1:]
        return f, np.r_[ga, gb, gc]

    def fit(self, Xd, d):
        X = np.hstack([np.ones((len(Xd), 1)), Xd.to_numpy()])
        t = np.maximum(d.dur.to_numpy(), 1.0); e = d.ev.to_numpy()
        p = X.shape[1]
        w0 = np.zeros(2 * p + 1); w0[0] = -1.0; w0[p] = np.log(np.median(t[e]) if e.any() else 365.0); w0[-1] = 0.0
        r = minimize(self._nll, w0, args=(X, t, e), jac=True, method='L-BFGS-B', options={'maxiter': 2000})
        self.w, self.ok, self.msg, self.p = r.x, bool(r.success), str(r.message), p
        return self

    def surv(self, Xd):
        X = np.hstack([np.ones((len(Xd), 1)), Xd.to_numpy()])
        a, b, c = self._unpack(self.w, self.p)
        u = expit(X @ a); lam = np.exp(X @ b); k = np.exp(c)
        return (1 - u)[:, None] + u[:, None] * np.exp(-(TIMES[None, :] / lam[:, None]) ** k)

    def susceptible(self, Xd):
        X = np.hstack([np.ones((len(Xd), 1)), Xd.to_numpy()]); return expit(X @ self.w[:self.p])


# ───────────── 지표 ─────────────
def s2_metrics(S: np.ndarray, yv, ytr) -> dict:
    S = np.asarray(S); col = {t: i for i, t in enumerate(TIMES)}
    risk1y = 1 - S[:, col[365]]
    c = concordance_index_ipcw(ytr, yv, risk1y, tau=TAU)[0]
    risk = 1 - S[:, [col[h] for h in H]]
    aucs = [0.5] * 3 if np.ptp(risk, axis=0).max() == 0 else list(cumulative_dynamic_auc(ytr, yv, risk, H)[0])
    t_ok = GRID[GRID < yv['time'].max()]
    ibs = integrated_brier_score(ytr, yv, S[:, [col[t] for t in t_ok]], t_ok)
    return {'c_index': float(c), 'auc_180': float(aucs[0]), 'auc_365': float(aucs[1]), 'auc_730': float(aucs[2]),
            'ibs': float(ibs), 'p_fill_365_mean': float(risk1y.mean())}


def calib_365(S, d) -> list[dict]:
    col = list(TIMES).index(365); p = 1 - np.asarray(S)[:, col]
    q = pd.qcut(p, 10, labels=False, duplicates='drop')
    out = []
    for b in np.unique(q):
        m = q == b
        obs = 1 - km_at(km(d.ev.to_numpy()[m], d.dur.to_numpy()[m]), np.array([365]))[0]
        out.append({'bin': int(b), 'n': int(m.sum()), 'pred': float(p[m].mean()), 'obs_km': float(obs)})
    return out
