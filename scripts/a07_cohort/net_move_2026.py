"""A-07 최근 1년(2025-10 → 2026-10) 연령대별 이사로 바뀐 인원 (나이를 한 살씩 밀어 비교, 2026-11-18).

- 방법(코호트 잔차): 2026-10에 a세인 인원 - 2025-10에 (a-1)세였던 인원. 한 해 동안 나이 드는 효과를 빼고
  들어온 사람 - 나간 사람(순이동)만 남긴다. 들어온·나간 사람 수를 각각 알 수는 없다.
  0~9세는 1~9세만(올해 태어난 0세는 작년 값이 없음), 100세 이상은 작년 99세와 100세 이상을 더한 값과 비교.
  70대 이상은 사망이 섞여 빠져나간 인원이 커 보인다(화면 순위에서 제외, 표에 '사망 포함').
- 입력: data/raw/a07_cohort/src(10세 구간)·src_1y(1세 단위). cohort_eval.load_single 이 1세 합계를 10세 구간과 맞춰 본다.
- 보류: docs/a07/population_forecast_2027-10_cohort.csv 에서 보류된 곳(최근 12개월 비교 가능한 이력 없음)은 비운다.
- 출력: docs/a07/net_move_2026-10.csv (UTF-8 BOM, LF). 전체(total) 행은 두지 않는다.
실행(저장소 루트): C:\\claude_workspace\\e06_env\\Scripts\\python scripts/a07_cohort/net_move_2026.py
"""
import csv
import hashlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cohort_eval as ce  # noqa: E402

ROOT = ce.ROOT
PREV, CUR = "2025-10", "2026-10"
FORECAST = ROOT / "docs/a07/population_forecast_2027-10_cohort.csv"
OUT = ROOT / "docs/a07/net_move_2026-10.csv"
BANDS = [b for b in ce.BANDS if b != "total"]
DEATHS = {"age_70_79", "age_80_89", "age_90_99", "age_100_plus"}  # 사망이 섞여 순위에서 뺀다


def ages_of(band):
    if band == "age_100_plus":
        return [100]
    lo = int(band[4:6])
    return list(range(max(lo, 1), lo + 10))


def net_move(now, prev, band):
    if band == "age_100_plus":
        return now[100] - prev[99] - prev[100]
    return sum(now[a] for a in ages_of(band)) - sum(prev[a - 1] for a in ages_of(band))


def main():
    months = ce.load_months()
    single = ce.load_single({m: months[m] for m in (PREV, CUR)})
    fc = list(csv.DictReader(FORECAST.open(encoding="utf-8-sig")))
    areas = {r["admin_code"]: (r["admin_area"], r["status"]) for r in fc if r["age_band"] == "total"}
    assert len(areas) == 152
    rows = []
    for code, (name, status) in areas.items():
        ok = status == "available" and code in single[CUR] and code in single[PREV]
        for band in BANDS:
            v = net_move(single[CUR][code], single[PREV][code], band) if ok else ""
            rows.append({"admin_code": code, "admin_area": name, "age_band": band, "from_month": PREV, "to_month": CUR,
                         "net_move_12m": v, "includes_deaths": int(band in DEATHS),
                         "status": "available" if ok else "withheld"})
    # 점검: 10세 구간 표의 단순 증감 = 순이동 + (구간 아래쪽으로 들어온 나이 - 위쪽으로 나간 나이) 로 맞아떨어져야 한다
    for code, (name, status) in areas.items():
        if status != "available":
            continue
        now, prev = single[CUR][code], single[PREV][code]
        for band in BANDS[:-1]:
            lo = int(band[4:6])
            naive = sum(now[a] for a in range(lo, lo + 10)) - sum(prev[a] for a in range(lo, lo + 10))
            aging = (prev[lo - 1] if lo else now[0]) - prev[lo + 9]
            assert naive == net_move(now, prev, band) + aging, (code, band)
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    OUT.write_bytes(("\ufeff" + buf.getvalue()).encode("utf-8"))
    n_ok = sum(r["status"] == "available" for r in rows) // len(BANDS)
    print(f"{OUT.name}: {len(rows):,}행, 계산 {n_ok}곳·보류 {len(areas) - n_ok}곳, sha256 {hashlib.sha256(OUT.read_bytes()).hexdigest()}")
    for name in ("대구광역시 중구 성내1동", "대구광역시 북구 산격3동"):
        print(name, {r["age_band"]: r["net_move_12m"] for r in rows if r["admin_area"] == name})


if __name__ == "__main__":
    main()
