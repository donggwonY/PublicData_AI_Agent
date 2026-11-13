"""자리 이력 조회의 공실 재입점 카드(E-03). 점수는 core.tools.vacancy_outlook 이 저장된 값을 읽어 준다.

배치(docs/e03/vacancy_mockup 3판·level_compare.md): ① 1년 확률 → ② 대구 전체 기준 5단계(같은 확률에서 나옴) → ③ 같은 공백 기간대 평균과 비교(맥락).
"""
from __future__ import annotations

import streamlit as st

from core.tools import COMPARE_TEXT, pct_text, per100_text  # noqa: F401  카드와 AI 답변이 같은 문구를 쓰도록 공유


def level_dots(level: int) -> str:
    return "●" * level + "○" * (5 - level)


def render_vacancy_outlook(v: dict | None) -> None:
    if not v:
        return
    st.markdown("**앞으로 1년 안에 점포형 가게가 다시 들어올 가능성**")
    c = st.columns(3)
    with c[0].container(border=True):
        st.caption("① 1년 안 재입점 가능성")
        st.markdown(f"### {pct_text(v['p_fill_1y'])}")
        st.caption(f"{per100_text(v['p_fill_1y'])}꼴 · 이미 {v['vacant_days']:,}일 비어 있던 점 반영")
    with c[1].container(border=True):
        st.caption("② 대구 공실 후보 전체 기준")
        st.markdown(f"### {v['level']}단계")
        st.markdown(f"{level_dots(v['level'])} &nbsp; <small>5단계 중 · 낮음 → 높음</small>", unsafe_allow_html=True)
        st.caption(f"과거 이 수준 자리의 실제 1년 재입점 약 {round(v['level_observed_1y'] * 100)}%")
    with c[2].container(border=True):
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
            "기존 방식보다 나았고, 과거 5개 시점 재현에서 평균 예측 5.0~5.3% vs 실제 4.4~5.4%.\n"
            f"- **한계**: {v['caveat']} 공백 기간 중 주변 변화는 반영하지 않습니다(폐업 후 90일 시점 정보).\n"
            f"- **기준**: 데이터 기준일 {v['reference_date']} · 점수 생성 {v['generated']} · 모델 {v['model_version']}\n"
            "- 공실은 인허가 기준이라 실제 빈 점포와 다를 수 있습니다. 임대 가능 여부나 입지 추천을 뜻하지 않습니다.")
