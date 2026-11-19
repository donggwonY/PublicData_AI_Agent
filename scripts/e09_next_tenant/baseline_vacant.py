"""E-09 2차 2단계: 기준선 B0·B1·B1L 검증 구간 평가 → docs/e09/results/vacant_baseline_valid.json
실행(저장소 루트에서): cd scripts/e09_next_tenant && C:/claude_workspace/e06_env/Scripts/python baseline_vacant.py
"""
import json

import common as C


def main():
    d, h = C.load("vacant_cases")
    tr, va = d[d.split == "train"], d[d.split == "valid"].reset_index(drop=True)
    preds = {"B0": C.b0(tr, len(va)), "B1": C.b1(tr, va), "B1L": C.b1l(tr, va)}
    yi = va["yi"].values
    res = {"cases_sha256": h, "n_train": len(tr), "n_valid": len(va), "uids_valid": int(va.uid.nunique()),
           "metrics": {k: C.metrics(yi, p) for k, p in preds.items()},
           "by_landmark": {int(L): {"n": int(m.sum()), **{k: C.metrics(yi[m], p[m]) for k, p in preds.items()}}
                           for L in sorted(va.L.unique()) for m in [va.L.values == L]},
           "per_class": {k: C.per_class(yi, p) for k, p in preds.items() if k != "B0"}}
    best = min(("B1", "B1L"), key=lambda k: res["metrics"][k]["logloss"])
    other = "B1" if best == "B1L" else "B1L"
    res["best_baseline"] = best
    res["diff_other_vs_best"] = {**C.boot_diff(va.uid.values, yi, preds[other], preds[best]),
                                 **C.boot_diff_top3(va.uid.values, yi, preds[other], preds[best])}
    C.RES.mkdir(parents=True, exist_ok=True)
    (C.RES / "vacant_baseline_valid.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, m in res["metrics"].items():
        print(k, {a: round(b, 4) for a, b in m.items()})
    for L, t in res["by_landmark"].items():
        print(L, t["n"], {k: (round(t[k]["logloss"], 3), round(t[k]["top3"], 3)) for k in preds})
    print("best", best, {a: (round(b, 4) if not isinstance(b, list) else [round(x, 4) for x in b]) for a, b in res["diff_other_vs_best"].items()})
    for k in ("B1", "B1L"):
        print(k, {c: (v["mean_pred"], v["obs_rate"]) for c, v in res["per_class"][k].items()})


if __name__ == "__main__":
    main()
