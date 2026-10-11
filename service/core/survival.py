"""Kaplan-Meier 생존분석 (영업 중 점포 = 중도절단).

왜 평균이 아니라 생존분석인가
    "카페는 몇 년 버티나?"를 폐업한 가게의 평균 영업기간으로 답하면 틀린다.
    아직 영업 중인 가게는 "적어도 지금까지는 버텼다"는 정보를 주는데, 평균은 그 정보를 버리기 때문이다.
    영업 중인 가게를 빼면 짧게, 기준일에 폐업한 셈 치면 더 짧게 나온다.

중도절단(censoring)
    사건(폐업)이 아직 일어나지 않은 관측. 이 프로젝트에서는 기준일 현재 영업 중인 점포 38,502건이 해당한다.
    Kaplan-Meier 는 이들을 "그 시점까지는 살아 있었다"로 세고, 그 이후 계산에서만 제외한다.

계산식
    S(t) = Π (1 - 그 시점 폐업 수 / 그 시점 위험집단 크기)
    폐업이 일어난 시점마다 "직전까지 살아 있던 가게 중 몇 %가 폐업했는지"를 곱해 나간다.
"""
from __future__ import annotations

import numpy as np

YEAR = 365.25  # 일수를 연 단위로 바꿀 때 쓰는 값 (윤년 평균)


def kaplan_meier(durations_days, events) -> tuple[np.ndarray, np.ndarray]:
    """고유 사건시점 t 와 S(t) 반환. events: 1=폐업(사건), 0=영업중(중도절단).

    반복문 없이 numpy 배열 연산만 쓴다. 12만 건도 수십 ms 에 끝나기 때문에
    Tool 이 요청을 받을 때마다 즉석에서 계산해도 응답 속도에 지장이 없다.
    """
    d = np.asarray(durations_days, dtype=float)  # 영업 일수
    e = np.asarray(events, dtype=int)            # 1=폐업, 0=영업중
    if d.size == 0:
        return np.array([0.0]), np.array([1.0])  # 표본이 없으면 "생존율 100%" 한 점만

    # 영업 일수 오름차순 정렬. mergesort 는 같은 값의 순서를 유지해(안정 정렬) 결과가 항상 같다.
    order = np.argsort(d, kind="mergesort")
    d, e = d[order], e[order]

    # 같은 일수가 여러 건이면 한 시점으로 묶는다. idx = 각 고유 시점이 시작되는 위치
    times, idx = np.unique(d, return_index=True)
    n = d.size
    at_risk = n - idx                      # 그 시점에 아직 남아 있는 점포 수 (정렬돼 있으므로 뺄셈으로 구해진다)
    deaths = np.add.reduceat(e, idx)       # 그 시점의 폐업 건수 (구간별 합계)
    s = np.cumprod(1.0 - deaths / at_risk)  # 시점별 생존 비율을 누적해서 곱하기

    # 폐업이 0건인 시점(중도절단만 있는 시점)은 S 가 그대로이므로 곡선에서 뺀다.
    keep = deaths > 0
    # 맨 앞에 "0일 → 생존율 1.0" 을 붙여 곡선이 100% 에서 시작하게 한다.
    return np.concatenate([[0.0], times[keep]]), np.concatenate([[1.0], s[keep]])


def survival_at(times: np.ndarray, surv: np.ndarray, t_days: float) -> float:
    """t_days 시점의 생존율. 계단함수이므로 '그 시점 이하의 마지막 값'을 찾는다."""
    i = np.searchsorted(times, t_days, side="right") - 1
    return float(surv[max(i, 0)])


def median_survival(times: np.ndarray, surv: np.ndarray) -> float | None:
    """중앙생존기간 = 생존율이 처음 50% 이하가 되는 시점.

    관측 기간 안에 절반이 폐업하지 않으면 None (추정 불가). 억지로 마지막 값을 돌려주면
    "이 업태는 오래 간다"는 사실이 "중앙생존 10년"이라는 없는 숫자로 둔갑한다.
    """
    below = np.nonzero(surv <= 0.5)[0]
    return float(times[below[0]]) if below.size else None


def summarize(durations_days, events, curve_years: int = 10) -> dict:
    """Tool 반환용 요약 — 근거 수치(n, 폐업, 중도절단)를 반드시 포함.

    생존율만 주면 "표본 3건짜리 92%"와 "표본 1만 건짜리 92%"를 구분할 수 없다.
    AI 가 신뢰도를 함께 말할 수 있도록 표본 수와 폐업/영업중 내역을 항상 같이 돌려준다.
    """
    d = np.asarray(durations_days, dtype=float)
    e = np.asarray(events, dtype=int)
    t, s = kaplan_meier(d, e)
    med = median_survival(t, s)
    max_follow = float(d.max()) if d.size else 0.0  # 이 표본에서 가장 오래 관측된 기간

    def pct(years):
        if max_follow < years * YEAR:  # 관측기간을 넘는 시점은 추정 불가
            return None                # 예: 2024년에 생긴 업태에 "5년 생존율"은 답할 수 없다
        return round(survival_at(t, s, years * YEAR) * 100, 1)

    return {
        "n": int(d.size),                           # 표본 수
        "closed": int(e.sum()),                     # 그중 폐업
        "censored_active": int(d.size - e.sum()),   # 그중 영업 중(중도절단)
        "median_survival_years": round(med / YEAR, 1) if med is not None else None,
        "survival_1y_pct": pct(1),
        "survival_3y_pct": pct(3),
        "survival_5y_pct": pct(5),
        # 차트용 연차별 생존율. 관측되지 않은 연차는 아예 넣지 않는다.
        "curve": [
            {"year": y, "survival_pct": round(survival_at(t, s, y * YEAR) * 100, 1)}
            for y in range(0, curve_years + 1)
            if max_follow >= y * YEAR
        ],
    }
