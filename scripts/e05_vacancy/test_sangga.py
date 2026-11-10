"""상가정보 누수 테스트: 예측 시점 이후에 공개되는 분기를 지운 자료로 다시 계산해도 변수가 같아야 한다.
기준 분기 3개(2017-06, 2019-12, 2021-09): 예측 시점이 '그 분기 공개일 ~ 다음 분기 공개일 전'인 사례를 고르고,
그 분기까지만 남긴 자료로 SG 를 새로 만들어 비교. '새로 나타난 점포'는 직전 분기만 쓰므로 그대로 성립해야 한다."""
import json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as E5P
import sangga as G

VF = E5P.VF
d = pd.read_parquet(os.path.join(VF, 'sangga_quarters.parquet'))
X = pd.read_parquet(os.path.join(VF, 'asof_episodes.parquet'))
F = pd.read_parquet(os.path.join(VF, 'sangga_features.parquet'))
full = G.SG(d)
res = {}
for qend in ['2017-06-30', '2019-12-31', '2021-09-30']:
    q = pd.Timestamp(qend); i = full.qs.index(q)
    lo, hi = q + G.AVAIL_LAG, (full.qs[i + 1] + G.AVAIL_LAG)
    at = X.t0 + pd.Timedelta(days=90)
    sel = (at >= lo) & (at < hi)
    sub = G.SG(d[d.q <= q].copy())
    got = sub.features(X[sel], at[sel], 's2_')
    exp = F.loc[sel.to_numpy(), got.columns]
    a = np.nan_to_num(got.to_numpy(float), nan=-999); b = np.nan_to_num(exp.to_numpy(float), nan=-999)
    res[qend] = {'n': int(sel.sum()), 'mismatch': int((~np.isclose(a, b)).any(axis=1).sum())}
ok = all(v['mismatch'] == 0 for v in res.values()) and all(v['n'] > 0 for v in res.values())
res['PASS'] = ok
print(json.dumps(res, ensure_ascii=False, indent=1))
json.dump(res, open(os.path.join(VF, 'test_sangga_result.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
sys.exit(0 if ok else 1)
