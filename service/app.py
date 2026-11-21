"""Streamlit UI.  실행: streamlit run app.py

LLM 설정은 .streamlit/secrets.toml(배포 시 Streamlit Cloud Secrets) 또는 환경변수에서 읽는다.
  LLM_PROVIDER = "gemini" | "claude"
  GEMINI_API_KEY / ANTHROPIC_API_KEY = 운영자 키 (없으면 AI 상담 탭은 이용 불가 안내만, 방문자 키 입력 없음)

Streamlit 을 읽기 전에 알아야 할 것
    버튼을 누르거나 글자를 입력할 때마다 이 파일이 위에서 아래로 '통째로 다시 실행'된다.
    그래서 사라지면 안 되는 값은 st.session_state 에 넣어 둔다.

값을 어디에 두느냐 = 누구와 공유되느냐 (공개 웹에서 가장 중요한 판단)
    st.session_state    방문자 한 명(브라우저 세션)   대화 이력, 에이전트, 방문자가 입력한 API 키
    @st.cache_resource  서버 전체, 모든 방문자 공유    분당 질문 제한 창, 데이터 표(읽기 전용)
    os.environ          서버 프로세스 전체            읽기만 한다. 방문자 키를 쓰면 다른 방문자에게 샌다
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
import uuid
from collections import deque

import pandas as pd
import streamlit as st

import config as C
from agent import API_KEY_ENV, create_agent
from core import tools as T
import ui_planner as P
from ui_area_outlook import render_population_outlook, render_similar_areas
from ui_permit_trends import industry_choices, render_permit_trends
from ui_vacancy import (CANDIDATE_COLS, TIMELINE_COLS, korean_table, render_next_tenant, render_unit_summary, render_vacancy_outlook,
                        tenure_sentences)
from ui_visuals import (ai_markdown, cycle_chart, history_chart, render_tool_result, render_tool_steps, survival_chart, tool_label,
                        _map, metric_value)

st.set_page_config(page_title="대구 상권 생애주기 AI 에이전트", page_icon="🏪", layout="wide")
st.markdown("""<style>
.block-container {max-width:1200px; padding-top:2rem; padding-bottom:3rem;}
h1 {font-size:2rem !important; letter-spacing:-.04em;}
h2,h3 {letter-spacing:-.025em;}
[data-testid="stMetric"] {background:rgba(15,118,110,.045); border-radius:14px; padding:16px;}
[data-testid="stMetricValue"] {font-size:1.8rem;}
[data-testid="stSidebar"] {min-width:260px; max-width:290px;}
@media(max-width:700px) {.block-container {padding:4rem 1rem 1rem;} h1 {font-size:1.5rem !important;}}
</style>""", unsafe_allow_html=True)


# 데이터 출처(core/datasource.py)는 환경변수로 고른다. 배포에서는 Secrets 의 같은 이름을 서버 환경변수로 옮긴다.
# 운영자가 정한 서버 설정이라 os.environ 에 둬도 된다(방문자 값은 여기에 넣지 않는다).
for _name in ("APP_DATABASE_URL", "APP_DATA_SOURCE", "APP_DATA_VERSION"):
    try:
        if _name in st.secrets and not os.environ.get(_name):
            os.environ[_name] = str(st.secrets[_name])
    except Exception:  # secrets.toml 이 없으면 st.secrets 접근 자체가 예외를 던진다
        break

try:
    S = T.store()
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()
META = S.meta
GUS = ["중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군", "군위군"]
EXAMPLES = [
    "수성구에서 카페 열려는데 어때?",
    "그럼 뭐가 더 오래 가?",
    "수성구, 중구, 달서구 중 카페 하기엔 어디가 나아?",
    "중구 삼덕동1가 요즘 분위기는?",
    "그 동네에 최근 빈자리 있어?",
    "대구 군위군 중앙길 90 이전엔 뭐였어?",
]


def setting(name: str, default=None):
    """Streamlit Secrets → 환경변수 → 기본값 순.

    같은 코드를 세 환경에서 돌리기 위한 장치다.
    배포(Streamlit Cloud)는 Secrets, 내 PC 터미널은 환경변수, 아무것도 없으면 config.py 기본값.
    """
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:  # secrets.toml 이 없으면 st.secrets 접근 자체가 예외를 던진다
        pass
    return os.environ.get(name, default)


PROVIDER = str(setting("LLM_PROVIDER", C.LLM_PROVIDER)).lower()
PROVIDER_LABEL = {"gemini": "Google Gemini", "claude": "Anthropic Claude"}.get(PROVIDER, PROVIDER)
KEY_NAME = API_KEY_ENV.get(PROVIDER, "API_KEY")
OPERATOR_KEY = setting(KEY_NAME)
MAX_PER_SESSION = int(setting("MAX_QUESTIONS_PER_SESSION", C.MAX_QUESTIONS_PER_SESSION))
GLOBAL_PER_MINUTE = int(setting("GLOBAL_QUESTIONS_PER_MINUTE", C.GLOBAL_QUESTIONS_PER_MINUTE))


@st.cache_resource
def _rate_window() -> dict:
    """모든 방문자가 공유하는 최근 1분 질문 시각 (서버 프로세스당 1개).

    @st.cache_resource 는 '서버에 하나만 만들어 모두가 함께 쓰는 객체'를 만든다.
    여러 방문자가 동시에 고치므로 Lock 으로 감싸야 숫자가 꼬이지 않는다.
    """
    return {"lock": threading.Lock(), "times": deque()}


quota_slot = None   # 사이드바 '남은 질문' 줄(st.empty). 사이드바에서 만든다.


def render_quota() -> None:
    """사이드바 남은 질문 수. 질문 처리 중 횟수를 올린 직후 같은 자리를 다시 그려 바로 줄어든 값이 보인다."""
    if quota_slot is not None:
        left = MAX_PER_SESSION - st.session_state.get("questions_used", 0)
        quota_slot.markdown(f":material/check_circle: 사용 가능 · 남은 질문 **{max(left, 0)}회**")


def take_quota() -> str | None:
    """질문 1회를 허용하면 None, 막아야 하면 안내 문구."""
    used = st.session_state.get("questions_used", 0)
    if used >= MAX_PER_SESSION:
        return f"이 세션의 무료 질문 {MAX_PER_SESSION}회를 모두 사용했습니다. 대시보드·자리 이력 조회 탭은 계속 이용할 수 있습니다."
    w, now = _rate_window(), time.time()
    with w["lock"]:  # 여러 방문자가 동시에 질문해도 한 번에 한 명씩만 이 블록에 들어온다
        while w["times"] and now - w["times"][0] > 60:
            w["times"].popleft()  # 1분이 지난 기록은 버린다(deque 는 앞에서 빼기가 빠르다)
        if len(w["times"]) >= GLOBAL_PER_MINUTE:
            wait = int(60 - (now - w["times"][0])) + 1
            return f"지금 이용자가 많아 잠시 대기가 필요합니다. 약 {wait}초 뒤에 다시 질문해 주세요."
        w["times"].append(now)
    st.session_state.questions_used = used + 1
    render_quota()
    return None


def get_agent(api_key: str):
    """방문자 세션마다 별도 에이전트. 키가 바뀌면 새로 만든다."""
    sig = hashlib.sha256(f"{PROVIDER}:{api_key}".encode()).hexdigest()
    if st.session_state.get("agent_sig") != sig:
        st.session_state.agent = create_agent(PROVIDER, api_key)
        st.session_state.agent_sig = sig
    return st.session_state.agent


# ─────────────────────────── 사이드바 ───────────────────────────
# 사이드바 개편(2026-11-15): 기준일·바로 가기·최근 본 자리·AI 상담 상태·용어 도움말을 접지 않고 보여 준다.
# 탭은 key 로 상태를 추적해 사이드바 버튼(바로 가기·최근 본 자리·예시 질문)이 해당 탭으로 옮겨 준다.
TAB_DASH, TAB_UNIT, TAB_PLAN, TAB_CHAT = "📊 상권 둘러보기", "🔎 자리 이력", "⭐ 내 후보지", "💬 AI 상담"
NAV = [(TAB_DASH, ":material/storefront:", "동네·업종 비교"),
       (TAB_UNIT, ":material/history:", "한 자리의 이력"),
       (TAB_PLAN, ":material/star:", "후보지 비교·손익 계산"),
       (TAB_CHAT, ":material/forum:", "AI에게 물어보기")]
GLOSSARY = [
    ("인허가 기록", "지자체 영업 인허가 자료의 한 건. 한 점포가 업종을 바꾸면 기록이 여러 건일 수 있어요."),
    ("폐업 신고", "인허가가 폐업 처리된 것. 이전·양도도 포함되며 사업 실패를 뜻하지 않아요."),
    ("인허가 공백(공실)", "마지막 가게가 폐업한 뒤 같은 자리에 새 인허가가 없는 상태. 실제 빈 점포와 다를 수 있어요."),
    ("재입점 가능성", "비어 있던 기간을 반영해, 1년 안에 같은 자리에 점포형 가게 인허가가 다시 생길 확률(과거 사례로 학습한 모델)."),
    ("중앙생존기간", "대구 같은 업태 가게(2010년 이후 개업)의 절반이 문을 닫은 시점."),
]


def fav_examples(gu: str, ind: str) -> list[str]:
    """사이드바 '내 관심 조건'으로 만든 예시 질문. 조건이 없으면 기본 예시."""
    if gu == "대구 전체" and ind == "전체 업종":
        return EXAMPLES
    where = "대구" if gu == "대구 전체" else gu
    if ind == "전체 업종":
        return [f"{where} 요즘 상권 분위기는?", f"{where}에서 오래 가는 업종은 뭐야?",
                f"{where}에 최근 빈자리 있어?", "그럼 뭐가 더 오래 가?"]
    out = [f"{where}에서 {ind} 열려는데 어때?", f"{ind} 가게는 보통 얼마나 오래 영업해?"]
    if gu != "대구 전체":
        out.append(f"{gu}에 최근 빈자리 있어?")
    return out + ["그럼 뭐가 더 오래 가?"]


def set_fav(gu: str | None = None, ind: str | None = None) -> None:
    """사이드바 '내 관심 조건' 콜백: 상권 둘러보기의 지역·관심 업종 선택도 같이 바꾼다(양방향 연동)."""
    gu = gu or st.session_state.fav_gu
    ind = ind or st.session_state.fav_industry
    st.session_state.fav_gu = st.session_state.dash_gu = gu
    st.session_state.fav_industry = st.session_state.dash_trend_industry = ind
    st.session_state.saved_dash_trend_industry = ind


def go_tab(tab: str, **state) -> None:
    """사이드바 버튼 콜백: 탭을 바꾸고 필요한 입력값을 미리 채운다(위젯이 그려지기 전이라 안전)."""
    st.session_state.main_tab = tab
    for k, v in state.items():
        st.session_state[k] = v


def render_recent_units() -> None:
    """사이드바 '최근 본 자리' 목록. 자리 조회 직후 같은 자리(st.empty)를 다시 그려 방금 본 자리도 바로 보인다."""
    # 한 번의 실행에서 두 번 그려질 수 있어(조회 직후) 위젯 key 에 그리기 차례를 넣어 겹치지 않게 한다
    draw = st.session_state["_recent_draw"] = st.session_state.get("_recent_draw", 0) + 1
    with recent_slot.container():
        recent = st.session_state.get("recent_units", [])
        if not recent:
            st.caption("자리 이력에서 조회한 주소가 여기 모여요.")
        for i, r in enumerate(recent):
            st.button(r["label"].replace("대구광역시 ", ""), icon=":material/location_on:", key=f"recent-{draw}-{i}",
                      type="tertiary", on_click=go_tab, args=(TAB_UNIT,),
                      kwargs={"unit_addr": r["query"], "unit_whole": r["whole"]})


def remember_unit(label: str, query: str, whole: bool) -> None:
    """자리 이력에서 조회에 성공한 자리를 최근 5곳까지 기억한다(이 브라우저 세션에만)."""
    recent = [r for r in st.session_state.get("recent_units", []) if r["query"] != query or r["whole"] != whole]
    new = ([{"label": label, "query": query, "whole": whole}] + recent)[:5]
    if new != st.session_state.get("recent_units"):
        st.session_state.recent_units = new
        render_recent_units()


with st.sidebar:
    rec = META["records"]["통합"]
    services = [k for k in META["records"] if k != "통합"]
    first_year = min(int(v["date_min"][:4]) for k, v in META["records"].items() if k != "통합")
    st.subheader("인허가로 보는 대구 상권")
    st.caption(f"{first_year}년부터 쌓인 영업 인허가 기록으로 동네와 자리를 살펴봐요.")
    kpi_label = ('+'.join(s.replace('영업', '') for s in services) if len(services) <= 8
                 else f"점포형 {len(services)}개 업종")
    ref = pd.Timestamp(META["reference_date"]).date()
    age = (pd.Timestamp.now(tz="Asia/Seoul").date() - ref).days
    with st.container(border=True):
        st.caption("자료 기준일")
        day = f"{ref.year}년 {ref.month}월 {ref.day}일"
        st.markdown(f"**{day}** <small>({age}일 전)</small>" if age > 0 else f"**{day}**", unsafe_allow_html=True)
        st.caption(f"대구 {kpi_label} 인허가 · 현재 영업 중 {rec['active']:,}건")
        with st.expander("수록 데이터 자세히"):
            st.metric(f"누적 인허가 ({kpi_label})", f"{rec['total']:,}")
            if len(services) > 8:
                with st.expander("포함 업종 보기"):
                    st.caption(" · ".join(services))
            # 누적 수치를 '현재 점포 수'로 오해하기 쉬워 기간을 명시한다
            st.caption(f"{first_year}년부터 {META['reference_date'][:4]}년까지 문을 연 전체 기록 (현재 점포 수가 아님)")
            c1, c2 = st.columns(2)
            c1.metric("그동안 폐업", f"{rec['closed']:,}")
            c2.metric("현재 영업 중", f"{rec['active']:,}")
            st.caption(f"배치 {META['built_at']} · 데이터 {S.source}")

    # 내 관심 조건(2026-11-15): 한 번 고르면 상권 둘러보기 지역·관심 업종과 예시 질문에 함께 적용
    IND_CHOICES = industry_choices(S.stores)
    st.session_state.setdefault("fav_gu", st.session_state.get("dash_gu", "대구 전체"))
    st.session_state.setdefault("fav_industry", st.session_state.get("saved_dash_trend_industry", "전체 업종"))
    st.markdown("**내 관심 조건**")
    with st.container(border=True):
        st.selectbox("지역", ["대구 전체"] + GUS, key="fav_gu", on_change=set_fav)
        st.selectbox("업종", IND_CHOICES, key="fav_industry", on_change=set_fav)
        fav_on = st.session_state.fav_gu != "대구 전체" or st.session_state.fav_industry != "전체 업종"
        if fav_on:
            st.caption("상권 둘러보기와 AI 예시 질문에 적용 중이에요.")
            st.button("조건 해제", icon=":material/close:", type="tertiary",
                      on_click=set_fav, args=("대구 전체", "전체 업종"))
        else:
            st.caption("고르면 상권 둘러보기와 AI 예시 질문에 함께 적용돼요.")

    st.markdown("**바로 가기**")
    cur = st.session_state.get("main_tab", TAB_DASH)
    for tab, icon, desc in NAV:
        st.button(desc, icon=icon, width="stretch", key=f"nav-{tab}",
                  type="primary" if tab == cur else "secondary", on_click=go_tab, args=(tab,))

    st.markdown("**내 후보지**")
    P.sync_browser_store()          # 브라우저에 저장해 둔 후보지 읽기·쓰기(화면에는 안 보임)
    _missing = st.session_state.pop("saved_missing", None)
    if _missing:
        st.caption("자료 갱신으로 찾지 못한 후보지: " + ", ".join(m.replace("대구광역시 ", "") for m in _missing)
                   + " — 자리 이력에서 다시 찾아 저장해 주세요.")
    if P.saved():
        for i, r in enumerate(P.saved()):
            st.button(r["label"].replace("대구광역시 ", ""), icon=":material/star:", key=f"saved-{i}", type="tertiary",
                      on_click=go_tab, args=(TAB_UNIT,), kwargs={"unit_addr": r["unit_id"], "unit_whole": r["whole"]})
        st.button("후보지 비교·손익 계산", icon=":material/compare_arrows:", key="saved-compare", width="stretch",
                  on_click=go_tab, args=(TAB_PLAN,))
    else:
        st.caption("자리 이력에서 ‘내 후보지에 저장’을 누르면 여기 모여요.")

    st.markdown("**최근 본 자리**")
    recent_slot = st.empty()
    render_recent_units()

    st.markdown("**AI 상담**")
    with st.container(border=True):
        if OPERATOR_KEY:
            quota_slot = st.empty()
            render_quota()
            st.caption(PROVIDER_LABEL)
        else:
            # 방문자 키 입력은 두지 않는다(2026-11-15). 운영 키가 없으면 안내만 한다.
            st.markdown(":material/block: 지금은 이용할 수 없어요")
            st.caption("상권 둘러보기·자리 이력은 그대로 이용할 수 있어요.")
        with st.expander("예시 질문 (누르면 바로 질문)", expanded=fav_on):
            for q in fav_examples(st.session_state.fav_gu, st.session_state.fav_industry):
                st.button(q, key=f"ex-{q}", type="tertiary", icon=":material/chat_bubble:",
                          on_click=go_tab, args=(TAB_CHAT,), kwargs={"pending": q})
        if st.button("대화 초기화", icon=":material/refresh:", width="stretch"):
            st.session_state.pop("agent", None)
            st.session_state.pop("agent_sig", None)
            st.session_state.history = []
            st.rerun()

    with st.expander("용어 도움말", icon=":material/help:"):
        st.markdown("\n".join(f"- **{k}**: {v}" for k, v in GLOSSARY))

tab_dash, tab_unit, tab_plan, tab_chat = st.tabs([TAB_DASH, TAB_UNIT, TAB_PLAN, TAB_CHAT], key="main_tab",
                                                 on_change="rerun")


# ─────────────────────────── 1. AI 상담 ───────────────────────────
def safe_markdown(text: str) -> str:
    """물결표를 escape 한다.

    "15~29세가 28.1%, 30~49세"처럼 범위 표기가 두 번 나오면 마크다운이 ~...~ 를 취소선으로 해석해
    물결표가 사라지고 "1529세가 28.1%, 3049세"로 보인다. 코드 블록 밖의 ~ 만 escape 한다.
    """
    parts = text.split("```")
    for i in range(0, len(parts), 2):  # 짝수 인덱스 = 코드 블록 바깥
        parts[i] = parts[i].replace("~", "\\~")
    return "```".join(parts)


def render_tools(tool_events: list[dict], msg_id: str):
    """접힌 '데이터 n번 확인'(단계·원자료) 다음에 차트·지도 등 결과 그림을 보여 준다."""
    render_tool_steps(tool_events)
    for i, ev in enumerate(tool_events):
        if not ev["error"]:
            render_tool_result(ev["name"], ev["output"], key=f"{msg_id}-{i}")


# AI 상담 화면(2026-11-15): 대화는 위에서 아래로 쌓이고, 입력창은 화면 아래에 고정한다.
# 탭 상태(main_tab)를 추적하므로 AI 상담 탭이 열려 있을 때만 하단 입력창을 그린다(다른 탭에는 보이지 않음).
chat_prompt = None
if tab_chat.open:
    with st.bottom:
        chat_prompt = st.chat_input("상권·자리에 대해 물어보세요. 예) 수성구 범어동에서 치킨집 하면 어때?",
                                    submit_mode="disable", key="chat_box")
        st.caption(f"답변은 {PROVIDER_LABEL} API로 생성됩니다"
                   + ("(무료 등급 입력은 제공사의 서비스 개선에 쓰일 수 있음)" if PROVIDER == "gemini" else "")
                   + ". 수치는 인허가 데이터 분석 도구의 반환값만 쓰며, 창업 판단의 참고 자료입니다.")

with tab_chat:
    st.session_state.setdefault("history", [])
    prompt = chat_prompt or st.session_state.pop("pending", None)
    # 첫 화면 자리는 항상 만든다: 첫 질문을 보내는 실행에서 빈 자리로 바뀌어 예전 버튼이 흐리게 남지 않는다
    welcome = st.empty()
    if not st.session_state.history and not prompt:
        with welcome.container():
            # 첫 화면: 무엇을 물을 수 있는지 보여 주고 예시 질문을 바로 누를 수 있게 한다
            st.markdown("### 무엇을 알아볼까요?")
            st.caption("동네 비교, 업종 생존 기간, 빈 자리, 한 자리의 과거 이력을 인허가 기록으로 답해 드려요.")
            qs = fav_examples(st.session_state.get("fav_gu", "대구 전체"), st.session_state.get("fav_industry", "전체 업종"))
            qs = [q for q in qs if not q.startswith(("그럼", "그 동네"))]   # 앞 대화가 필요한 질문은 첫 화면에서 뺀다
            cols = st.columns(2)
            for i, q in enumerate(qs[:4]):
                cols[i % 2].button(q, key=f"start-{i}", icon=":material/chat_bubble:", width="stretch",
                                   on_click=go_tab, args=(TAB_CHAT,), kwargs={"pending": q})
    for m in st.session_state.history:
        with st.chat_message(m["role"]):
            if m["role"] == "assistant":
                render_tools(m.get("tools", []), m["id"])
            st.markdown(ai_markdown(m["content"]), unsafe_allow_html=True)
            if m.get("model"):
                st.caption(f"모델: {m['model']}")

    if prompt:
        api_key = OPERATOR_KEY
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            if not api_key:
                st.error("지금은 AI 상담을 이용할 수 없어요. 상권 둘러보기·자리 이력 탭은 그대로 이용할 수 있습니다.")
                st.stop()
            blocked = take_quota()
            if blocked:
                st.warning(blocked)
                st.stop()
            st.session_state.history.append({"role": "user", "content": prompt})
            agent = get_agent(api_key)
            msg_id = uuid.uuid4().hex[:8]
            tool_box = st.empty()   # 진행 중에는 단계 목록, 끝나면 접힌 기록+그림으로 바꿔 그린다
            text_box = st.empty()
            text, tool_events, model, live = "", [], None, []
            with st.spinner("데이터 확인 중…"):
                for ev in agent.ask(prompt):
                    if ev["type"] == "text":
                        text += ev["text"]
                        text_box.markdown(ai_markdown(text) + "▌", unsafe_allow_html=True)
                    elif ev["type"] == "tool_call":
                        live.append(tool_label(ev["name"], ev.get("input")))
                        tool_box.markdown("  \n".join([f":material/check: {x}" for x in live[:-1]]
                                                       + [f":shimmer[{live[-1]}]"]))
                    elif ev["type"] == "tool_result":
                        tool_events.append(ev)
                    elif ev["type"] == "done":
                        model = ev.get("model")
                    elif ev["type"] == "error":
                        text += f"\n\n⚠️ {ev['message']}"
            text_box.empty()
            with tool_box.container():
                render_tools(tool_events, msg_id)
            st.markdown(ai_markdown(text), unsafe_allow_html=True)
            if model:
                st.caption(f"모델: {model}")
        st.session_state.history.append({"role": "assistant", "content": text, "tools": tool_events,
                                         "id": msg_id, "model": model})


# ─────────────────────────── 2. 대시보드 ───────────────────────────
with tab_dash:
    st.title("내 업종에 맞는 동네 살펴보기")
    st.caption("지역과 업종을 고르면 영업 현황과 최근 변화를 비교할 수 있어요.")
    st.caption(f"자료 기준 {S.ref:%Y-%m-%d} · 수록 인허가 기준")
    gu_sel = st.selectbox("살펴볼 지역", ["대구 전체"] + GUS, key="dash_gu",
                          on_change=lambda: st.session_state.update(fav_gu=st.session_state.dash_gu))
    gu = None if gu_sel == "대구 전체" else gu_sel
    view = st.radio("살펴볼 내용", ["업종 비교", "동네·자리", "상세 통계"], horizontal=True, key="dash_view", label_visibility="collapsed")
    if view == "업종 비교":
        render_permit_trends(S.stores, S.ref, gu, S.legal_admin)
    elif view == "동네·자리":
        st.subheader("동네의 생활 여건과 자리 살펴보기")
        st.caption("인구·집객시설을 확인하고, 관심 주소는 상단 ‘자리 이력’에서 이전 영업 이력을 확인하세요.")
        vac = T.find_vacant_units(gu=gu, limit=1000)
        if S.area_context is not None:
            st.subheader("동네 프로필 (상가정보 · 인구 · 집객시설)")
            ctx = S.area_context if not gu else S.area_context[S.area_context["gu"] == gu]
            c1, c2 = st.columns([1, 2])
            with c1:
                dong_sel = st.selectbox("행정동", sorted(ctx["admin_dong"].unique()), key="dash_dong")
                prof = T.get_area_profile(gu=ctx[ctx["admin_dong"] == dong_sel]["gu"].iat[0], dong=dong_sel)
                st.metric("상권 유형", prof["market_type"])
                st.caption(prof["market_type_basis"])
                st.metric("업종 다양성 지수", f"{prof['diversity_index']}", f"대구 {prof['city_diversity_index']}", delta_color="off", delta_arrow="off")
                pop = prof["population"]
                if pop.get("total"):
                    st.metric("주민등록 인구", f"{int(pop['total']):,}명",
                              f"15~29세 {pop['age_15_29_pct']}% · 65세+ {pop['age_65_plus_pct']}%", delta_color="off", delta_arrow="off")
                f = prof["facilities"]
                st.caption(f"전통시장 {f['traditional_markets']}곳 · 주차장 {f['parking_lots']}곳({f['parking_slots']:,}면)")
            with c2:
                render_tool_result("get_area_profile", prof, key="dash-profile")
                st.caption("현재 영업 점포 " + f"{prof['stores_now']:,}개 중 음식 {prof['food_stores_now']:,}개 · 주요 업종 "
                           + ", ".join(f"{k} {v}" for k, v in prof["top_categories"].items()))

            # A-07 1년 뒤 거주 인구 · A-09 비슷한 동네(자료가 없는 버전이면 카드를 숨긴다)
            dong_gu = ctx[ctx["admin_dong"] == dong_sel]["gu"].iat[0]
            if S.population_forecast is not None:
                render_population_outlook(dong_gu, dong_sel)
            if S.similar_areas is not None:
                render_similar_areas(dong_gu, dong_sel)

            types = ctx.groupby("market_type").size().sort_values(ascending=False)
            st.caption("상권 유형 분포: " + " · ".join(f"{k} {v}곳" for k, v in types.items()))

        if S.station is not None and not gu:
            st.subheader("도시철도 역별 일평균 승하차 (유동인구 대리지표)")
            render_tool_result("get_station_traffic", T.get_station_traffic(top_n=15), key="dash-station")

        st.subheader("인허가 공백 후보 지도")
        st.caption(f"전체 후보 {vac['total_vacant']:,}곳 중 목록 {vac['shown']:,}곳을 조회했습니다. 지도에서는 좌표가 없는 기록이 빠질 수 있습니다.")
        st.caption(safe_markdown(vac["basis"]["definition"] + " · " + vac["basis"]["caveat"]))
        _map(vac["units"], "vacant_days", ["last_store", "last_category", "vacant_days", "closures_since_2010"], key="dash-map")

    else:
        st.subheader("지역 전체의 과거 영업 통계")
        st.caption("이 화면은 선택 지역의 전체 업종 기준입니다. 앞 화면의 관심 업종 선택은 적용되지 않습니다.")
        cyc = T.get_market_cycle(gu)
        surv = T.get_survival_curve(gu=gu)
        vac = T.find_vacant_units(gu=gu, limit=1000)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("상권 사이클", cyc["stage"], f"개업/폐업 {cyc['open_close_ratio_recent']} (직전 {cyc['open_close_ratio_prev']})", delta_color="off", delta_arrow="off", border=True)
        k2.metric("중앙생존기간 (2010~ 개업)", metric_value(surv["median_survival_years"], "년", "관찰기간 내 미도달"), "대구 " + metric_value(surv["daegu_baseline_same_cohort"]["median_survival_years"], "년", "관찰기간 내 미도달"), delta_color="off", delta_arrow="off", border=True)
        k3.metric("1년 내 폐업 신고 추정치", metric_value(surv["close_within_1y_pct"], "%"), f"n={surv['n']:,}", delta_color="off", delta_arrow="off", border=True)
        k4.metric("인허가 공백 후보 (90일~3년)", f"{vac['total_vacant']:,}곳", border=True)

        st.caption(f"기준일: {surv['basis']['reference_date']} · 대상: {surv['target']} · {surv['basis']['cohort']} · 표본 {surv['n']:,}건")
        st.caption("1년 내 폐업 신고 추정치는 100%−Kaplan–Meier 1년 생존율입니다. 표본 전체 중 신고 건수의 단순 비율이나 새 점포의 개별 예측 확률이 아닙니다.")
        st.caption("폐업 신고는 실제 사업 실패와 같지 않으며 행사장 영업 종료 등이 포함될 수 있습니다. 인허가 공백 후보는 실제 공실·임대 매물 여부를 확인한 결과가 아닙니다.")
        with st.expander("집계 대상과 기준 자세히 보기"):
            _n_src = len(services)
            _n_grp = len({"의원·병원" if s in ("의원", "병원") else s for s in services})
            st.caption(f"원천 업종명은 {_n_src}개이며, 분석 보고서는 의원·병원을 합쳐 {_n_grp}그룹으로 집계합니다. "
                       "서비스의 원천 업종 조회에서는 의원·병원을 각각 유지합니다.")
            _se = META.get("quality", {}).get("short_event_excluded_from_stats")
            if _se:
                st.caption(f"백화점·마트 식품관 등 다점포 자리에서 {C.SHORT_EVENT_MAX_DAYS}일 이내 폐업한 단기 행사·팝업 등록 "
                           f"대구 전체 {_se['occupants']:,}곳은 생존율·상권 사이클·개폐업 통계에서 제외했습니다(자리 이력에는 표시).")
            if META.get("quality", {}).get("occupants"):
                st.caption("같은 자리·같은 상호로 기간이 겹치는 인허가(예: 편의점의 담배소매업+휴게음식점)는 한 가게로 묶어 "
                           "자리·공백·생존·교체를 계산합니다. 누적 인허가 수는 묶기 전 건수입니다.")

        left, right = st.columns(2)
        with left:
            st.subheader("업태별 중앙생존기간")
            survival_chart(T.get_survival_curve(gu=gu, group_by="category", min_n=100 if gu else 300), key="dash-surv")
        with right:
            st.subheader("연도별 개업·폐업")
            cycle_chart(cyc, key="dash-cycle")

        st.subheader("구·군 비교" if not gu else f"{gu} 동별 비교 (표본 상위)")
        if not gu:
            render_tool_result("compare_areas", T.compare_areas(GUS), key="dash-compare")
        else:
            rank = T.get_survival_curve(gu=gu, group_by="dong", min_n=150, top_n=40)
            vac_d = S.vacancy[(S.vacancy["level"] == "동") & (S.vacancy["gu"] == gu)][["dong", "units_3y", "vacancy_rate_pct"]]
            cyc_d = S.cycle[(S.cycle["level"] == "동") & (S.cycle["gu"] == gu)][["dong", "stage", "open_close_ratio_recent"]]
            df = (pd.DataFrame(rank["ranking_by_median_survival"])[["dong", "n", "median_survival_years", "survival_1y_pct", "survival_3y_pct"]]
                  .merge(vac_d, on="dong", how="left").merge(cyc_d, on="dong", how="left"))
            df.columns = ["동", "표본", "중앙생존(년)", "1년 생존%", "3년 생존%", "최근3년 자리", "인허가 공백 후보율%", "사이클", "개폐업비"]
            st.dataframe(df, hide_index=True, width="stretch")

        with st.expander("데이터 품질과 산출 방법"):
            q = META["quality"]
            st.markdown(safe_markdown(f"""
    - **레코드**: 원본 {q['raw_rows']:,}건 · 중복 제거 {q['duplicates_removed']}건 · 인허가일 결측 {q['missing_license_date']}건 · 날짜 모순 {q['date_contradiction']}건 · 대구 외 주소 {q['non_daegu_address']}건 제외
    - **좌표 채움률**: {', '.join(f'{k} {v}%' for k, v in q['coord_fill_pct'].items())} (EPSG:5174 → WGS84 변환)
    - **문제1 공실 과대판정**: 공실 상태 자리의 공백기간 분포 {META['vacancy_buckets_all_vacant_units']} → 90일~3년 인허가 공백 후보 **{META['recent_vacancy_units']:,}곳**
    - **문제2 다점포 건물**: 동시영업 수로 판별, 단일 점포 자리 비율 **{META['single_unit_ratio_pct']}%** · 전체 최다 폐업 {META['max_closures_all_units_top5'][0]['n_closed']}건({META['max_closures_all_units_top5'][0]['addr']}) → 단일 점포 기준 최다 {META['max_closures_single_units_top5'][0]['n_closed']}건
    - **문제4 업종 확장**: 업종 간 전환(예: 일반음식점 → 휴게음식점)으로 현재 영업 중인 자리 **{META['service_switch_units']:,}곳** (한 업종만 봤다면 공실로 오판)
    """))
            if S.poi is not None:
                poi_food = int((S.poi["cat_l"] == "음식").sum())
                poi_bakery = int(S.poi["cat_s"].fillna("").str.contains("제과|베이커리|빵").sum())
                st.markdown(safe_markdown(
                    f"- **출처별 수록 범위**: 인허가 자료의 전체 업종 영업 중 기록은 {rec['active']:,}건, "
                    f"소상공인 상가정보 {C.POI_MONTH}의 음식·제과·베이커리 점포는 {poi_food + poi_bakery:,}개입니다. "
                    "업종 범위·집계 단위·수집 시점이 달라 두 수치의 일치 여부로 정확도를 판단할 수 없습니다.\n"
                    f"- **누적과 현재**: 누적 인허가 {rec['total']:,}건에는 과거 폐업 신고 {rec['closed']:,}건도 포함됩니다. "
                    "개업 시기별 관찰기간이 다르므로 단순 폐업 비율을 같은 조건의 위험도로 비교하지 않습니다."))
            st.markdown("**문제3 생존편향** — 개업 연대별 1년 생존율 (그래서 생존분석은 2010년 이후 개업만)")
            st.dataframe(pd.DataFrame(META["survival_by_decade_1y"]), hide_index=True)




# ─────────────────────────── 3. 자리 이력 ───────────────────────────
with tab_unit:
    st.title("관심 있는 자리의 이력 확인")
    st.caption("주소나 상호로 찾아보세요. 이전 업종과 영업기간, 해당하는 경우 재입점 전망을 함께 확인할 수 있어요.")
    addr = st.text_input("주소 또는 상호", placeholder="예) 대구 중구 동성로5길 83 / 삼덕동1가 28-6 / 빽다방 대구군위점",
                         key="unit_addr")
    whole = st.checkbox("층 구분 없이 건물 전체 보기", key="unit_whole")
    h = None
    if addr:
        try:
            h = T.get_unit_history(addr, whole_building=whole)
        except T.AmbiguousAddressError as e:
            # 서로 다른 건물이 걸리면 임의로 고르지 않고 사용자가 고르게 한다. 고른 자리 ID 로 다시 조회한다.
            opts = e.candidates
            st.info(f"'{addr}'에 해당하는 건물이 여러 곳입니다. 원하는 주소를 고르세요.")
            pick = st.selectbox("주소 후보", range(len(opts)), index=None, placeholder="주소 선택",
                                format_func=lambda i: f"{opts[i]['address']} — 인허가 {opts[i]['records']}건, {opts[i]['status']}",
                                key=f"unit-pick-{addr}")
            if pick is not None:
                h = T.get_unit_history(opts[pick]["unit_id"], whole_building=whole)
        except T.ToolError as e:
            st.warning(str(e))
        if h:
            u = h["unit"]
            remember_unit(u["address"] + (" (건물 전체)" if whole else ""), u["unit_id"], whole)
            st.markdown(f"### {u['address']}")
            st.caption(f"자리 ID: {u['unit_id']} · {u['status']}")
            P.render_save_button(u["unit_id"], u["address"] + (" (건물 전체)" if whole else ""), whole)
            if h.get("floor_note"):
                st.info(h["floor_note"] + " (아래 '다른 후보 자리' 참고)")
            if not u["is_single_unit"]:
                st.info(u["single_unit_note"])
            # 요약을 맨 위로(2026-11-14): 지금 상태 → 재입점 카드 → 과거 이력 → 상세 표(접기)
            render_unit_summary(h, whole_building=whole)
            render_vacancy_outlook(h.get("vacancy_outlook"))
            render_next_tenant(h.get("next_tenant_outlook"))
            P.render_nearby(h, key=f"{u['unit_id']}-{whole}")
            st.markdown("#### 이 자리의 과거")
            s = h["summary"]
            c = st.columns(4)
            c[0].metric("인허가 레코드", s["total_records"])
            c[1].metric("2010년 이후 폐업", s["closures_since_2010"])
            c[2].metric("2010년 이후 폐업점 평균 존속", f"{s['avg_years_closed_since_2010'] or '-'}년")
            c[3].metric("최대 동시영업", u["max_concurrent_stores"])
            st.caption("업태 변천: " + s["category_path"])
            history_chart(h, key="unit-tl")
            # 가게별 영업기간을 대구 같은 업태 가게와 같은 잣대로 비교(문장). 최근 5곳, 나머지는 접기
            _ts = tenure_sentences(h)
            if _ts:
                st.markdown("**대구 같은 업태 가게와 비교하면**")
                st.markdown("\n".join(f"- {x}" for x in _ts[:5]))
                if len(_ts) > 5:
                    with st.expander(f"나머지 {len(_ts) - 5}곳 더 보기"):
                        st.markdown("\n".join(f"- {x}" for x in _ts[5:]))
                st.caption("비율은 대구 같은 업태(2010년 이후 개업) 가게의 생존율입니다. 짧은 편: 75% 이상이 더 오래 영업, "
                           "긴 편: 더 오래 영업한 가게가 25% 미만. 영업 중인 가게는 아직 진행 중인 기간입니다.")
            st.markdown("#### 상세 기록")
            st.markdown("**전체 인허가 기록**")
            _tl = korean_table(h["timeline"], TIMELINE_COLS)
            if "영업기간(년)" in _tl.columns:          # 영업 중인 가게는 기준일까지의 진행 중 기간
                _tl["영업기간(년)"] = [f"{y} (영업 중)" if c == "영업 중" else f"{y}" for y, c in zip(_tl["영업기간(년)"], _tl["폐업일"])]
            if not u["is_single_unit"] and "직전 폐업 후 공백(일)" in _tl.columns:
                _tl = _tl.drop(columns="직전 폐업 후 공백(일)")
                st.caption("여러 가게가 함께 있던 자리라 다른 가게가 영업 중일 때도 '공백'으로 계산되므로 직전 폐업 후 공백은 표시하지 않아요.")
            if "단기 행사 등록" in _tl.columns and not _tl["단기 행사 등록"].astype(bool).any():
                _tl = _tl.drop(columns="단기 행사 등록")
            # 기본 height="auto" = 최대 10줄 높이, 기록이 많은 자리는 표 안에서 스크롤
            st.dataframe(_tl, hide_index=True, width="stretch")
            if h["other_candidates"]:
                st.markdown("**다른 후보 자리**")
                st.dataframe(korean_table(h["other_candidates"], CANDIDATE_COLS), hide_index=True)



# ─────────────────────────── 4. 내 후보지 ───────────────────────────
# 2026-11-21 추가: 저장한 후보지 비교 · 손익분기 계산기 (후보지는 브라우저에 저장)
def _open_saved(r: dict) -> None:
    go_tab(TAB_UNIT, unit_addr=r["unit_id"], unit_whole=r["whole"])


with tab_plan:
    st.title("내 후보지 비교와 손익 계산")
    st.caption("저장한 자리를 나란히 비교하고, 월세·비용을 넣어 본전이 되는 판매량을 계산해 보세요.")
    P.render_compare(_open_saved)
    st.divider()
    P.render_calculator()
