"""자리 이력 조회의 공실 재입점 카드(E-03). 점수는 core.tools.vacancy_outlook 이 저장된 값을 읽어 준다.

배치(docs/e03/vacancy_mockup 3판·level_compare.md): ① 1년 확률 → ② 대구 전체 기준 5단계(같은 확률에서 나옴) → ③ 같은 공백 기간대 평균과 비교(맥락).
"""
from __future__ import annotations

import streamlit as st

from core.tools import COMPARE_TEXT, pct_text, per100_text  # noqa: F401  카드와 AI 답변이 같은 문구를 쓰도록 공유


def level_dots(level: int) -> str:
    return "●" * level + "○" * (5 - level)


def _ym(d) -> str:
    return str(d)[:7] if d not in (None, "영업중") else "영업 중"


def unit_summary(h: dict, whole_building: bool = False) -> dict:
    """자리 이력 맨 위 '지금 상태' 요약(제목·설명·점수 미제공 사유). 화면과 테스트가 같은 값을 쓴다."""
    u, tl = h["unit"], h.get("timeline") or []
    last = max(tl, key=lambda r: str(r["open"])) if tl else None
    def store_line(r):
        years = f", 약 {r['years']}년" if r.get("years") is not None else ""
        # 물결표(~)는 마크다운 취소선으로 해석되므로 기간 구분은 '–'
        return f"{r['name']} ({r['service']} · {r['category']} · {_ym(r['open'])}–{_ym(r['close'])}{years})"
    if whole_building:
        active = [r for r in tl if r["close"] == "영업중"]
        return {"title": f"건물 전체: 영업 중 {len(active)}곳 · 기록 {len(tl)}건",
                "detail": ("영업 중: " + " / ".join(store_line(r) for r in active[-3:])) if active else "영업 중인 기록 없음",
                "no_score_reason": "건물 전체 보기에서는 재입점 점수를 보여 주지 않아요. 층을 지정해 조회해 보세요."}
    if not u.get("vacant", False):
        active = [r for r in tl if r["close"] == "영업중"]
        title = f"현재 영업 중 {u.get('n_active', len(active))}곳"
        detail = ("영업 중: " + " / ".join(store_line(r) for r in active[-3:])) if active else ""
        return {"title": title, "detail": detail, "no_score_reason": None}
    days = u.get("vacant_days")
    title = f"인허가 공백 {days:,}일째" if days is not None else "인허가 공백"
    detail = ("마지막 가게: " + store_line(last)) if last else ""
    reason = None
    if not h.get("vacancy_outlook"):
        if whole_building:
            reason = "건물 전체 보기에서는 재입점 점수를 보여 주지 않아요. 층을 지정해 조회해 보세요."
        elif not u.get("is_single_unit", True):
            reason = "여러 가게가 동시에 있던 자리라 재입점 점수를 내지 않아요."
        elif days is not None and days < 90:
            reason = "폐업 후 90일이 지나지 않아 아직 재입점 점수를 내지 않아요(양도·늦은 신고 가능)."
        elif days is not None and days > 1095:
            reason = "3년 넘게 비어 있어 다른 용도로 바뀌었을 가능성이 커 재입점 점수를 내지 않아요."
        else:
            reason = "이 자리는 재입점 점수가 없어요."
    return {"title": title, "detail": detail, "no_score_reason": reason}


# 자리 이력 상세 표의 한글 열 이름(2026-11-14). 데이터 키는 그대로 두고 화면에서만 바꾼다.
BY_CATEGORY_COLS = {"category": "업태", "stores": "가게 수", "closed": "폐업 수", "avg_years": "평균 영업기간(년)",
                    "max_years": "최장 영업기간(년)", "daegu_median_years_2010plus": "대구 중앙생존기간(년, 2010년 이후 개업)"}
TIMELINE_COLS = {"open": "개업일", "close": "폐업일", "name": "상호", "service": "업종", "category": "업태", "floor": "층",
                 "years": "영업기간(년)", "gap_from_previous_close_days": "직전 폐업 후 공백(일)",
                 "short_event": "단기 행사 등록"}
CANDIDATE_COLS = {"address": "주소", "floor": "층", "records": "인허가 기록 수", "status": "상태"}


def korean_table(rows: list[dict], names: dict) -> "pd.DataFrame":
    """표시할 열만 순서대로 골라 한글 이름으로 바꾼다. 날짜는 연-월-일만 남긴다."""
    import pandas as pd
    df = pd.DataFrame(rows)
    df = df[[c for c in names if c in df.columns]].rename(columns=names)
    for c in ("개업일", "폐업일"):
        if c in df.columns:
            df[c] = df[c].astype(str).str.slice(0, 10).replace({"영업중": "영업 중"})
    if "직전 폐업 후 공백(일)" in df.columns:   # 첫 가게는 직전 폐업이 없어 비어 있다 → None 대신 '-'
        df["직전 폐업 후 공백(일)"] = df["직전 폐업 후 공백(일)"].map(lambda x: "-" if pd.isna(x) else f"{int(x):,}")
    for c in df.columns:                       # 글자 칸의 빈 값(층 미상 등)도 None/NaN 대신 '-'
        if not (pd.api.types.is_numeric_dtype(df[c]) or pd.api.types.is_bool_dtype(df[c])):
            df[c] = df[c].astype(object).where(df[c].notna(), "-")
    return df


def render_unit_summary(h: dict, whole_building: bool = False) -> None:
    s = unit_summary(h, whole_building)
    with st.container(border=True):
        st.caption("지금 상태")
        st.markdown(f"### {s['title']}")
        if s["detail"]:
            st.markdown(s["detail"])
        if s["no_score_reason"]:
            st.caption(s["no_score_reason"])


def render_vacancy_outlook(v: dict | None) -> None:
    if not v:
        return
    st.markdown("**앞으로 1년 안에 점포형 가게가 다시 들어올 가능성**")
    c = st.columns(3)
    # 세 카드를 같은 줄의 가장 높은 카드에 맞춰 같은 높이로(2026-11-14)
    with c[0].container(border=True, height="stretch"):
        st.caption("① 1년 안 재입점 가능성")
        st.markdown(f"### {pct_text(v['p_fill_1y'])}")
        st.caption(f"{per100_text(v['p_fill_1y'])}꼴 · 이미 {v['vacant_days']:,}일 비어 있던 점 반영")
    with c[1].container(border=True, height="stretch"):
        st.caption("② 대구 공실 후보 전체 기준")
        st.markdown(f"### {v['level_name']}")
        st.markdown(f"{level_dots(v['level'])} &nbsp; <small>5단계 중 {v['level']}단계</small>", unsafe_allow_html=True)
        obs = round(v["level_observed_1y"] * 100)
        st.caption(f"과거 이 수준 자리의 실제 1년 재입점 약 {obs}%"
                   + (f" · 그래도 100곳 중 약 {100 - obs}곳은 1년 안에 채워지지 않았어요" if v["level"] >= 4 else ""))
    with c[2].container(border=True, height="stretch"):
        st.caption(f"③ 같은 기간({v['vacant_band']}) 빈 자리와 비교")
        st.markdown(f"### {COMPARE_TEXT.get(v['compare_to_band'], '-')}")
        if v.get("band_avg_p_fill_1y") is not None:
            st.caption(f"같은 기간 빈 자리 평균 {pct_text(v['band_avg_p_fill_1y'])}")
    if v["thin_evidence"]:
        st.caption("⚠️ 2년 넘게 빈 자리는 평가 사례가 적어 참고용입니다.")
    with st.expander("이 점수는 무엇인가요? (정의 · 근거 · 한계)"):
        st.markdown(
            f"- **정의**: {v['definition']}\n"
            "- **근거**: 2022–23년 폐업 사례 평가에서 자리 순서 맞힘 0.68(기존 구×업종 평균 0.58). 180일·1년·2년째 빈 자리에서도 "
            "기존 방식보다 나았고, 과거 5개 시점 재현에서 평균 예측 5.0–5.3% vs 실제 4.4–5.4%.\n"
            f"- **한계**: {v['caveat']} 공백 기간 중 주변 변화는 반영하지 않습니다(폐업 후 90일 시점 정보).\n"
            f"- **기준**: 데이터 기준일 {v['reference_date']} · 점수 생성 {v['generated']} · 모델 {v['model_version']}\n"
            "- 공실은 인허가 기준이라 실제 빈 점포와 다를 수 있습니다. 임대 가능 여부나 입지 추천을 뜻하지 않습니다.")
