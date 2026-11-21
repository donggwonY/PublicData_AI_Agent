"""손익분기 계산기 (2026-11-21 추가).

사용자가 넣은 가정값으로 '본전이 되려면 하루 몇 건을 팔아야 하는지'를 산수로만 계산한다.
매출을 예측하지 않는다. 세금(부가세·소득세)·감가상각·대출 원금 상환은 넣지 않는다.

용어
- 결제 1건 금액: 손님 한 번 결제의 평균 금액(원)
- 변동비율: 재료비 등 원가율 + 카드·배달 수수료율. 팔 때마다 비례해 나가는 돈
- 월 고정비: 월세·관리비 + 인건비 + 기타 고정비 (+ 내가 가져갈 목표 월 소득)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

SCENARIO_STEP = 0.2   # 보수 −20% / 기준 / 낙관 +20%


class BreakevenError(ValueError):
    """입력값이 계산할 수 없는 조합일 때. 메시지는 사용자에게 그대로 보여 준다."""


@dataclass(frozen=True)
class Inputs:
    ticket: float                 # 결제 1건 평균 금액(원)
    cost_rate_pct: float          # 원가율(%)
    fee_rate_pct: float           # 카드·배달 수수료율(%)
    rent: float                   # 월세 + 관리비(원/월)
    labor: float                  # 직원 인건비(원/월)
    other_fixed: float            # 기타 고정비: 공과금·통신·소모품 등(원/월)
    days: int                     # 월 영업일
    owner_pay: float = 0.0        # 내가 가져갈 목표 월 소득(원/월). 0이면 순수 본전
    expected_daily: float | None = None   # 예상 하루 결제 건수(선택)
    investment: float = 0.0       # 초기 투자비: 보증금 제외 인테리어·설비·권리금 등(원)


def _check(i: Inputs) -> None:
    if i.ticket <= 0:
        raise BreakevenError("결제 1건 금액은 0원보다 커야 해요.")
    if not 1 <= i.days <= 31:
        raise BreakevenError("월 영업일은 1~31일 사이로 넣어 주세요.")
    for name, v in [("원가율", i.cost_rate_pct), ("수수료율", i.fee_rate_pct)]:
        if not 0 <= v < 100:
            raise BreakevenError(f"{name}은 0% 이상 100% 미만이어야 해요.")
    if i.cost_rate_pct + i.fee_rate_pct >= 100:
        raise BreakevenError("원가율과 수수료율을 더하면 100% 이상이라, 팔수록 손해가 나서 본전 지점이 없어요.")
    for name, v in [("월세·관리비", i.rent), ("인건비", i.labor), ("기타 고정비", i.other_fixed),
                    ("목표 월 소득", i.owner_pay), ("초기 투자비", i.investment)]:
        if v < 0:
            raise BreakevenError(f"{name}은 0원 이상이어야 해요.")
    if i.expected_daily is not None and i.expected_daily < 0:
        raise BreakevenError("예상 하루 결제 건수는 0건 이상이어야 해요.")


def monthly_profit(i: Inputs, daily: float) -> float:
    """하루 daily 건을 팔 때 월 영업이익(목표 월 소득은 비용에 넣지 않은 값)."""
    sales = i.ticket * daily * i.days
    return sales * (1 - (i.cost_rate_pct + i.fee_rate_pct) / 100) - (i.rent + i.labor + i.other_fixed)


def calculate(i: Inputs) -> dict:
    """본전 하루 건수·목표 소득 하루 건수, 예상 건수를 넣었으면 세 시나리오와 투자 회수 개월."""
    _check(i)
    margin = i.ticket * (1 - (i.cost_rate_pct + i.fee_rate_pct) / 100)   # 1건 팔면 남는 돈
    fixed = i.rent + i.labor + i.other_fixed

    def need(total_fixed: float) -> dict:
        month = math.ceil(total_fixed / margin) if total_fixed > 0 else 0
        return {"monthly_orders": month, "daily_orders": math.ceil(month / i.days) if month else 0,
                "monthly_sales": month * i.ticket}

    out = {
        "margin_per_order": round(margin),
        "variable_rate_pct": round(i.cost_rate_pct + i.fee_rate_pct, 1),
        "monthly_fixed": round(fixed),
        "breakeven": need(fixed),
        "target": need(fixed + i.owner_pay) if i.owner_pay > 0 else None,
        "scenarios": None,
    }
    if i.expected_daily is not None:
        rows = []
        for name, k in [("보수", 1 - SCENARIO_STEP), ("기준", 1.0), ("낙관", 1 + SCENARIO_STEP)]:
            daily = i.expected_daily * k
            profit = monthly_profit(i, daily)
            left = profit - i.owner_pay
            rows.append({
                "name": name, "daily_orders": round(daily, 1),
                "monthly_sales": round(i.ticket * daily * i.days),
                "monthly_profit": round(profit),
                "after_owner_pay": round(left) if i.owner_pay > 0 else None,
                # 투자 회수: 목표 소득을 가져간 뒤 남는 돈으로 초기 투자비를 메우는 개월 수
                "payback_months": (math.ceil(i.investment / left) if i.investment > 0 and left > 0 else None),
            })
        out["scenarios"] = rows
    return out
