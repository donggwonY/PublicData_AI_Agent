"""E-10 2단계: 기준선 B1(업종 평균)·B2(업종 × 직전 가게 영업 기간)를 학습 구간으로 만들어 검증 구간에서 비교.

평가 구간(2021~2023 개업)은 읽지 않는다. 결과: docs/e10/results/baseline_valid.json
실행(저장소 루트): C:/claude_workspace/e06_env/Scripts/python scripts/e10_takeover/baseline.py
"""
import json

import numpy as np
import pandas as pd

import common as C


def main():
    d, sha = C.load()
    tr = d[d.split == "train"].copy()
    va = d[d.split == "valid"].copy()
    del d                                   # 평가 구간은 쓰지 않음
    va["B0"] = tr.y.mean()
    va["B1"] = C.b1(tr, va)
    va["B2"] = C.b2(tr, va)
    cols = ["B0", "B1", "B2"]
    y = va.y.values
    tbl = {c: C.metrics(y, va[c].values) for c in cols}
    best = min(("B1", "B2"), key=lambda c: tbl[c]["brier"])

    svc = va.service.where(va.service.isin(["일반음식점", "담배소매업", "휴게음식점", "미용업", "즉석판매제조가공업"]), "그 밖")
    cells = tr.groupby(["service", "p_tenure_band"]).size()
    res = {
        "input_sha256": sha, "n_train": len(tr), "n_valid": len(va),
        "train_rate": round(float(tr.y.mean()), 4), "valid_rate": round(float(va.y.mean()), 4),
        "metrics": tbl, "selected_baseline": best,
        "diff_B2_vs_B1": C.boot_diff(va, "B2", "B1"),
        "calibration": {c: C.calib(y, va[c].values) for c in ("B1", "B2")},
        "by_service": C.by_group(va.assign(svc=svc), "svc", cols[1:]),
        "by_tenure_band": C.by_group(va, "p_tenure_band", cols[1:]),
        "b2_cells": {"total": int(len(cells)), "n_ge_30": int((cells >= C.MIN_N).sum()),
                     "valid_rows_in_full_cells": round(float(np.mean([
                         cells.get((s, b), 0) >= C.MIN_N for s, b in zip(va.service, va.p_tenure_band)])), 3)},
        "train_service_rates": {k: [int(n), round(float(m), 3)] for k, (m, n) in
                                tr.groupby("service").y.agg(["mean", "size"]).sort_values("size", ascending=False).iterrows()},
    }
    C.RES.mkdir(parents=True, exist_ok=True)
    (C.RES / "baseline_valid.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(pd.DataFrame(tbl).T.round(4).to_string())
    print("선택:", best, json.dumps(res["diff_B2_vs_B1"], ensure_ascii=False))
    print(json.dumps(res["by_service"], ensure_ascii=False))
    print(json.dumps(res["by_tenure_band"], ensure_ascii=False))
    print(json.dumps(res["calibration"], ensure_ascii=False))
    print(res["b2_cells"])


if __name__ == "__main__":
    main()
