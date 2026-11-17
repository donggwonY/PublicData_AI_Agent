"""상권 둘러보기의 세부 업태 범위와 '앞으로 1년 폐업 예측'(E-06).

- 세부 업태(예: 커피숍)는 예측표와 같은 정의로, 인허가 종류와 관계없이 그 업태 전체를 뜻한다.
- 예측 수치는 core.tools.get_competition_outlook 이 저장된 예측표에서 읽어 준다(AI 상담과 같은 값).
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import tools as T

OPEN_C, CLOSE_C, PRED_C = "#0f766e", "#c2410c", "rgba(194,65,12,.30)"
EXCLUDED = {"기타"}  # 서로 다른 가게가 섞인 분류라 세부 업태로 고르지 않는다


def _md(text: str) -> str:
    """캡션·마크다운에서 물결표(~) 두 개가 취소선으로 바뀌지 않게 막는다."""
    return text.replace("~", "\\~")


def _services(industry: str) -> list[str]:
    return ["의원", "병원"] if industry == "의원·병원" else [industry]


def sub_category_choices(stores: pd.DataFrame, industry: str) -> list[str]:
    """업종(인허가 종류) 안의 세부 업태. 현재 영업 수가 많은 순, 분류 이름 변경은 합친다."""
    if not {"service", "category", "closed"} <= set(stores.columns):
        return []
    s = stores[stores["service"].isin(_services(industry))]
    cats = s["category"].replace(T.FORECAST_MERGE)
    active = (~s["closed"].astype(bool)).groupby(cats).sum()
    return [c for c in active[active > 0].sort_values(ascending=False).index if c not in EXCLUDED]


def sub_label(sub: str) -> str:
    """집계표 안에서 쓰는 이름. 업종 이름(예: 담배소매업·의원)과 겹치지 않게 표시를 붙인다."""
    return f"{sub} (세부 업태)"


def scoped_stores(stores: pd.DataFrame, sub: str) -> pd.DataFrame:
    """세부 업태 기록의 업종 이름을 sub_label 로 바꾼 복사본. 다른 기록은 그대로 두어 지역 비중의 분모를 유지한다."""
    out = stores.copy()
    m = out["category"].replace(T.FORECAST_MERGE).eq(sub)
    out["service"] = out["service"].astype(object)
    out.loc[m, "service"] = sub_label(sub)
    return out


def _flow_chart(periods: list[str], opens: list[int], closes: list[int], pred: float,
                rng: tuple[int, int] | None, key: str) -> None:
    fut = "앞으로 1년"
    x = periods + [fut]
    fig = go.Figure()
    fig.add_bar(x=x, y=opens + [None], name="개업(실제)", marker_color=OPEN_C,
                text=[f"{v:,}" for v in opens] + [""], textposition="outside")
    # 폐업은 실제 3기간 + 예측 1개를 같은 막대 줄에 둔다(예측은 옅은 색·범위 표시).
    err = None if rng is None else dict(type="data", symmetric=False, array=[0] * len(closes) + [rng[1] - pred],
                                        arrayminus=[0] * len(closes) + [pred - rng[0]], color="#7c2d12", thickness=1.5, width=8)
    fig.add_bar(x=x, y=closes + [pred], name="폐업(실제·옅은 막대는 예측)",
                marker=dict(color=[CLOSE_C] * len(closes) + [PRED_C], line=dict(color=CLOSE_C, width=1.5)),
                text=[f"{v:,}" for v in closes] + [""], textposition="outside", error_y=err)
    top = max(opens + closes + [rng[1] if rng else pred])
    label = f"약 {round(pred):,}" + ("" if rng is None else f"<br>({rng[0]:,}~{rng[1]:,})")
    fig.add_annotation(x=fut, y=(rng[1] if rng else pred), text=label, showarrow=False, yshift=22,
                       font=dict(size=12, color="#7c2d12"))
    fig.update_layout(height=320, barmode="group", bargap=.28, margin=dict(l=0, r=10, t=36, b=10),
                      legend=dict(orientation="h", y=1.14, title_text=""),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(categoryorder="array", categoryarray=x)
    fig.update_yaxes(title=None, gridcolor="rgba(128,128,128,.12)", rangemode="tozero", range=[0, top * 1.25 + 1])
    st.plotly_chart(fig, width="stretch", key=key)


def render_flow_with_forecast(sub: str, gu: str | None) -> bool:
    """세부 업태의 최근 3기간 실제 개업·폐업과 앞으로 1년 폐업 예측을 한 그래프로. 예측이 없으면 False."""
    out = T.get_competition_outlook(sub, gu=gu, top_n=9)
    items = [i for i in out.get("items", []) if i["category"] == sub]
    if not out.get("available") or not items:
        return False
    periods = list(items[0]["recent_closes"])
    if gu:
        it = items[0]
        opens, closes = list(it["recent_opens"].values()), list(it["recent_closes"].values())
        pred, rng = it["closes_pred"], tuple(it["closes_range"])
    else:
        opens = [sum(i["recent_opens"][p] for i in items) for p in periods]
        closes = [sum(i["recent_closes"][p] for i in items) for p in periods]
        pred, rng = sum(i["closes_pred"] for i in items), None
    c1, c2, c3 = st.columns(3)
    c1.metric("앞으로 1년 폐업 예상", "1곳 미만" if pred < 1 else f"약 {round(pred):,}곳", border=True)
    c2.metric("범위", "구·군별로 제공" if rng is None else f"{rng[0]:,}~{rng[1]:,}곳", border=True)
    c3.metric("직전 1년 실제 폐업", f"{closes[-1]:,}곳", border=True)
    _flow_chart(periods, opens, closes, pred, rng, key=f"dash-flow-{gu}-{sub}")
    st.caption(_md(f"{out['period']} 예측 · 단위: 곳(겸업은 한 곳) · 기간은 11월 7일~다음 해 11월 6일. "
               "위의 인허가 건수와 세는 방식이 달라 조금 다를 수 있어요."))
    st.caption(f"범위: {out['range_note']}. 영업 중인 가게가 많은 곳은 폐업 수도 많으므로 폐업 수만으로 지역을 고르지 마세요.")
    # 구·군별 예측(2026-11-17): 특정 구를 골라도 다른 구·군과 견줄 수 있게 항상 둔다. 단위는 곳만 쓴다.
    all_gu = items if not gu else [i for i in T.get_competition_outlook(sub, top_n=9).get("items", [])
                                   if i["category"] == sub]
    if all_gu:
        with st.expander("구·군별 예측" + (f" · {gu}와 비교" if gu else "")):
            st.dataframe(pd.DataFrame([{"구·군": i["gu"] + (" (선택)" if i["gu"] == gu else ""),
                                        "폐업 예상(곳)": round(i["closes_pred"]),
                                        "범위(곳)": f"{i['closes_range'][0]:,}~{i['closes_range'][1]:,}",
                                        "직전 1년 실제 폐업(곳)": list(i["recent_closes"].values())[-1]} for i in all_gu]),
                         hide_index=True, width="stretch")
            st.caption(("대구 합계는 구·군 예상의 합이며 범위는 구·군별로만 제공합니다. " if not gu else "")
                       + "예상 폐업이 많은 순이며, 영업 중인 가게가 많은 구·군일수록 폐업 수도 많습니다.")
    with st.expander("예측 기준과 한계"):
        st.caption(out["caveat"])
        st.caption("근거: 과거 7개 기간 점검에서 직전 3년 평균보다 약 14% 정확했습니다(오프라인 포아송 회귀 모델의 저장값).")
    return True


def render_sub_forecast_table(stores: pd.DataFrame, industry: str, gu: str | None, top: int = 6) -> None:
    """업종 전체를 볼 때: 세부 업태별 앞으로 1년 폐업 예상을 짧은 표로."""
    cf = T.store().competition
    if cf is None or str(cf["reference_date"].iat[0]) != str(T.store().ref.date()):
        return
    subs = sub_category_choices(stores, industry)
    f = cf[cf["category"].isin(subs)]
    if gu:
        f = f[f["gu"] == gu]
        rows = [{"세부 업태": r.category, "폐업 예상(곳)": round(r.closes_pred), "범위(곳)": f"{r.closes_lo:,}~{r.closes_hi:,}"}
                for r in f.sort_values("closes_pred", ascending=False).head(top).itertuples()]
    else:
        g = f.groupby("category")["closes_pred"].sum().sort_values(ascending=False).head(top)
        rows = [{"세부 업태": c, "폐업 예상(곳, 구·군 합)": round(v)} for c, v in g.items()]
    if not rows:
        return
    period = T._forecast_period_text(str(cf["period_start"].iat[0]), str(cf["period_end"].iat[0]))
    st.markdown(_md(f"**세부 업태별 {period} 폐업 예상**"))
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("위에서 세부 업태를 고르면 실제 기록과 예측을 한 그래프로 볼 수 있어요. "
               + ("" if gu else "대구 전체는 구·군 예상의 합이며 범위는 구·군을 고르면 보여요. ")
               + f"범위: {T.FORECAST_RANGE_NOTE}.")
