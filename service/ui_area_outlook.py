"""상권 둘러보기 › 동네·자리: '1년 뒤 거주 인구'(A-07)와 '비슷한 동네 5곳'(A-09).

- 수치는 core.tools.get_population_outlook·get_similar_areas 가 저장된 표(scripts/area_outlook_export.py)에서 읽는다.
- 카드: 전체 1년 뒤 추정, 최근 1년 가장 많이 들어온·빠져나간 연령대(나이를 한 살씩 밀어 본 순이동, 70대 이상 제외).
  특정 연령대만 따로 카드로 보여 주지 않는다. 표는 모든 연령대에 같은 열(현재·1년 뒤 추정·최근 1년 이사 인원).
  화면 안내는 '주민등록 거주자 기준'만 둔다(docs/a07/cohort_results_c.md '앱 표시 규칙').
"""
import pandas as pd
import streamlit as st

from core import tools as T

BUSINESS = "업종 비중"
AGE = "연령대 비중"
MODES = {"업종·연령 구성": "combined", "상가·거주자 규모": "size", BUSINESS: None, AGE: None}


def _go_to(gu: str, dong: str) -> None:
    """'이 동네 보기': 위쪽 행정동 선택을 그 동네로 바꾼다. 다른 구를 보고 있었다면 구도 함께 바꾼다."""
    cur = st.session_state.get("dash_gu", "대구 전체")
    if cur not in ("대구 전체", gu):
        st.session_state.dash_gu = st.session_state.fav_gu = gu
    st.session_state.dash_dong = dong


def _move_card(col, title: str, top: dict | None, has_data: bool) -> None:
    if top:
        col.metric(title, top["label"], f"최근 1년 {top['net_move']:+,}명", delta_color="off", delta_arrow="off", border=True)
    else:
        col.metric(title, "뚜렷하지 않음" if has_data else "-", border=True)


def render_population_outlook(gu: str, dong: str) -> None:
    res = T.get_population_outlook(gu, dong)
    st.subheader("1년 뒤 거주 인구")
    if not res.get("items"):
        st.info(res["reason"])
        return
    st.caption(f"{res['base_month']} 현재 → {res['target_month']} 추정 · {res['basis']}")
    if not res["available"]:
        st.info(res["reason"])
    total = res["items"][0]
    c1, c2, c3 = st.columns(3)
    if total["change_kind"] == "withheld":
        c1.metric("전체 거주자 (현재)", f"{total['current']:,}명", border=True)
    else:
        c1.metric("전체 1년 뒤 추정", f"{total['forecast']:,}명", f"1년 뒤 {total['change_value']:+,}명",
                  delta_color="off", delta_arrow="off", border=True)
    moved = res.get("move_period") is not None
    _move_card(c2, "많이 들어온 연령대", res.get("top_in"), moved)
    _move_card(c3, "많이 나간 연령대", res.get("top_out"), moved)
    if moved:
        st.caption(f"{res['base_month']} 현재 전체 {total['current']:,}명. 들어온·나간 연령대는 {res['move_period']} "
                   "나이 드는 효과를 빼고 이사로 바뀐 인원(들어온 사람 − 나간 사람)이에요. "
                   "70대 이상은 사망이 섞여 순위에서 뺐어요.")
    with st.expander("연령대별로 모두 보기"):
        df = pd.DataFrame([{"연령대": i["label"], f"{res['base_month']} 현재": f"{i['current']:,}명",
                            f"{res['target_month']} 추정": "-" if i["forecast"] is None else f"{i['forecast']:,}명",
                            "최근 1년 이사로 바뀐 인원": i.get("net_move_text", "-")} for i in res["items"]])
        st.dataframe(df, hide_index=True, width="stretch", height=35 * (len(df) + 1) + 3)
        st.caption("연령대마다 따로 추정해 연령대 합이 전체와 조금 다를 수 있어요. "
                   "0\\~9세의 이사 인원은 올해 태어난 아기를 빼고 1\\~9세만 셌어요.")


def _option_picker(gu: str, dong: str) -> str:
    mode = st.segmented_control("무엇이 비슷한 동네를 찾을까요?", list(MODES), default="업종·연령 구성",
                                key="dash_similar_mode") or "업종·연령 구성"
    if MODES[mode]:
        return MODES[mode]
    sa = T.store().similar_areas
    group = "business" if mode == BUSINESS else "population"
    opts = sa.loc[sa["option_group"] == group, "option"].drop_duplicates().tolist()
    return st.selectbox("항목", opts, format_func=T.similar_option_label, key=f"dash_similar_{group}")


def render_similar_areas(gu: str, dong: str) -> None:
    st.subheader("비슷한 동네 5곳")
    if T.store().similar_areas is None:
        st.info("비슷한 동네 자료가 이 데이터 버전에 없어요.")
        return
    option = _option_picker(gu, dong)
    res = T.get_similar_areas(gu, dong, option)
    if not res["available"]:
        st.info(res["reason"])
        return
    share = res["option_group"] != ""
    if share:
        st.caption(f"{gu} {dong}의 {res['option_label']}: {res['base_share_pct']}%")
    for i in res["items"]:
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 4, 2], vertical_alignment="center")
            c1.markdown(f"**{i['rank']}. {i['gu']} {i['dong']}**")
            facts = [f"상가 {i['shops']:,}곳"]
            if i["residents"] is not None:
                facts.append(f"거주자 {i['residents']:,}명")
            if share:
                facts.append(f"{res['option_label']} {i['option_share_pct']}%")
            pc = i["population_change"]
            facts.append("1년 뒤 인구 추정 보류" if pc is None else f"1년 뒤 전체 {pc:+,}명")
            c2.caption(" · ".join(facts))
            c3.button("이 동네 보기", key=f"dash_similar_go_{option}_{i['rank']}", on_click=_go_to,
                      args=(i["gu"], i["dong"]), width="stretch")
    st.caption(f"추천과 비중은 {res['shops_month']} 소상공인 상가정보·주민등록 거주자, 거주자 수와 1년 뒤 인구는 "
               f"{res['residents_month']} 주민등록 거주자 기준이에요. 구성이 비슷한 순서이며, 창업 성과를 비교한 결과는 아니에요.")
