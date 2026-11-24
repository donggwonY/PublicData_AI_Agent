"""E-09 5단계: 현재 빈 자리의 '다음 가게가 들어온다면' 업종 확률 점수표(로컬 배치, DB·앱 반영 없음).

설계: docs/e09/serve_design.md. E-03 재입점 점수와 같은 후보(공백 90일~3년 단일 점포 자리 4,536곳)·기준일(2026-11-06).
- 학습: E-03 2026 사례 표(2012~2026 폐업)에서 랜드마크 90~1,095일, 예측 시점 ≤ 기준일 − 730일(2년 창이 끝난 것)만.
  선택된 2차 설정(vacant_selection.json: M2 LightGBM)으로 전체 재학습. 비교선 B1(직전 묶음 이동표)도 같은 표본으로.
- 점수: 후보별 예측 시점 = 기준일, 공백 일수 = 실제 값. 변수는 build_vacant 와 같은 함수로 기준일 직전 달 말 기준.
- 점검: 평가받은 모델(학습+검증 2019~2021 랜드마크까지 학습)과 재학습 모델의 점수 차이.
입력(저장소 밖): C:/claude_workspace/e05_data/{input, aux, serve/asof_episodes_2026.parquet, serve/step1_candidate_links.parquet}
출력(저장소 밖): C:/claude_workspace/e09_data/serve/next_tenant_scores_<기준일>.parquet, 요약 docs/e09/results/serve_scores.json
실행(scripts/e09_next_tenant 에서): C:/claude_workspace/e06_env/Scripts/python serve_scores.py
"""
import hashlib
import json
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import build_vacant as BV
import common as C
import model as M

E05 = BV.E05
# 이웃·동네 변수와 기준일을 만드는 인허가 표. 기본은 실험 고정 빌드(기준일 2026-11-06).
# 새 원본으로 점수를 다시 낼 때는 E09_INPUT=service/data/processed (2026-11-24, 기준일 2026-11-22)
INPUT = Path(os.environ.get("E09_INPUT", E05 / "input"))
SERVE_EP = E05 / "serve/asof_episodes_2026.parquet"
CAND = E05 / "serve/step1_candidate_links.parquet"
OUT = C.DATA / "serve"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def features(d, P, occ, sub, pop, lmap):
    at = d["at"]
    feats = [BV.A.neighbor_features(d, P, at, "s1_"), BV.A.dong_features(d, P, occ, at, "s1_"),
             BV.E.subway_features(d, sub, at, "s1_"), BV.E.population_features(d, pop, lmap, at, "s1_"),
             BV.added_features(d, P, occ)]
    return pd.concat([d] + feats, axis=1), [c for f in feats for c in f.columns]


def main():
    sel = json.loads((C.RES / "vacant_selection.json").read_text(encoding="utf-8"))
    meta_in = json.loads((INPUT / "meta.json").read_text(encoding="utf-8"))
    ref = pd.Timestamp(meta_in["reference_date"])
    ep = pd.read_parquet(SERVE_EP)
    ep = ep[~ep.censor_bulk_registration].reset_index(drop=True)
    ep = ep.drop(columns=[c for c in ep.columns if c.startswith(("s1_", "s2_"))])

    stores = pd.read_parquet(INPUT / "stores.parquet")
    stores = stores[stores.uid.notna()]                     # 번지 가림(E-12, uid 없음)은 자리가 없어 제외, E-03 step1 과 같게
    units = pd.read_parquet(INPUT / "units.parquet", columns=["uid", "lat", "lon"])
    occ = BV.A.load_occupants(stores, units)
    P = BV.A.Panels(occ, ref)
    sub = BV.E.load_subway(str(BV.AUX / "subway/subway_monthly.csv"), str(BV.AUX / "station/daegu_station_location.xlsx"))
    pop = BV.E.load_population(str(BV.AUX / "population"))
    lmap = pd.read_parquet(E05 / "input/legal_admin_map.parquet")   # 인구 변수용 법정동 대응표는 학습 때와 같은 고정본(E-03 step2 와 같게)

    # 학습 표본: 2년 창이 기준일 안에 끝나는 랜드마크
    BV.LAST_LANDMARK = ref - pd.Timedelta(days=BV.WINDOW)
    tr = BV.landmark_rows(ep)
    tr, _ = features(tr, P, occ, sub, pop, lmap)
    tr["yi"] = tr["y"].map(C.CLASSES.index)

    # 점수 대상: 현재 후보(마지막 가게 = 아직 안 채워진 사례), 예측 시점 = 기준일
    cand = pd.read_parquet(CAND)
    cand = cand[cand.link == "ok"]
    sc = ep.set_index("occupant_id").loc[cand.occupant_id].reset_index()
    assert (~sc.event).all(), "후보 사례에 다음 가게가 있음"
    sc["at"] = ref
    sc["L"] = cand["vacant_days"].astype(int).values
    sc["vacant_days"] = sc["L"]
    sc["prev7"] = sc.group.map(BV.to7)
    sc["next_ld"] = ref + pd.Timedelta(days=60)          # added_features 의 assert 용(다음 가게 없음 = 조회 달 뒤)
    sc, feat_cols = features(sc, P, occ, sub, pop, lmap)

    feats = sel["features"]
    p_new = M.fit_predict(sel["model"], sel["params"], tr, sc, feats)
    p_b1 = C.b1(tr, sc)
    # 평가받은 모델(학습+검증 표본)로도 점수를 내 비교
    d_eval, _ = C.load("vacant_cases")
    p_eval = M.fit_predict(sel["model"], sel["params"], d_eval[d_eval.split.isin(["train", "valid"])], sc, feats)

    gen = date.today().isoformat()
    batch = f"{gen}|E09-vacant-{sel['model']}-lm_to_{BV.LAST_LANDMARK.date()}-ref{ref.date()}"
    out = pd.DataFrame({"uid": sc.uid, "occupant_id": sc.occupant_id, "vacant_days": sc.vacant_days,
                        "prev_group": sc.group, "prev_group7": sc.prev7})
    for k, c in enumerate(C.KEYS):
        out[f"p_{c}"] = p_new[:, k].round(5)
    for k, c in enumerate(C.KEYS):
        out[f"typical_{c}"] = p_b1[:, k].round(5)
    top = np.argsort(-p_new, 1)
    for r in range(3):
        out[f"top{r + 1}"] = [C.CLASSES[i] for i in top[:, r]]
        out[f"top{r + 1}_p"] = p_new[np.arange(len(sc)), top[:, r]].round(5)
    out["data_reference_date"] = str(ref.date())
    out["generated"] = gen
    out["model_version"] = batch
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"next_tenant_scores_{ref.date()}.parquet"
    out.to_parquet(path, index=False)

    t1_new, t1_eval = p_new.argmax(1), p_eval.argmax(1)
    band = pd.cut(sc.vacant_days, [89, 180, 365, 730, 1095], labels=["90~180일", "180일~1년", "1~2년", "2~3년"])
    res = {
        "batch_id": batch, "file_sha256": sha(path), "rows": len(out), "uids": int(out.uid.nunique()),
        "train_rows": len(tr), "train_uids": int(tr.uid.nunique()), "train_last_landmark": str(BV.LAST_LANDMARK.date()),
        "train_by_landmark": {int(k): int(v) for k, v in tr.L.value_counts().sort_index().items()},
        "train_class_share": {c: round(float((tr.yi == k).mean()), 4) for k, c in enumerate(C.CLASSES)},
        "inputs_sha256": {"asof_episodes_2026": sha(SERVE_EP), "candidate_links": sha(CAND),
                          "stores": sha(INPUT / "stores.parquet"), "units": sha(INPUT / "units.parquet")},
        "input_dir": str(INPUT), "data_reference_date": str(ref.date()),
        "score_mean": {c: round(float(p_new[:, k].mean()), 4) for k, c in enumerate(C.CLASSES)},
        "typical_mean": {c: round(float(p_b1[:, k].mean()), 4) for k, c in enumerate(C.CLASSES)},
        "top1_counts": {c: int((t1_new == k).sum()) for k, c in enumerate(C.CLASSES)},
        "top1_p_quantiles": {q: round(float(np.quantile(p_new.max(1), q)), 3) for q in (0.1, 0.5, 0.9)},
        "by_band_top1_counts": {str(b): {c: int(((band == b).values & (t1_new == k)).sum()) for k, c in enumerate(C.CLASSES)}
                                for b in band.cat.categories},
        "vs_evaluated_model": {"top1_agree": round(float((t1_new == t1_eval).mean()), 4),
                               "mean_abs_diff": round(float(np.abs(p_new - p_eval).mean()), 4),
                               "max_abs_diff": round(float(np.abs(p_new - p_eval).max()), 4)},
        "missing_rate_candidates": {c: round(float(sc[c].isna().mean()), 4) for c in feat_cols if sc[c].isna().any()},
    }
    C.RES.mkdir(parents=True, exist_ok=True)
    (C.RES / "serve_scores.json").write_bytes(json.dumps(res, ensure_ascii=False, indent=1).encode("utf-8"))
    print(json.dumps({k: v for k, v in res.items() if k not in ("inputs_sha256",)}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
