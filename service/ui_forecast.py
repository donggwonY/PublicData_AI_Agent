"""상권 둘러보기의 '앞으로 1년 폐업 예측' 카드(E-06). 수치는 core.tools.get_competition_outlook 이 저장된 예측표에서 읽어 준다.

AI 상담과 같은 함수·같은 문장을 쓰므로 화면과 답변의 숫자가 어긋나지 않는다.
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import tools as T


def forecast_categories(stores: pd.DataFrame, industry: str) -> list[str]:
    """업종(인허가 종류) 안의 세부 업태 중 예측표에 있는 것. 현재 영업 수가 많은 순."""
    services = ["의원", "병원"] if industry == "의원·병원" else [industry]
    cf = T.store().competition
    if cf is None or not {"service", "category", "closed"} <= set(stores.columns):
        return []
    s = stores[stores["service"].isin(services)]
    cats = s["category"].replace(T.FORECAST_MERGE)
    active = (~s["closed"].astype(bool)).groupby(cats).sum()
    have = set(cf["category"])
    return [c for c in active.sort_values(ascending=False).index if c in have]


def _chart(item: dict, key: str) -> None:
    names = list(item["recent_closes"])
    actual = list(item["recent_closes"].values())
    lo, hi = item["closes_range"]
    p = item["closes_pred"]
    fig = go.Figure()
    fig.add_bar(x=names, y=actual, name="실제 폐업 신고", marker_color="#c2410c", text=actual, textposition="outside")
    fig.add_bar(x=["앞으로 1년(예측)"], y=[p], name="예측", marker_color="rgba(194,65,12,.35)",
                marker_line=dict(color="#c2410c", width=1.5), text=[f"약 {round(p)}"], textposition="outside",
                error_y=dict(type="data", symmetric=False, array=[hi - p], arrayminus=[p - lo], color="#7c2d12"))
    fig.update_layout(height=280, margin=dict(l=0, r=10, t=30, b=10), showlegend=False, bargap=.35,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis_title="곳")
    fig.update_yaxes(gridcolor="rgba(128,128,128,.12)", rangemode="tozero")
    st.plotly_chart(fig, width="stretch", key=key)


def render_closure_forecast(stores: pd.DataFrame, industry: str, gu: str | None) -> None:
    """업종을 고른 상태에서 세부 업태 하나를 골라 앞으로 1년 폐업 예측을 보여 준다."""
    cats = forecast_categories(stores, industry)
    if not cats:
        return
    with st.container(border=True):
        st.markdown("#### 앞으로 1년 폐업 예측")
        cat = st.selectbox("세부 업태", cats, key=f"dash_forecast_cat_{industry}",
                           help="예측은 세부 업태(예: 한식, 커피숍) 단위로 만들었어요.")
        out = T.get_competition_outlook(cat, gu=gu, top_n=9)
        if not out["available"] or not out["items"]:
            st.info(out.get("reason") or (out["notes"][-1] if out["notes"] else "이 조합은 예측이 없습니다."))
            return
        st.caption(f"{out['period']} · 오프라인 예측 모델(포아송 회귀)의 저장값 · 자료 기준일 {out['basis']['reference_date']}")
        if gu:
            it = out["items"][0]
            lo, hi = it["closes_range"]
            p = it["closes_pred"]
            c1, c2, c3 = st.columns(3)
            c1.metric("폐업 예상", "1곳 미만" if p < 1 else f"약 {round(p):,}곳", border=True)
            c2.metric("범위", f"{lo:,}~{hi:,}곳", border=True)
            c3.metric("현재 영업 (인허가)", f"{it['active_now']:,}곳", border=True)
            _chart(it, key=f"dash-forecast-{gu}-{cat}")
        else:
            rows = [{"구·군": i["gu"], "폐업 예상(곳)": round(i["closes_pred"]),
                     "범위": f"{i['closes_range'][0]:,}~{i['closes_range'][1]:,}",
                     "현재 영업(곳)": i["active_now"],
                     "직전 1년 실제 폐업(곳)": list(i["recent_closes"].values())[-1]} for i in out["items"]]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            for n in out["notes"]:
                if "합계" in n:
                    st.caption(n)
        st.caption(f"범위: {out['range_note']}. 영업 중인 가게가 많은 곳은 폐업 수도 많으므로 폐업 수만으로 지역을 고르지 마세요.")
        with st.expander("예측 기준과 한계"):
            st.caption(out["caveat"])
            st.caption("과거 기간은 11월 7일~다음 해 11월 6일 단위입니다. 근거: 과거 7개 기간 점검(직전 3년 평균보다 약 14% 정확).")
