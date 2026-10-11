"""상권 사이클 단계 판정 — 개업/폐업 비율의 시계열 추세.

기존 상권분석 서비스는 "지금 이 동네에 카페가 몇 개인가"라는 현재 스냅샷만 준다.
같은 자리·같은 동네의 개업과 폐업을 시간순으로 세면 점포 수가 늘고 있는지 줄고 있는지가 드러난다.

판정 규칙 (r = 최근 3년 개업/폐업 비율, rp = 직전 3년 같은 비율)
    r >= 1.1  →  개업 우위.  직전이 나빴으면(rp < 0.9) 회복기, 아니면 성장기
    r >= 0.9  →  균형.       성숙기
    r <  0.9  →  폐업 우위.  직전이 괜찮았으면(rp >= 0.9) 쇠퇴 진입기, 아니면 쇠퇴기
경계값 1.1 / 0.9 는 "비율이 1.0 근처에서 조금 흔들리는 것"을 추세로 오해하지 않으려고 둔 여유 구간이다.

이 파일은 데이터프레임도 파일도 건드리지 않는 순수 함수라, 데이터 없이 단위 테스트할 수 있다.
(tests/test_core_units.py 의 ClassifyStageTest 참고)
"""
from __future__ import annotations

import config as C

# 단계 이름 → 사람이 읽을 설명. Tool 이 이 문장을 그대로 반환해 AI 가 근거와 함께 말하게 한다.
STAGE_DESC = {
    "성장기": "개업이 폐업보다 뚜렷하게 많고 이전 기간에도 증가 추세",
    "회복기": "직전 기간엔 폐업 우위였으나 최근 개업 우위로 반전",
    "성숙기": "개업과 폐업이 비슷해 점포 수가 안정적",
    "쇠퇴 진입기": "직전 기간엔 균형 이상이었으나 최근 폐업 우위로 전환",
    "쇠퇴기": "두 기간 연속 폐업이 개업보다 많아 점포 수 감소",
    "판정 보류": "개·폐업 표본이 적어 추세 판단 불가",
}


def classify_stage(open_recent, close_recent, open_prev, close_prev, active_now, active_then) -> dict:
    """개·폐업 건수 6개로 단계를 판정한다.

    인자는 모두 건수다. recent = 최근 3년, prev = 직전 3년,
    active_now / active_then = 기준일 현재와 3년 전의 영업 중 점포 수.
    """
    events = int(open_recent + close_recent)
    # 폐업이 0건이면 나눌 수 없다 → None. 작은 동네에서 실제로 일어난다.
    r = open_recent / close_recent if close_recent else None
    rp = open_prev / close_prev if close_prev else None
    change = (active_now - active_then) / active_then * 100 if active_then else None

    if events < C.CYCLE_MIN_EVENTS or r is None or rp is None:
        # 표본이 적으면 비율이 우연히 크게 흔들린다. 억지로 단계를 붙이지 않고 보류한다.
        stage = "판정 보류"
    elif r >= 1.1:
        stage = "회복기" if rp < 0.9 else "성장기"
    elif r >= 0.9:
        stage = "성숙기"
    else:
        stage = "쇠퇴 진입기" if rp >= 0.9 else "쇠퇴기"

    # 단계 이름만 주면 AI 가 근거를 말할 수 없으므로 판정에 쓴 비율과 점포 수 증감을 함께 돌려준다.
    return {
        "stage": stage,
        "stage_desc": STAGE_DESC[stage],
        "open_close_ratio_recent": round(r, 2) if r is not None else None,
        "open_close_ratio_prev": round(rp, 2) if rp is not None else None,
        "active_change_pct": round(change, 1) if change is not None else None,
    }
