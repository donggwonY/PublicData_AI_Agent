"""내 후보지 저장·비교, 자리 주변 같은 업종, 손익분기 계산기 (2026-11-21 추가).

- 후보지는 방문자 브라우저(localStorage)에 저장한다. 서버·DB에는 남기지 않는다. 저장소가 막힌 브라우저에서는 이 접속에만 남는다.
- 주변 같은 업종 수는 상가정보 분류와 이름을 맞춘 업종(config.POI_CATEGORY_KEYWORDS)만 센다.
- 손익분기 계산은 입력한 가정값의 산수이며 매출 예측이 아니다(core.breakeven).
"""
from __future__ import annotations

import json
import uuid
from datetime import date

import pandas as pd
import streamlit as st

import config as C
from core import breakeven as B
from core import tools as T

MAX_SAVED = 10
COMPARE_MAX = 3
# 상가정보와 업종 이름을 맞춰 둔 업종만 '주변 같은 업종'으로 센다. 커피숍은 카페(커피숍·다방 등 묶음)에 포함
NEARBY_CATEGORIES = [k for k in C.POI_CATEGORY_KEYWORDS if k != "커피숍"]


# ─────────────────────────── 후보지 저장 ───────────────────────────
def saved() -> list[dict]:
    return st.session_state.setdefault("saved_units", [])


def is_saved(unit_id: str, whole: bool) -> bool:
    return any(r["unit_id"] == unit_id and r["whole"] == whole for r in saved())


def toggle_saved(unit_id: str, label: str, whole: bool) -> None:
    """저장 버튼 콜백. 이미 있으면 빼고, 없으면 맨 앞에 넣는다(최대 MAX_SAVED곳)."""
    rows = saved()
    if is_saved(unit_id, whole):
        st.session_state.saved_units = [r for r in rows if not (r["unit_id"] == unit_id and r["whole"] == whole)]
        return
    if len(rows) >= MAX_SAVED:
        st.session_state["saved_full"] = True
        return
    st.session_state.saved_units = [{"unit_id": unit_id, "label": label, "whole": whole,
                                     "saved": date.today().isoformat()}] + rows


def render_save_button(unit_id: str, label: str, whole: bool) -> None:
    on = is_saved(unit_id, whole)
    st.button("후보지에서 빼기" if on else "내 후보지에 저장", icon=":material/star:" if on else ":material/star_border:",
              key=f"save-{unit_id}-{whole}", on_click=toggle_saved, args=(unit_id, label, whole))
    if st.session_state.pop("saved_full", False):
        st.warning(f"후보지는 {MAX_SAVED}곳까지 저장할 수 있어요. '내 후보지'에서 하나를 뺀 뒤 다시 저장해 주세요.")


def parse_stored(raw: str | None) -> tuple[list[dict], list[str]]:
    """브라우저에 저장해 둔 후보지 목록을 읽는다. 반환: (지금 자료에 있는 자리, 찾지 못한 자리 이름).

    자료 갱신으로 자리 키가 바뀌면(E-12처럼) 예전 키는 찾지 못한다. 그런 자리는 목록에서 빼고 이름만 알려 준다.
    """
    if not raw:
        return [], []
    try:
        data = json.loads(raw)
        units = data["units"] if isinstance(data, dict) else data
        rows = [{"unit_id": str(r["unit_id"]), "label": str(r.get("label") or r["unit_id"]),
                 "whole": bool(r.get("whole", False)), "saved": str(r.get("saved", ""))} for r in units]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("저장된 후보지 형식을 읽지 못했어요.")
    known = set(T.store().units["uid"])
    ok, missing, seen = [], [], set()
    for r in rows:
        if (r["unit_id"], r["whole"]) in seen:
            continue
        seen.add((r["unit_id"], r["whole"]))
        if r["unit_id"] in known:
            ok.append(r)
        else:
            missing.append(r["label"])
    return ok[:MAX_SAVED], missing


# ─────────────────────────── 브라우저 저장 (2026-11-21) ───────────────────────────
# 서버(파이썬)는 방문자 브라우저 저장소를 직접 읽지 못해 작은 부품(CCv2)이 둘을 잇는다.
# 1) 접속 후 처음 한 번: 부품이 localStorage 값을 읽어 'loaded' 신호로 보낸다 → 세션 목록에 합친다.
# 2) 그 뒤 매 실행: 세션 목록을 부품에 넘기고, 부품이 바뀐 경우에만 localStorage 에 쓴다.
# 읽기 전에는 쓰지 않는다(빈 목록으로 기존 저장을 덮지 않게). 저장소가 막힌 브라우저는 이 접속에만 남는다.
STORAGE_KEY = "pubdai.saved_units.v1"
_STORE_JS = """
export default function (component) {
  const { data, parentElement, setTriggerValue } = component
  const key = data && data.storage_key
  if (!key) return
  if (data.need_load) {
    if (parentElement.__pubdaiSent === data.nonce) return
    parentElement.__pubdaiSent = data.nonce
    let raw = null
    let ok = true
    try { raw = window.localStorage.getItem(key) } catch (e) { ok = false }
    setTriggerValue("loaded", { ok: ok, raw: raw })
    return
  }
  if (data.write) {
    try {
      const next = JSON.stringify({ version: 1, units: data.units || [] })
      if (window.localStorage.getItem(key) !== next) window.localStorage.setItem(key, next)
    } catch (e) {}
  }
}
"""


def _on_store_loaded() -> None:
    payload = (st.session_state.get("saved_store") or {}).get("loaded") or {}
    st.session_state.saved_store_loaded = True
    if not payload.get("ok", False):
        st.session_state.saved_store_blocked = True
        return
    try:
        stored, missing = parse_stored(payload.get("raw"))
    except ValueError:
        stored, missing = [], []
    now = saved()
    keys = {(r["unit_id"], r["whole"]) for r in now}
    st.session_state.saved_units = (now + [r for r in stored if (r["unit_id"], r["whole"]) not in keys])[:MAX_SAVED]
    if missing:
        st.session_state.saved_missing = missing


def sync_browser_store() -> None:
    """사이드바에서 매 실행 한 번 부른다. 화면에는 아무것도 그리지 않는다."""
    loaded = st.session_state.get("saved_store_loaded", False)
    nonce = st.session_state.setdefault("saved_store_nonce", uuid.uuid4().hex)
    # 등록은 같은 이름이면 덮어쓰므로 매 실행 등록해도 안전하다. 모듈을 불러올 때 한 번만 등록하면
    # 새 Streamlit 실행 환경(테스트·서버 재시작)에서 "등록되지 않음" 오류가 날 수 있다.
    store = st.components.v2.component("pubdai_saved_store", html="<div></div>", js=_STORE_JS)
    store(key="saved_store", data={"storage_key": STORAGE_KEY, "nonce": nonce, "need_load": not loaded,
                                    "write": loaded and not st.session_state.get("saved_store_blocked", False),
                                    "units": saved()},
          on_loaded_change=_on_store_loaded, height="content")


def clear_saved() -> None:
    st.session_state.saved_units = []


# ─────────────────────────── 자리 주변 같은 업종 ───────────────────────────
def default_category(h: dict) -> str | None:
    """자리의 가장 최근 업태가 셀 수 있는 업종이면 그것, 아니면 None."""
    for r in reversed(h.get("timeline") or []):
        c = r.get("category")
        if c in NEARBY_CATEGORIES:
            return c
        if c in C.CATEGORY_ALIASES.get("카페", []):
            return "카페"
    return None


def nearby_summary(unit_id: str, category: str, radius: int = C.NEARBY_RADIUS_M) -> dict:
    """화면용으로 줄인 find_nearby 결과. 같은 건물 안 기록은 '주변 경쟁'에서 뺀 수를 앞에 둔다."""
    out = T.find_nearby(unit_id, radius_m=radius, category=category, limit=5)
    same = out["same_category"] or {}
    excl = same.get("excluding_same_address_deduplicated_count")
    return {
        "radius": out["radius_m"], "stores": out["stores_in_radius"],
        # 중심 건물 도로명 주소를 못 읽으면 같은 건물을 뺄 수 없어 포함한 수를 쓰고 표시한다
        "same": excl if excl is not None else same.get("exact_deduplicated_count"),
        "same_includes_building": excl is None,
        "same_in_building": same.get("same_address_deduplicated_count"),
        "same_label": same.get("query", category),
        "examples": same.get("examples", []),
        "vacancies": out["recent_vacancy_count"],
        "parking": out.get("parking"),
        "poi_basis": out["basis"].get("poi"),
    }


def render_nearby(h: dict, key: str) -> None:
    u = h["unit"]
    st.markdown(f"#### 주변 {C.NEARBY_RADIUS_M}m 같은 업종")
    if u.get("lat") is None or pd.isna(u.get("lat")):
        st.caption("이 자리는 위치 정보가 없어 주변을 셀 수 없어요.")
        return
    cat0 = default_category(h)
    cat = st.selectbox("업종", NEARBY_CATEGORIES, index=NEARBY_CATEGORIES.index(cat0) if cat0 else None,
                       placeholder="창업하려는 업종을 고르세요", key=f"near-cat-{key}")
    if not cat:
        st.caption("업종을 고르면 반경 안 같은 업종 가게 수를 보여 줘요.")
        return
    try:
        n = nearby_summary(u["unit_id"], cat)
    except T.ToolError as e:
        st.warning(str(e))
        return
    c = st.columns(4)
    c[0].metric(f"같은 업종 ({n['same_label'].split('(')[0]})" + (" · 같은 건물 포함" if n["same_includes_building"] else ""),
                f"{n['same']}곳" if n["same"] is not None else "-", border=True)
    c[1].metric("같은 건물 안 같은 업종", f"{n['same_in_building']}곳" if n["same_in_building"] is not None else "-",
                border=True)
    c[2].metric("반경 안 전체 가게", f"{n['stores']:,}곳", border=True)
    c[3].metric("반경 안 인허가 공백 후보", f"{n['vacancies']}곳", border=True)
    if n["examples"]:
        st.caption("가까운 같은 업종: " + " · ".join(f"{e['name']}({int(e['dist_m'])}m)" for e in n["examples"]))
    st.caption(f"출처: {n['poi_basis']} · 직선거리 기준 · 상가 기록 수라 실제 영업 여부와 다를 수 있어요. "
               "같은 업종은 같은 건물 기록을 뺀 수예요. 상가정보와 분류 이름을 맞춘 업종만 고를 수 있어요.")


# ─────────────────────────── 후보지 비교 ───────────────────────────
def _survival_ref(gu: str, dong: str, category: str) -> tuple[str, dict | None]:
    """동 → 구 → 대구 순으로 표본이 충분한 범위의 생존율."""
    for label, kw in [(dong, {"gu": gu, "dong": dong}), (gu, {"gu": gu}), ("대구", {})]:
        try:
            return label, T.get_survival_curve(category=category, **kw)
        except T.ToolError:
            continue
    return "-", None


def compare_row(item: dict, category: str | None) -> dict:
    """후보지 한 곳의 비교표 열. 자리를 못 찾으면 그 사실만 담는다."""
    try:
        h = T.get_unit_history(item["unit_id"], whole_building=item["whole"])
    except T.ToolError:
        return {"후보지": item["label"], "지금 상태": "자리 정보를 찾지 못했어요(자료 갱신으로 바뀌었을 수 있어요)"}
    u, s = h["unit"], h["summary"]
    last = (h["timeline"] or [{}])[-1]
    row = {
        "후보지": item["label"],
        "지금 상태": "영업 중" if not u["vacant"] else f"인허가 공백 {u['vacant_days']:,}일째",
        "마지막 가게": f"{last.get('name', '-')} ({last.get('category', '-')})",
        "2010년 이후 폐업": f"{s['closures_since_2010']}건",
        "폐업 가게 평균 영업": f"{s['avg_years_closed_since_2010']}년" if s["avg_years_closed_since_2010"] else "-",
        "다점포 건물": "예" if not u["is_single_unit"] else "아니요",
    }
    v = h.get("vacancy_outlook")
    row["1년 안 재입점 가능성"] = T.pct_text(v["p_fill_1y"]) if v else "-"
    nt = h.get("next_tenant_outlook")
    row["다음 업종 1위"] = f"{nt['top3'][0]['group']} {T.pct_text(nt['top3'][0]['p'])}" if nt else "-"
    if category:
        try:
            n = nearby_summary(u["unit_id"], category)
            row[f"주변 {C.NEARBY_RADIUS_M}m 같은 업종"] = (
                f"{n['same']}곳" + (" (같은 건물 포함)" if n["same_includes_building"] else "")
                if n["same"] is not None else "-")
        except T.ToolError:
            row[f"주변 {C.NEARBY_RADIUS_M}m 같은 업종"] = "-"
        where, sv = _survival_ref(u["gu"], u["dong"], category)
        if sv:
            row["같은 업종 1년·3년 생존율"] = f"{sv['survival_1y_pct']}% · {sv['survival_3y_pct']}% ({where}, n={sv['n']:,})"
        else:
            row["같은 업종 1년·3년 생존율"] = "-"
    return row


def render_compare(go_unit) -> None:
    rows = saved()
    st.subheader("저장한 후보지 비교")
    if not rows:
        st.info("아직 저장한 후보지가 없어요. ‘자리 이력’에서 자리를 조회한 뒤 ‘내 후보지에 저장’을 누르세요.")
        return
    labels = {i: r["label"].replace("대구광역시 ", "") for i, r in enumerate(rows)}
    pick = st.multiselect(f"비교할 후보지 (최대 {COMPARE_MAX}곳)", list(labels), default=list(labels)[:COMPARE_MAX],
                          format_func=labels.get, max_selections=COMPARE_MAX, key="plan_pick")
    cat = st.selectbox("창업하려는 업종 (주변 경쟁·생존율 비교용)", NEARBY_CATEGORIES, index=None,
                       placeholder="고르면 주변 같은 업종 수와 생존율이 함께 나와요", key="plan_category")
    if pick:
        table = pd.DataFrame([compare_row(rows[i], cat) for i in pick]).set_index("후보지").T
        table.columns = [labels[i] for i in pick]
        st.dataframe(table, width="stretch")
        st.caption("인허가 공백은 실제 빈 점포·임대 매물 여부를 확인한 결과가 아니에요. 생존율은 2010년 이후 개업한 가게의 "
                   "Kaplan–Meier 추정이며, 표본이 적으면 구·대구 범위로 넓혀 보여 줘요. 재입점 가능성·다음 업종은 "
                   "비어 있는 자리에만 나와요.")
    with st.expander(f"저장한 후보지 관리 ({len(rows)}/{MAX_SAVED})"):
        for i, r in enumerate(rows):
            c1, c2, c3 = st.columns([6, 2, 2])
            c1.markdown(labels[i] + (" (건물 전체)" if r["whole"] and "건물 전체" not in labels[i] else ""))
            c2.button("이력 보기", key=f"plan-go-{i}", type="tertiary", on_click=go_unit, args=(r,))
            c3.button("빼기", key=f"plan-del-{i}", type="tertiary", on_click=toggle_saved,
                      args=(r["unit_id"], r["label"], r["whole"]))
        st.caption(storage_note())
        st.button("목록 모두 지우기", icon=":material/delete:", key="plan-clear", on_click=clear_saved)


def storage_note() -> str:
    if st.session_state.get("saved_store_blocked"):
        return "이 브라우저는 저장을 막고 있어 지금 접속에만 남아요. 새로고침하면 사라져요."
    return ("후보지는 이 기기의 이 브라우저에만 저장돼요(서버에는 남지 않아요). 다른 기기·브라우저에서는 보이지 않고, "
            "시크릿 창이나 방문 기록 삭제 때 지워져요. 함께 쓰는 컴퓨터라면 다 본 뒤 ‘목록 모두 지우기’를 눌러 주세요.")


# ─────────────────────────── 손익분기 계산기 ───────────────────────────
def won(v: float | None) -> str:
    if v is None:
        return "-"
    return f"{v / 10_000:,.0f}만 원" if abs(v) >= 10_000 else f"{v:,.0f}원"


def render_calculator() -> None:
    st.subheader("손익분기 계산기")
    st.caption("넣은 가정값으로 ‘본전이 되려면 하루 몇 건 팔아야 하는지’ 계산해요. 매출을 예측하지 않아요. "
               "세금(부가세·소득세)·대출 원금 상환·감가상각은 넣지 않았어요.")
    with st.form("calc"):
        st.markdown("**한 건 팔 때**")
        c = st.columns(3)
        ticket = c[0].number_input("결제 1건 평균 금액(원)", min_value=0, step=500, value=None, placeholder="예: 7,000")
        cost = c[1].number_input("원가율(%)", min_value=0.0, max_value=99.0, step=1.0, value=None,
                                 placeholder="재료비 비율, 예: 35", help="팔 때마다 비례해 드는 재료·포장비 비율")
        fee = c[2].number_input("카드·배달 수수료율(%)", min_value=0.0, max_value=99.0, step=0.5, value=None,
                                placeholder="예: 3")
        st.markdown("**매달 나가는 돈**")
        c = st.columns(3)
        rent = c[0].number_input("월세+관리비(만 원)", min_value=0, step=10, value=None, placeholder="예: 150")
        labor = c[1].number_input("직원 인건비(만 원)", min_value=0, step=10, value=None, placeholder="없으면 0")
        other = c[2].number_input("기타 고정비(만 원)", min_value=0, step=5, value=None, placeholder="공과금·통신 등")
        c = st.columns(3)
        days = c[0].number_input("월 영업일", min_value=1, max_value=31, step=1, value=26)
        owner = c[1].number_input("내가 가져갈 목표 월 소득(만 원)", min_value=0, step=10, value=None,
                                  placeholder="선택", help="넣으면 이 소득까지 벌려면 몇 건이 필요한지도 계산해요")
        st.markdown("**선택: 예상 판매량과 초기 투자비**")
        c = st.columns(3)
        exp = c[0].number_input("예상 하루 결제 건수", min_value=0.0, step=5.0, value=None, placeholder="선택")
        inv = c[1].number_input("초기 투자비(만 원)", min_value=0, step=100, value=None,
                                placeholder="보증금 제외", help="인테리어·설비·권리금 등. 돌려받는 보증금은 빼고 넣으세요")
        go = st.form_submit_button("계산하기", type="primary")
    if not go:
        return
    if None in (ticket, cost, fee, rent):
        st.warning("결제 1건 금액, 원가율, 수수료율, 월세+관리비는 꼭 넣어 주세요. 없는 항목은 0으로 넣으면 돼요.")
        return
    man = 10_000
    try:
        r = B.calculate(B.Inputs(ticket=ticket, cost_rate_pct=cost, fee_rate_pct=fee, rent=rent * man,
                                 labor=(labor or 0) * man, other_fixed=(other or 0) * man, days=int(days),
                                 owner_pay=(owner or 0) * man, expected_daily=exp, investment=(inv or 0) * man))
    except B.BreakevenError as e:
        st.warning(str(e))
        return
    be = r["breakeven"]
    c = st.columns(3)
    c[0].metric("본전 하루 결제", f"{be['daily_orders']:,}건", f"월 {be['monthly_orders']:,}건", delta_color="off",
                delta_arrow="off", border=True)
    c[1].metric("본전 월 매출", won(be["monthly_sales"]), f"월 고정비 {won(r['monthly_fixed'])}", delta_color="off",
                delta_arrow="off", border=True)
    if r["target"]:
        t = r["target"]
        c[2].metric("목표 소득까지 하루 결제", f"{t['daily_orders']:,}건", f"월 매출 {won(t['monthly_sales'])}",
                    delta_color="off", delta_arrow="off", border=True)
    st.caption(f"1건 팔면 남는 돈 {won(r['margin_per_order'])} (결제 금액 × (1 − 원가율 {cost:g}% − 수수료율 {fee:g}%)) · "
               f"본전 건수 = 월 고정비 ÷ 1건당 남는 돈, 소수점은 올림")
    if r["scenarios"]:
        df = pd.DataFrame(r["scenarios"])
        show = pd.DataFrame({
            "시나리오": [f"{n} ({'−20%' if n == '보수' else '+20%' if n == '낙관' else '입력값'})" for n in df["name"]],
            "하루 결제": [f"{x:g}건" for x in df["daily_orders"]],
            "월 매출": [won(x) for x in df["monthly_sales"]],
            "월 영업이익": [won(x) for x in df["monthly_profit"]],
        })
        if r["target"]:
            show["목표 소득 뺀 뒤"] = [won(x) for x in df["after_owner_pay"]]
        if inv:
            show["투자비 회수"] = [f"약 {x}개월" if x else "회수 안 됨" for x in df["payback_months"]]
        st.dataframe(show, hide_index=True, width="stretch")
        st.caption("예상 하루 결제 건수는 직접 넣은 가정이에요. 이 앱은 자리별 매출·손님 수를 알 수 없어요. "
                   "위 ‘저장한 후보지 비교’의 주변 같은 업종 수와 생존율을 함께 보며 가정이 현실적인지 따져 보세요.")
