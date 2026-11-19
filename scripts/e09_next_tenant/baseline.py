"""E-09 2단계: 기준선 B0~B3 검증 구간 평가 → docs/e09/results/baseline_valid.json
실행(저장소 루트): C:/claude_workspace/e06_env/Scripts/python scripts/e09_next_tenant/baseline.py
"""
import json

import numpy as np

import common as C


def main():
    d, h = C.load()
    tr, va = d[d.split == "train"], d[d.split == "valid"].reset_index(drop=True)
    preds = {"B0": C.b0(tr, len(va)), "B1": C.b1(tr, va), "B2": C.b2(d, tr, va), "B3": C.b3(tr, va)}
    yi = va["yi"].values
    res = {"cases_sha256": h, "n_train": len(tr), "n_valid": len(va),
           "metrics": {k: C.metrics(yi, p) for k, p in preds.items()},
           "by_year": {int(y): {k: C.metrics(yi[m], p[m]) for k, p in preds.items()}
                       for y in sorted(va.close_year.unique()) for m in [va.close_year.values == y]},
           "per_class": {k: C.per_class(yi, p) for k, p in preds.items()}}
    best = min(("B1", "B2", "B3"), key=lambda k: res["metrics"][k]["logloss"])
    res["best_baseline"] = best
    others = [k for k in ("B1", "B2", "B3") if k != best]
    res["diff_vs_best"] = {k: C.boot_diff(va.uid.values, yi, preds[k], preds[best]) for k in others}
    C.RES.mkdir(parents=True, exist_ok=True)
    (C.RES / "baseline_valid.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, m in res["metrics"].items():
        print(k, {a: round(b, 4) for a, b in m.items()})
    for y, t in res["by_year"].items():
        print(y, {k: round(m["logloss"], 4) for k, m in t.items()})
    print("best", best, json.dumps(res["diff_vs_best"], indent=0))
    for k in ("B1", "B2"):
        print(k, {c: (v["mean_pred"], v["obs_rate"], v["recall"]) for c, v in res["per_class"][k].items()})


if __name__ == "__main__":
    main()
