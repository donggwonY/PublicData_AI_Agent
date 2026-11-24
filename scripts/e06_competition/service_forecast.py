"""E-06 서비스용 폐업 예측표: 구 × 세부 업종, 기준일 다음 날부터 12개월.

결정 근거: docs/e06/service_backtest.md (C안, 범위는 '과거 점검 적중 약 85%'로 표시).
service_backtest.py 와 같은 방식(models.py 함수 정의 + 날짜 +55일)으로, 연도 ≤ 2026 기간 전체로 G1(λ=0.3)을
학습해 2027 기간(2026-11-07 ~ 2027-11-06)을 예측한다. 사전 점검: 같은 빌드로 2026 기간 MAE 2.7142 재현.
출력: service/data/processed/competition_forecast.parquet (앱은 읽기만), docs/e06/results/service_forecast.json
실행(저장소 루트): C:\\claude_workspace\\e06_env\\Scripts\\python scripts/e06_competition/service_forecast.py
"""
import hashlib, json
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
src = (HERE / 'models.py').read_text(encoding='utf-8')
prefix = src.split('\nres = {')[0]
assert 'LAST_YEAR, FIRST_TARGET = 2022, 2010' in prefix
prefix = prefix.replace('LAST_YEAR, FIRST_TARGET = 2022, 2010', 'LAST_YEAR, FIRST_TARGET = 2027, 2010')
ns = {'__file__': str(HERE / 'models.py'), '__name__': 'e06_models_prefix'}
exec(compile(prefix, 'models.py(함수 정의 부분)', 'exec'), ns)
build, rolling, ppf_counts, mae = (ns[k] for k in ('build', 'rolling', 'ppf_counts', 'mae'))

REF = pd.Timestamp(json.loads((ROOT / 'service/data/processed/meta.json').read_text(encoding='utf-8'))['reference_date'])
SHIFT = pd.Timestamp('2026-12-31') - REF
# 같은 기준일로 돌린 점검(service_backtest.py) 결과가 있어야 한다. 결정 당시 2026-11-06 은 service_backtest.json.
BT = ROOT / ('docs/e06/results/service_backtest.json' if REF == pd.Timestamp('2026-11-06')
             else f'docs/e06/results/service_backtest_{REF.date()}.json')
assert BT.exists(), f'기준일 {REF.date()} 점검 결과가 없다: 먼저 service_backtest.py 실행'
bt = json.loads(BT.read_text(encoding='utf-8'))
assert bt['period_definition'].endswith(f'+{SHIFT.days}일 이동)'), '점검 결과의 기준일이 다르다'
assert bt['input_sha256'] == ns['snapshot_sha256'](ns['SRC']), '점검 때와 입력(stores.parquet)이 다르다'
assert bt['c1_all_years_better'] and bt['c2_ci_upper_below_0'], '점검에서 G1이 기준선보다 낫지 않다 → 반영 중단'
s = ns['s']
s['ld'] = s.ld + SHIFT
s['cd'] = s.cd + SHIFT
s['oy'] = s.ld.dt.year
s['cy'] = np.where(s.closed, s.cd.dt.year, np.nan)

LAM, TARGET, HIT = 0.3, 2027, bt['cov80_poisson']   # 결정 당시 0.852
GUS = ['중구', '동구', '서구', '남구', '북구', '수성구', '달서구', '달성군', '군위군']
T1 = build(['gu'])

# 사전 점검: 2026 기간 예측이 service_backtest.json 과 같아야 한다
pre, _ = rolling(T1, 'closes', [2026], LAM)
W = T1.year == 2026
pre_mae = round(mae(T1.loc[W, 'closes'], pre[W]), 4)
assert pre_mae == bt['by_year']['2026']['G1'], f"사전 점검 실패: {pre_mae} ≠ {bt['by_year']['2026']['G1']}"  # 결정 당시 2.7142
print('사전 점검 통과', pre_mae)

pred, _ = rolling(T1, 'closes', [TARGET], LAM)
F = T1[T1.year == TARGET].copy()
F['closes_pred'] = pred[F.index]
F = F[F.closes_pred.notna()]
dropped = sorted(set(F.gu) - set(GUS))
F = F[F.gu.isin(GUS)].copy()

hist = T1[T1.year.between(TARGET - 3, TARGET - 1)].pivot_table(index=['gu', 'category'], columns='year',
                                                               values=['opens', 'closes'], aggfunc='sum')
hist.columns = [f'{v}_{TARGET - y}y_ago' for v, y in hist.columns]
F = F.merge(hist.reset_index(), on=['gu', 'category'], how='left')

mu = F.closes_pred.values
out = pd.DataFrame({
    'gu': F.gu.values, 'category': F.category.values,
    'period_start': (REF + pd.Timedelta(days=1)).date().isoformat(),
    'period_end': (REF + pd.DateOffset(years=1)).date().isoformat(),
    'closes_pred': np.round(mu, 2),
    'closes_lo': ppf_counts(0.1, mu).astype(int), 'closes_hi': ppf_counts(0.9, mu).astype(int),
    'active_now': F.active_prev.astype(int).values,
    **{f'{v}_{k}y_ago': F[f'{v}_{k}y_ago'].fillna(0).astype(int).values for v in ('closes', 'opens') for k in (1, 2, 3)},
    'range_hit_rate': HIT, 'reference_date': REF.date().isoformat(),
}).sort_values(['gu', 'category']).reset_index(drop=True)

PQ = ROOT / 'service/data/processed/competition_forecast.parquet'
out.to_parquet(PQ, index=False)
summary = {
    'decision': 'docs/e06/service_backtest.md', 'backtest': BT.name, 'input_sha256': ns['snapshot_sha256'](ns['SRC']),
    'precheck_2026_mae': pre_mae, 'model': f'G1 포아송 회귀 λ=0.3, 학습 기간 연도 ≤ 2026 ({REF:%m-%d} 기준 12개월)',
    'period': [out.period_start[0], out.period_end[0]], 'rows': int(len(out)),
    'gu': int(out.gu.nunique()), 'categories': int(out.category.nunique()), 'dropped_gu_values': dropped,
    'closes_pred_sum': round(float(out.closes_pred.sum()), 1),
    'last_period_actual_closes_sum': int(out.closes_1y_ago.sum()),
    'parquet_sha256': hashlib.sha256(PQ.read_bytes()).hexdigest(),
}
(ROOT / 'docs/e06/results/service_forecast.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1) + '\n',
                                                              encoding='utf-8', newline='\n')
print(json.dumps(summary, ensure_ascii=False))
print(out[(out.gu == '수성구') & out.category.isin(['커피숍', '한식', '편의점', '일반미용업'])].to_string())
