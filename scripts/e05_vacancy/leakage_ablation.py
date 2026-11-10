"""누수 비교 보조: 자리 이력만 / 주변 상황만 최종 기록으로 바꾼 M1(평가 구간)."""
import json, os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as E5P
os.chdir(E5P.VF)
import mlib as L
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'leakage_compare.py'), encoding='utf-8').read().split("NUM = L.numeric_cols")[0]
exec(compile(src, 'leak_build', 'exec'))
hist = ['h_n_occ', 'h_n_closed', 'h_n_turnover', 'h_mean_gap_days', 'h_years_since_first', 'h_n_groups']
ctx = [c for c in Xb.columns if c.startswith('s2_')]
NUM = L.numeric_cols('s2') + ['s2_' + c for c in SGC]
out = {}
for name, cols in (('history_only_final', hist), ('context_only_final', ctx)):
    Xm = Xa.copy(); Xm[cols] = Xb[cols].to_numpy()
    dtr = L.stage2(L.split(Xm, (2016, 2021), '2023-12-31')); dte = L.stage2(L.split(Xm, (2022, 2023), '2026-11-06'))
    pr = L.Prep(NUM, True).fit(dtr); m = L.M1Cox(alpha=0.1).fit(pr.transform(dtr), dtr)
    out[name] = L.s2_metrics(m.surv(pr.transform(dte)), L.surv_y(dte), L.surv_y(dtr))['c_index']
r = json.load(open('leakage_compare.json', encoding='utf-8')); r['test_ablation_M1'] = out
json.dump(r, open('leakage_compare.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
print(out)
