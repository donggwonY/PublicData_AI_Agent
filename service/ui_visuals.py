"""Tool 결과 → Streamlit 시각화.

핵심은 맨 아래 render_tool_result 다. Tool 이름을 보고 그 결과 JSON 에 맞는 그림을 고른다.
대시보드 탭과 AI 상담 탭이 같은 함수를 쓰기 때문에, AI 가 Tool 을 부르면
대시보드에서 보던 것과 똑같은 차트가 대화 안에 나타난다.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

from core.tools import store


HOVER_LABELS = {
    "last_store": "직전 상호", "last_category": "직전 업태", "vacant_days": "공백일수",
    "closures_since_2010": "2010~ 폐업", "closures": "폐업 횟수", "avg_years_per_store": "점포당 평균(년)", "now": "현재",
}


def _map(rows: list[dict], color: str, hover: list[str], key: str):
    """pydeck 산점도 지도. color 컬럼 값이 클수록 진한 빨강."""
    df = pd.DataFrame(rows).dropna(subset=["lat", "lon"])  # 좌표 없는 행(약 4%)은 지도에 못 찍는다
    if df.empty:
        st.caption("좌표가 있는 결과가 없습니다.")
        return
    v = pd.to_numeric(df[color], errors="coerce") if color in df else pd.Series(0, index=df.index)
    t = ((v - v.min()) / (v.max() - v.min() or 1)).fillna(0)  # 0~1로 정규화 (or 1 은 0으로 나누기 방지)
    df["_r"], df["_g"], df["_b"] = 255, (170 - t * 150).astype(int), (60 - t * 50).astype(int)
    layer = pdk.Layer("ScatterplotLayer", data=df, get_position="[lon, lat]", get_fill_color="[_r, _g, _b, 200]",
                      get_radius=35, radius_min_pixels=4, radius_max_pixels=14, pickable=True)
    tip = "<b>{address}</b><br/>" + "<br/>".join(f"{HOVER_LABELS.get(c, c)}: {{{c}}}" for c in hover if c in df)
    view = pdk.ViewState(latitude=float(df["lat"].mean()), longitude=float(df["lon"].mean()),
                         zoom=11 if len(df) > 1 else 15)
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, tooltip={"html": tip}, map_style="light"),
                    height=420, key=key)
    st.caption(f"점 {len(df)}개 · 색이 진할수록 '{HOVER_LABELS.get(color, color)}' 값이 큼")


def survival_chart(out: dict, key: str):
    if "ranking_by_median_survival" in out:
        df = pd.DataFrame(out["ranking_by_median_survival"])
        col = out["group_by"]
        fig = px.bar(df, x="median_survival_years", y=col, orientation="h", text="median_survival_years",
                     hover_data=["n", "survival_1y_pct", "survival_3y_pct", "survival_5y_pct"],
                     labels={"median_survival_years": "중앙생존기간(년)", col: ""}, height=max(300, 26 * len(df)))
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch", key=key)
        return
    if not out.get("curve"):
        return
    df = pd.DataFrame(out["curve"])
    fig = go.Figure()
    fig.add_scatter(x=df["year"], y=df["survival_pct"], mode="lines+markers", name=out.get("target", "대상"), line_shape="hv")
    fig.add_hline(y=50, line_dash="dot", annotation_text="50% (중앙생존)")
    fig.update_layout(xaxis_title="개업 후 경과 연수", yaxis_title="생존율(%)", yaxis_range=[0, 101], height=320,
                      margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
    st.plotly_chart(fig, width="stretch", key=key)


def cycle_chart(out: dict, key: str):
    df = pd.DataFrame(out.get("yearly") or [])
    if df.empty:
        return
    df["label"] = df["year"].astype(str) + df["partial_year"].map({True: "*", False: ""})
    fig = go.Figure()
    fig.add_bar(x=df["label"], y=df["opens"], name="개업")
    fig.add_bar(x=df["label"], y=df["closes"], name="폐업")
    fig.add_scatter(x=df["label"], y=df["active_end_of_year"], name="연말 영업점포", yaxis="y2", mode="lines+markers")
    fig.update_layout(barmode="group", height=320, margin=dict(l=0, r=0, t=10, b=0),
                      yaxis2=dict(overlaying="y", side="right", showgrid=False), legend=dict(orientation="h"))
    st.plotly_chart(fig, width="stretch", key=key)
    st.caption(f"단계: **{out['stage']}** — {out['stage_desc']} (* 부분 연도)")


def history_chart(out: dict, key: str):
    tl = pd.DataFrame(out.get("timeline") or [])
    if tl.empty:
        return
    ref = store().meta["reference_date"]
    tl["end"] = tl["close"].where(tl["close"] != "영업중", ref)
    tl["label"] = tl["name"] + " [" + tl["category"] + "]"
    fig = px.timeline(tl, x_start="open", x_end="end", y="label", color="category", hover_data=["years", "service"],
                      height=max(260, 34 * len(tl)))
    fig.update_yaxes(autorange="reversed", title="")
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
    st.plotly_chart(fig, width="stretch", key=key)


def profile_chart(out: dict, key: str):
    """동네 업종 구성 vs 대구 평균 — 무엇이 이 동네를 특징짓는지 한눈에."""
    share, city = out.get("share_pct"), out.get("city_share_pct")
    if not share:
        return
    df = pd.DataFrame({"항목": list(share), "이 동네": list(share.values()),
                       "대구 평균": [city.get(k) for k in share]})
    fig = go.Figure()
    fig.add_bar(x=df["항목"], y=df["이 동네"], name="이 동네")
    fig.add_bar(x=df["항목"], y=df["대구 평균"], name="대구 평균", marker_opacity=0.55)
    fig.update_layout(barmode="group", height=300, margin=dict(l=0, r=0, t=10, b=0),
                      yaxis_title="비중(%)", legend=dict(orientation="h"))
    st.plotly_chart(fig, width="stretch", key=key)


def station_chart(out: dict, key: str):
    """역별 이용객 순위 또는 한 역의 시간대 구성."""
    slots = {"morning_07_09_pct": "아침 7~9시", "lunch_11_14_pct": "점심 11~14시",
             "evening_17_20_pct": "저녁 17~20시", "night_22_24_pct": "심야 22~24시"}
    if out.get("ranking_by_daily_total"):
        df = pd.DataFrame(out["ranking_by_daily_total"])
        fig = px.bar(df, x="station", y="daily_total", labels={"station": "", "daily_total": "일평균 승하차(명)"},
                     height=300)
    elif out.get("station"):
        df = pd.DataFrame({"시간대": list(slots.values()), "비중": [out.get(k) for k in slots]})
        fig = px.bar(df, x="시간대", y="비중", labels={"비중": "하차 비중(%)"}, height=300,
                     title=f"{out['station']} · 일평균 {int(out['daily_total']):,}명 · 최대 {out['peak_hour']}")
    else:
        return
    fig.update_layout(margin=dict(l=0, r=0, t=40, b=0))
    st.plotly_chart(fig, width="stretch", key=key)


def render_tool_result(name: str, out: dict | None, key: str):
    """Tool 이름에 맞는 시각화를 고른다. key 는 Streamlit 이 차트를 구분하는 고유 id (중복되면 오류)."""
    if not out:
        return
    if name == "get_survival_curve":
        survival_chart(out, key)
    elif name == "get_market_cycle":
        cycle_chart(out, key)
    elif name == "find_vacant_units":
        _map(out["units"], "vacant_days", ["last_store", "last_category", "vacant_days", "closures_since_2010"], key)
    elif name == "find_risk_spots":
        _map(out["spots"], "closures", ["closures", "avg_years_per_store", "now"], key)
    elif name == "get_unit_history":
        history_chart(out, key)
    elif name == "compare_areas":
        rows = [{"지역": a["area"], "표본": a["survival"].get("n"), "중앙생존(년)": a["survival"].get("median_survival_years"),
                 "1년 생존%": a["survival"].get("survival_1y_pct"), "3년 생존%": a["survival"].get("survival_3y_pct"),
                 "공실률%": a["vacancy_rate_pct"], "사이클": a["cycle_stage"], "동종 영업점포": a["active_stores_same_category"],
                 "반복폐업 자리": a["repeat_closure_spots"]} for a in out["areas"]]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", key=key)
    elif name == "get_area_profile":
        profile_chart(out, key)
    elif name == "get_station_traffic":
        station_chart(out, key)
    elif name == "find_nearby":
        rows = [{**v, "address": v["address"]} for v in out.get("recent_vacancies", [])]
        if rows:
            _map(rows + [{"address": out["center"]["address"], "lat": out["center"]["lat"],
                          "lon": out["center"]["lon"], "vacant_days": 0}], "vacant_days",
                 ["last_store", "last_category", "vacant_days"], key)
    elif name == "transition_matrix" and out.get("breakdown"):
        df = pd.DataFrame(out["breakdown"])
        col = "to_category" if "to_category" in df else "from_category"
        fig = px.bar(df, x=col, y="count", color="median_survival_years", text="share_pct",
                     labels={"count": "전이 건수", col: "", "median_survival_years": "후속 중앙생존(년)"}, height=320)
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch", key=key)
