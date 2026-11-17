"""E-06 서비스용 예측 기간 점검(C안). 계획 docs/e06/service_backtest_plan.md (2026-11-17 고정, 실행 전).

models.py 의 함수 정의 부분(`res = {` 앞까지)을 그대로 실행한 뒤, 개업일·폐업일을 55일 뒤로 밀어
'연도 y = (y−1)-11-07 ~ y-11-06' 으로 바꾸고 같은 G1(λ=0.3)·기준선을 평가한다.
실행(저장소 루트): C:\\claude_workspace\\e06_env\\Scripts\\python scripts/e06_competition/service_backtest.py
"""
import json
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
src = (HERE / 'models.py').read_text(encoding='utf-8')
prefix = src.split('\nres = {')[0]
assert 'LAST_YEAR, FIRST_TARGET = 2022, 2010' in prefix
prefix = prefix.replace('LAST_YEAR, FIRST_TARGET = 2022, 2010', 'LAST_YEAR, FIRST_TARGET = 2026, 2010')
ns = {'__file__': str(HERE / 'models.py'), '__name__': 'e06_models_prefix'}
exec(compile(prefix, 'models.py(함수 정의 부분)', 'exec'), ns)
build, rolling, ppf_counts, mae, boot = (ns[k] for k in ('build', 'rolling', 'ppf_counts', 'mae', 'boot'))

SHIFT = pd.Timedelta(days=55)          # 2026-11-06 + 55일 = 2026-12-31
assert pd.Timestamp('2026-11-06') + SHIFT == pd.Timestamp('2026-12-31')
s = ns['s']
s['ld'] = s.ld + SHIFT
s['cd'] = s.cd + SHIFT
s['oy'] = s.ld.dt.year
s['cy'] = np.where(s.closed, s.cd.dt.year, np.nan)

OUT = ROOT / 'docs/e06/results/service_backtest.json'
EVAL = list(range(2020, 2027))
LAM = 0.3

T1 = build(['gu'])
g1, _ = rolling(T1, 'closes', EVAL, LAM)
bc = {'B1': T1.closes_l1, 'B2': T1.closes_m3, 'B3': T1.closes_m5}
E = T1.year.isin(EVAL)
y = T1.loc[E, 'closes'].values

by_year = {}
for yr in EVAL:
    W = T1.year == yr
    yy, mu = T1.loc[W, 'closes'].values, g1[W].values
    by_year[str(yr)] = {**{n: round(mae(yy, p[W]), 4) for n, p in {'G1': g1, **bc}.items()},
                        'cells': int(W.sum()), 'actual_closes': int(yy.sum()),
                        'cov80_poisson': round(float(np.mean((yy >= ppf_counts(0.1, mu)) & (yy <= ppf_counts(0.9, mu)))), 3)}
c1 = all(by_year[str(yr)]['G1'] < min(by_year[str(yr)][b] for b in bc) for yr in EVAL)
best_b = min(bc, key=lambda b: mae(y, bc[b][E]))
ci = boot(np.abs(y - g1[E].values) - np.abs(y - bc[best_b][E].values),
          (T1.loc[E, 'year'].astype(str) + '|' + T1.loc[E, 'category']).values)
cp = float(np.mean((y >= ppf_counts(0.1, g1[E].values)) & (y <= ppf_counts(0.9, g1[E].values))))
mae_all = {n: round(mae(y, p[E]), 4) for n, p in {'G1': g1, **bc}.items()}

res = {'plan': 'docs/e06/service_backtest_plan.md', 'input_sha256': ns['snapshot_sha256'](ns['SRC']),
       'period_definition': '연도 y = (y-1)-11-07 ~ y-11-06 (날짜 +55일 이동)', 'lambda': LAM,
       'cells': int(E.sum()), 'mae': mae_all, 'best_baseline': best_b,
       'improvement_pct_vs_best': round(100 * (mae_all['G1'] / mae_all[best_b] - 1), 1),
       'by_year': by_year, 'c1_all_years_better': bool(c1),
       'improvement_vs_best_ci95': ci, 'c2_ci_upper_below_0': bool(ci[1] < 0),
       'cov80_poisson': round(cp, 3), 'c3_cov_ok': bool(0.75 <= cp <= 0.85)}
res['pass'] = bool(res['c1_all_years_better'] and res['c2_ci_upper_below_0'] and res['c3_cov_ok'])
OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
print(json.dumps({k: v for k, v in res.items() if k != 'by_year'}, ensure_ascii=False))
for k, v in by_year.items():
    print(k, v)
