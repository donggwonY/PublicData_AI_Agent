"""에이전트 Tool 8종.

모든 Tool 은 야간 배치 산출물(data/processed)을 조회만 하며,
반환값에 근거 수치(표본 수, 기간, 정의)를 반드시 포함한다 — 환각 방지 (기획서 8장).

같은 함수를 세 곳이 부른다: AI 에이전트(agent.py), 웹 대시보드(app.py), MCP 서버(mcp_server.py).
그래서 어디서 보든 같은 숫자가 나온다.

파일 구조
    DataStore / store()   parquet 7개를 프로세스당 한 번 읽어 두는 보관소
    _py, _basis, ...      공통 헬퍼 (약 150줄). Tool 을 읽기 전에 이것부터 보면 빠르다
    Tool 1~8              같은 틀의 반복: 입력 해석 → 필터링 → 계산 → 근거와 함께 dict 반환

Tool 이 지키는 공통 규칙
    - 입력이 애매하면 추측하지 않고 ToolError 를 던져 AI 가 사용자에게 되묻게 한다
    - 표본 수(n)를 반드시 함께 돌려준다
    - 추정할 수 없는 값은 0 이 아니라 None 으로 둔다
    - 목록은 limit 으로 잘라 AI 에게 보내는 양을 제한한다
"""
from __future__ import annotations

import json
import math
from datetime import date
from functools import lru_cache

import numpy as np
import pandas as pd

import config as C
from core import address as A
from core.cycle import classify_stage
from core.survival import YEAR, summarize


class ToolError(ValueError):
    """사용자 입력으로 결과를 만들 수 없을 때 — 에이전트에게 is_error 로 전달된다.

    '입력이 잘못됨'(없는 구 이름)과 '코드 버그'(KeyError 등)를 구분하려고 따로 만든 예외다.
    ToolError 메시지는 AI 에게 그대로 전달돼 사용자에게 되묻는 데 쓰이고,
    그 밖의 예외는 "Tool 실행 중 오류"로 따로 알린다(agent.run_tool).
    """


# ─────────────────────────── 데이터 로딩 ───────────────────────────
class DataStore:
    """배치 산출물 7개 + meta.json 을 메모리에 올려 두는 보관소.

    12만 행이라 통째로 올려도 부담이 없고, 모든 Tool 이 이 표들을 걸러 쓰기만 한다.
    """

    def __init__(self, processed_dir=C.PROCESSED_DIR):
        if not (processed_dir / "meta.json").exists():
            raise FileNotFoundError(f"{processed_dir} 에 배치 산출물이 없습니다. `python -m pipeline.build` 를 먼저 실행하세요.")
        rd = lambda n: pd.read_parquet(processed_dir / f"{n}.parquet")  # noqa: E731
        self.meta = json.loads((processed_dir / "meta.json").read_text(encoding="utf-8"))
        self.stores = rd("stores")
        self.units = rd("units").set_index("uid", drop=False)
        self.transitions = rd("transitions")
        self.cycle = rd("area_cycle")
        self.area_year = rd("area_year")
        self.survival = rd("survival")
        self.vacancy = rd("vacancy_area")
        # 보조 데이터(상가정보·인구·지하철 등). pipeline/external.py 를 돌리지 않았으면 None 이고,
        # 해당 Tool 만 "데이터 없음"으로 안내한다 — 기존 8종은 그대로 동작한다.
        def opt(name):
            path = processed_dir / f"{name}.parquet"
            return pd.read_parquet(path) if path.exists() else None

        self.poi = opt("poi")
        self.area_context = opt("area_context")
        self.legal_admin = opt("legal_admin_map")
        self.station = opt("station_traffic")
        self.parking = opt("parking")
        self.market = opt("market")

        self.ref = pd.Timestamp(self.meta["reference_date"])          # 분석 기준일
        self.categories = sorted(self.stores["category"].unique())     # 실제 존재하는 업태 목록(입력 검증용)
        self.dongs = self.units[["gu", "dong"]].dropna().drop_duplicates()  # 구-동 조합(동 이름 해석용)


@lru_cache(maxsize=1)
def store() -> DataStore:
    """DataStore 를 프로세스당 한 번만 만든다.

    @lru_cache 는 '같은 인자로 부르면 계산하지 않고 저장해 둔 결과를 준다'는 뜻이다.
    덕분에 웹 방문자가 아무리 많아도 parquet 읽기는 서버 시작 후 한 번뿐이다.
    표를 읽기만 하고 고치지 않으므로 여러 방문자가 공유해도 안전하다.
    """
    return DataStore()


# ─────────────────────────── 공통 헬퍼 ───────────────────────────
def _py(v):
    """numpy / pandas 값을 JSON 직렬화 가능한 파이썬 값으로.

    pandas 가 돌려주는 값은 numpy 자료형(np.int64 등)이라 json.dumps 가 거부한다.
    결측값도 종류별로 달라서(NaN, NaT, pd.NA) 전부 None 으로 통일한다.
    dict·list 안까지 재귀로 훑는다.
    """
    if isinstance(v, dict):
        return {k: _py(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_py(x) for x in v]
    if isinstance(v, (pd.Timestamp, date)):
        return None if pd.isna(v) else str(v.date() if isinstance(v, pd.Timestamp) else v)
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    if v is pd.NaT or v is pd.NA:
        return None
    return v


def _basis(**extra) -> dict:
    """모든 Tool 결과에 붙는 '근거' 블록 — 환각 방지 장치.

    출처·기준일·정의·한계를 숫자와 함께 돌려주면, AI 가 "2010년 이후 개업 기준"처럼
    조건을 밝히며 답할 수 있고 없는 숫자를 지어낼 여지가 줄어든다.
    """
    s = store()
    return {"data": f"행정안전부 지방행정 인허가(대구 {_services_label()})",
            "reference_date": s.meta["reference_date"], **extra}


@lru_cache(maxsize=1)
def _services_label() -> str:
    """'일반음식점·휴게음식점·제과점영업' — 업종을 확장해도 안내 문구가 따라오도록 meta 에서 만든다."""
    return "·".join(k for k in store().meta["records"] if k != "통합")


def _resolve_area(gu: str | None = None, dong: str | None = None) -> tuple[str | None, list[str] | None, str]:
    """사람이 말한 지역명 → (구, 동 목록, 표시용 이름).

    AI 가 넘기는 인자는 사용자가 말한 그대로일 때가 많다("수성", "범어", "삼덕동").
    맞는 이름을 찾지 못하거나 여러 구에 같은 동이 있으면 ToolError 로 되묻는다 — 조용히 아무 데나 고르면
    AI 가 엉뚱한 지역 숫자를 사실처럼 말하게 된다.
    """
    s = store()
    g = A.normalize_gu(gu) if gu else None
    if gu and not g and gu.strip().endswith(("구", "군")):
        raise ToolError(f"'{gu}'는 대구의 구·군이 아닙니다 (중구, 동구, 서구, 남구, 북구, 수성구, 달서구, 달성군, 군위군).")
    if gu and not g and not dong:  # 구 자리에 동 이름을 넣은 경우
        dong = gu
    d = None
    if dong:
        text = dong.replace(A.SIDO, "").replace("대구", "").strip()
        parts = text.split()
        if len(parts) > 1 and A.normalize_gu(parts[0]):
            g = g or A.normalize_gu(parts[0])
            text = parts[-1]
        # '삼덕동' → 삼덕동(수성구) + 삼덕동1가~3가(중구) 모두 후보
        names = s.dongs["dong"]
        cand = s.dongs[(names == text) | names.str.startswith(text)]
        if cand.empty:
            cand = s.dongs[names.str.startswith(text.rstrip("동읍면"))]
        if g:
            cand = cand[cand["gu"] == g]
        if cand.empty:
            raise ToolError(f"'{dong}'에 해당하는 동·읍·면을 찾지 못했습니다 (법정동 기준, 예: 범어동, 삼덕동1가, 다사읍).")
        if cand["gu"].nunique() > 1:
            opts = cand.groupby("gu")["dong"].apply(lambda x: ", ".join(sorted(x))).to_dict()
            raise ToolError(f"'{dong}'이(가) 여러 구에 있습니다: {opts}. 구를 함께 지정하세요.")
        g = cand["gu"].iat[0]
        d = sorted(cand["dong"].unique())
    elif gu and not g:
        raise ToolError(f"'{gu}'는 대구의 구·군이 아닙니다 (중구, 동구, 서구, 남구, 북구, 수성구, 달서구, 달성군, 군위군).")
    label = "대구 전체" if not g else (g if not d else f"{g} {', '.join(d)}")
    return g, d, label


def _area_mask(df: pd.DataFrame, g, d) -> pd.Series:
    m = pd.Series(True, index=df.index)
    if g:
        m &= df["gu"] == g
    if d:
        m &= df["dong"].isin(d)
    return m


def _resolve_category(text: str | None) -> tuple[str | None, list[str] | None, str]:
    """반환: (service, categories, label). 업종명(config.SERVICES)과 업태·별칭 모두 허용.

    "카페"처럼 데이터에 없는 일상어는 config.CATEGORY_ALIASES 로 실제 업태 여러 개(커피숍·까페·다방…)에 매핑한다.
    label 은 "카페(커피숍, 까페, 다방)"처럼 무엇을 합쳤는지 사용자에게 밝히기 위한 문자열이다.
    """
    if not text:
        return None, None, "전체 업태"
    t = text.strip()
    s = store()
    if t in C.SERVICES:
        return t, None, t
    if t in s.categories:
        return None, [t], t
    key = t.replace(" ", "")
    if key in C.CATEGORY_ALIASES:
        cats = [c for c in C.CATEGORY_ALIASES[key] if c in s.categories]
        if cats:
            return None, cats, f"{t}({', '.join(cats)})"
    cats = [c for c in s.categories if key in c.replace(" ", "")]
    if cats:
        return None, cats, f"{t}({', '.join(cats)})"
    raise ToolError(f"업태 '{text}'를 찾지 못했습니다. 사용 가능한 업태: {', '.join(s.categories)}")


def _cat_mask(df: pd.DataFrame, service, cats, cat_col="category", service_col="service") -> pd.Series:
    m = pd.Series(True, index=df.index)
    if service:
        m &= df[service_col] == service
    if cats:
        m &= df[cat_col].isin(cats)
    return m


def _years(days) -> float | None:
    return None if days is None or pd.isna(days) else round(float(days) / YEAR, 1)


SHORT_LIVED_DAYS = 30
SHORT_LIVED_WARN_PCT = 10


def _survival(frame: pd.DataFrame, curve=True) -> dict:
    out = summarize(frame["dur_days"], frame["closed"])
    if out["median_survival_years"] is None and out["n"]:
        out["median_note"] = "관측기간 내 생존율이 50% 아래로 떨어지지 않음(중앙생존기간 추정 불가)"
    # 백화점 팝업·행사 매장은 며칠 만에 인허가가 끝나 생존율을 끌어내린다.
    # 비중이 크면 숫자와 함께 알려 AI 가 "1년 생존율이 낮다"를 단정하지 않게 한다.
    closed = frame[frame["closed"]]
    if len(closed):
        pct = round(float((closed["dur_days"] <= SHORT_LIVED_DAYS).mean() * 100), 1)
        out["short_lived_closures_pct"] = pct
        if pct >= SHORT_LIVED_WARN_PCT:
            out["short_lived_note"] = (f"폐업의 {pct}%가 {SHORT_LIVED_DAYS}일 이내 — 백화점 팝업·행사 매장이 섞여 "
                                       "생존율이 실제 상설 점포보다 낮게 보일 수 있음")
    if not curve:
        out.pop("curve")
    return out


def _unit_brief(u: pd.Series) -> dict:
    status = (f"영업중 {int(u['n_active'])}개 ({u['current_stores']})" if not u["vacant"]
              else f"인허가 공백 {int(u['vacant_days'])}일째 (마지막 폐업 {u['last_close'].date()})")
    return {
        "unit_id": u["uid"], "address": u["addr"], "jibun_address": u["jibun_addr"], "floor": u["floor"],
        "gu": u["gu"], "dong": u["dong"], "records": int(u["n_records"]), "status": status,
        "lat": u["lat"], "lon": u["lon"],
    }


# ─────────────────────────── Tool 1. normalize_address ───────────────────────────
def normalize_address(query: str, limit: int = 10) -> dict:
    """주소·상호 문자열을 '자리(unit)' 후보로 정규화.

    아래 네 방법을 정확한 것부터 차례로 시도하고, 처음 걸리는 결과를 쓴다.
        1 지번 기본주소 일치   2 도로명 기본주소 일치   3 주소 토큰 포함 검색   4 상호명 검색
    어떤 방법으로 찾았는지(method)도 함께 돌려주어, AI 와 사용자가 신뢰도를 판단할 수 있게 한다.
    """
    s = store()
    u = s.units
    q = (query or "").strip()
    if not q:
        raise ToolError("주소 또는 상호를 입력하세요.")
    floor = A.extract_floor(q)
    hits, method = pd.Index([]), None

    jb = A.parse_jibun(q if q.startswith("대구") else f"{A.SIDO} {q}")
    if jb:
        hits, method = u.index[u["building_key"] == jb["key"]], "지번 기본주소 일치"
    if hits.empty:
        rd = A.parse_road(q if q.startswith("대구") else f"{A.SIDO} {q}")
        if rd:
            uids = s.stores.loc[s.stores["road_key"] == rd["key"], "uid"].unique()
            hits, method = pd.Index(uids), "도로명 기본주소 일치"
    if hits.empty:
        # 정규식이 실패한 주소(건물명만 있는 등)는 단어를 모두 포함하는 자리를 찾는다
        tokens = [t for t in q.replace(",", " ").split() if t not in ("대구", "대구시", A.SIDO)]
        hay = u["addr"] + " " + u["jibun_addr"]
        m = pd.Series(True, index=u.index)
        for t in tokens:
            m &= hay.str.contains(t, regex=False)  # regex=False: 괄호 같은 기호를 글자 그대로 취급
        hits, method = u.index[m], "주소 토큰 포함 검색"
    if hits.empty and len(q) >= 2:
        uids = s.stores.loc[s.stores["name"].str.contains(q, regex=False), "uid"].unique()
        hits, method = pd.Index(uids), "상호명 검색(과거 상호 포함)"
    if hits.empty:
        return _py({"query": query, "matched": 0, "matches": [],
                    "hint": "도로명(예: 동성로5길 83) 또는 지번(예: 삼덕동1가 28-6) 형식으로 다시 시도하세요."})

    cand = u.loc[hits]
    if floor:  # 질문에 "2층"이 있으면 같은 층을 우선하되, 없으면 후보를 버리지 않는다
        same = cand[cand["floor"] == floor]
        cand = same if not same.empty else cand
    cand = cand.sort_values("n_records", ascending=False)  # 이력이 많은 자리를 위로
    return _py({
        "query": query, "method": method, "matched": int(len(cand)),
        "matches": [_unit_brief(r) for _, r in cand.head(limit).iterrows()],
        "note": "자리(unit) = 건물 기본주소(지번) + 층. 층 기재가 없는 과거 레코드는 건물 내 주 사용 층으로 합산.",
    })


def _pick_unit(address: str) -> tuple[pd.Series, dict]:
    """가장 그럴듯한 자리 하나 + 나머지 후보 목록. 후보는 결과에 함께 실어 사용자가 고를 수 있게 한다."""
    res = normalize_address(address, limit=5)
    if not res["matched"]:
        raise ToolError(f"'{address}'에 해당하는 자리를 찾지 못했습니다. {res.get('hint', '')}")
    uid = res["matches"][0]["unit_id"]
    return store().units.loc[uid], res


# ─────────────────────────── Tool 2. get_unit_history ───────────────────────────
def get_unit_history(address: str, whole_building: bool = False, max_records: int = 40) -> dict:
    """한 자리의 업종 변천 이력 + 업태별 존속기간."""
    s = store()
    u, res = _pick_unit(address)
    key = "building_key" if whole_building else "uid"
    recs = s.stores[s.stores[key] == u[key]].sort_values(["ld", "cd"])
    prev_close, timeline = None, []
    for _, r in recs.iterrows():
        gap = (r["ld"] - prev_close).days if prev_close is not None else None
        timeline.append({
            "open": r["ld"], "close": r["cd"] if r["closed"] else "영업중",
            "name": r["name"], "service": r["service"], "category": r["category"], "floor": r["floor"],
            "years": _years(r["dur_days"]), "gap_from_previous_close_days": gap,
        })
        if r["closed"]:
            prev_close = r["cd"] if prev_close is None else max(prev_close, r["cd"])

    by_cat = (recs.groupby("category")
              .agg(stores=("name", "size"), closed=("closed", "sum"), avg_years=("dur_days", "mean"),
                   max_years=("dur_days", "max"))
              .assign(avg_years=lambda d: (d["avg_years"] / YEAR).round(1),
                      max_years=lambda d: (d["max_years"] / YEAR).round(1))
              .sort_values("avg_years", ascending=False).reset_index())
    daegu = s.survival[(s.survival["level"] == "업태") & s.survival["category"].isin(by_cat["category"])]
    by_cat = by_cat.merge(daegu[["category", "median_survival_years"]]
                          .rename(columns={"median_survival_years": "daegu_median_years_2010plus"}),
                          on="category", how="left")

    since = recs[recs["ld"].dt.year >= C.SURVIVAL_START_YEAR]
    return _py({
        "unit": _unit_brief(u) | {
            "max_concurrent_stores": int(u["max_concurrent"]),
            "is_single_unit": bool(u["is_single_unit"]),
            "single_unit_note": None if u["is_single_unit"] else "동시에 여러 점포가 영업한 다점포 건물/층(푸드코트·백화점 등)이라 '한 자리'의 교체 이력으로 해석하면 안 됨",
        },
        "summary": {
            "total_records": int(len(recs)), "closed": int(recs["closed"].sum()),
            "active": int((~recs["closed"]).sum()),
            "first_open": recs["ld"].min(), "closures_since_2010": int(since["closed"].sum()),
            "avg_years_closed_since_2010": _years(since.loc[since["closed"], "dur_days"].mean()),
            "category_path": " → ".join(recs["category"].tolist()[-12:]),
        },
        "by_category": by_cat.to_dict("records"),
        "timeline": timeline[-max_records:],
        "timeline_truncated": len(timeline) > max_records,
        "other_candidates": res["matches"][1:],
        "basis": _basis(definition="같은 자리(건물+층)의 인허가 레코드를 인허가일 순으로 정렬. gap = 직전 폐업일~이번 인허가일(음수는 양도·양수로 인한 중첩)."),
    })


# ─────────────────────────── Tool 3. get_survival_curve ───────────────────────────
def get_survival_curve(category: str | None = None, gu: str | None = None, dong: str | None = None,
                       since_year: int = C.SURVIVAL_START_YEAR, group_by: str | None = None,
                       min_n: int = 100, top_n: int = 20) -> dict:
    """Kaplan-Meier 생존곡선. group_by='category'|'gu'|'dong'|'service' 이면 그룹별 순위표.

    "카페 열려는데 어때?" → 업태 하나의 곡선,
    "뭐가 더 오래 가?"   → group_by="category" 로 업태 순위표.
    한 함수가 두 질문을 모두 받는 이유는, AI 가 부를 수 있는 Tool 수를 늘리지 않기 위해서다.
    """
    s = store()
    # 사람 말("카페", "수성") → 데이터의 정확한 값으로. 실패하면 여기서 ToolError 가 난다.
    service, cats, cat_label = _resolve_category(category)
    g, d, area_label = _resolve_area(gu, dong)
    since_year = int(since_year or C.SURVIVAL_START_YEAR)
    st = s.stores
    base = st[st["ld"].dt.year >= since_year]        # 코호트: 이 연도 이후 개업분만
    # 불리언 마스크를 & 로 결합해 조건을 한 번에 적용한다(pandas 의 기본 필터링 방식)
    frame = base[_area_mask(base, g, d) & _cat_mask(base, service, cats)]
    caveat = ("2010년 이전 개업분은 전산화 이전 단명 업소 누락으로 생존율이 과대추정됨(1990년대 1년 생존율 99.9%)."
              if since_year < C.SURVIVAL_START_YEAR else None)
    basis = _basis(cohort=f"{since_year}년 이후 인허가", area=area_label, category=cat_label,
                   method="Kaplan-Meier, 영업중 점포는 기준일에서 중도절단", caveat=caveat)

    if group_by:
        col = {"category": "category", "업태": "category", "gu": "gu", "구": "gu", "dong": "dong", "동": "dong",
               "service": "service", "업종": "service"}.get(group_by)
        if not col:
            raise ToolError("group_by 는 category, gu, dong, service 중 하나입니다.")
        rows = []
        for key, f in frame.groupby(col):
            if len(f) < min_n:  # 표본이 적은 그룹이 순위표 1위에 오르는 일을 막는다
                continue
            sm = _survival(f, curve=False)
            rows.append({col: key, **({"gu": f["gu"].iat[0]} if col == "dong" else {}), **sm})
        # 중앙생존기간 미도달(None)은 가장 오래 버틴 그룹이므로 맨 앞
        rows.sort(key=lambda r: -(r["median_survival_years"] if r["median_survival_years"] is not None else 99))
        return _py({"group_by": col, "min_n": min_n, "groups": len(rows),
                    "ranking_by_median_survival": rows[:top_n],
                    "shortest": rows[-min(5, len(rows)):][::-1] if len(rows) > top_n else None,
                    "overall": _survival(frame, curve=False), "basis": basis})

    if len(frame) < C.MIN_GROUP_N:
        raise ToolError(f"표본이 {len(frame)}건으로 너무 적습니다(최소 {C.MIN_GROUP_N}). 범위를 넓혀 주세요.")
    result = _survival(frame)
    baseline = _survival(base, curve=False)
    return _py({
        "target": f"{area_label} / {cat_label}", **result,
        "daegu_baseline_same_cohort": {k: baseline[k] for k in ("n", "median_survival_years", "survival_1y_pct", "survival_3y_pct", "survival_5y_pct")},
        "close_within_1y_pct": None if result["survival_1y_pct"] is None else round(100 - result["survival_1y_pct"], 1),
        "basis": basis,
    })


# ─────────────────────────── Tool 4. get_market_cycle ───────────────────────────
_CYCLE_COUNTS = ["open_recent", "close_recent", "open_prev", "close_prev", "active_now", "active_then"]


def _cycle_for(g: str, d: list[str] | None) -> tuple[pd.Series, pd.DataFrame]:
    """배치에서 계산한 사이클 행과 연도별 시계열. 여러 법정동(삼덕동1가~3가 등)은 합산 후 재판정."""
    s = store()
    cyc, ay = s.cycle, s.area_year
    if not d:
        return (cyc[(cyc["level"] == "구군") & (cyc["gu"] == g)].iloc[0],
                ay[(ay["level"] == "구군") & (ay["gu"] == g)])
    sub = cyc[(cyc["level"] == "동") & (cyc["gu"] == g) & cyc["dong"].isin(d)]
    series = ay[(ay["level"] == "동") & (ay["gu"] == g) & ay["dong"].isin(d)]
    if len(d) == 1:
        return sub.iloc[0], series
    counts = sub[_CYCLE_COUNTS].sum()
    row = pd.Series({**counts.to_dict(), **classify_stage(*counts.tolist()),
                     "window_recent": sub["window_recent"].iat[0], "window_prev": sub["window_prev"].iat[0]})
    series = (series.groupby("year", as_index=False)[["opens", "closes", "active_end_of_year"]].sum()
              .assign(partial_year=lambda x: x["year"] == s.ref.year))
    return row, series


def get_market_cycle(gu: str | None = None, dong: str | None = None, years: int = 10) -> dict:
    """상권 사이클 단계(성장/회복/성숙/쇠퇴 진입/쇠퇴) + 근거 수치."""
    s = store()
    g, d, label = _resolve_area(gu, dong)
    cyc, ay = s.cycle, s.area_year
    cols = ["open_recent", "close_recent", "open_prev", "close_prev", "active_now", "active_then", "stage",
            "stage_desc", "open_close_ratio_recent", "open_close_ratio_prev", "active_change_pct"]
    rules = ("최근 3년 개업/폐업 비율 r, 직전 3년 rp: r≥1.1이면 성장기(rp<0.9면 회복기), 0.9≤r<1.1 성숙기, "
             "r<0.9이면 쇠퇴기(rp≥0.9면 쇠퇴 진입기). 이벤트 20건 미만은 판정 보류.")

    if not g:
        row = cyc[cyc["level"] == "대구"].iloc[0]
        gus = cyc[cyc["level"] == "구군"].sort_values("open_close_ratio_recent", ascending=False)
        series = ay[ay["level"] == "대구"]
        return _py({
            "area": label, **row[cols].to_dict(),
            "by_gu": gus[["gu"] + cols[:1] + cols[1:2] + ["stage", "open_close_ratio_recent", "active_change_pct"]].to_dict("records"),
            "yearly": series[["year", "opens", "closes", "active_end_of_year", "partial_year"]].tail(years).to_dict("records"),
            "basis": _basis(window_recent=row["window_recent"], window_prev=row["window_prev"], rule=rules),
        })

    row, series = _cycle_for(g, d)

    # 최근 3년 업태별 순증감 (어떤 업종이 들어오고 나가는지)
    st = s.stores[_area_mask(s.stores, g, d)]
    t1 = s.ref - pd.DateOffset(years=C.CYCLE_WINDOW_YEARS)
    mv = pd.DataFrame({
        "opens": st[st["ld"] > t1].groupby("category").size(),
        "closes": st[st["closed"] & (st["cd"] > t1)].groupby("category").size(),
    }).fillna(0).astype(int)
    mv["net"] = mv["opens"] - mv["closes"]
    mv = mv[(mv["opens"] + mv["closes"]) >= 5].sort_values("net")

    return _py({
        "area": label, **row[cols].to_dict(),
        "yearly": series[["year", "opens", "closes", "active_end_of_year", "partial_year"]].tail(years).to_dict("records"),
        "categories_growing_recent_3y": mv.tail(5)[::-1].reset_index().to_dict("records"),
        "categories_shrinking_recent_3y": mv.head(5).reset_index().to_dict("records"),
        "basis": _basis(window_recent=row["window_recent"], window_prev=row["window_prev"], rule=rules,
                        note=f"{s.ref.year}년은 {s.meta['reference_date']}까지의 부분 연도"),
    })


# ─────────────────────────── Tool 5. find_vacant_units ───────────────────────────
def find_vacant_units(gu: str | None = None, dong: str | None = None, previous_category: str | None = None,
                      min_days: int = C.VACANCY_MIN_DAYS, max_days: int = C.VACANCY_MAX_DAYS,
                      single_unit_only: bool = True, sort: str = "recent", limit: int = 20) -> dict:
    """최근 공실(폐업 후 같은 자리에 신규 인허가가 없음) 목록 + 좌표 + 지속일수.

    '공실'은 어디까지나 '분석 대상 업종의 인허가 공백'이다. 분석에 포함하지 않은 업종으로
    바뀌었을 수도 있어서 basis.caveat 에 "현장 확인 필요"를 함께 실어 AI 가 단정하지 않게 한다.
    업종을 넓힐수록(config.SERVICES) 이 오판이 줄어든다 — 기획서 문제4.
    """
    s = store()
    g, d, label = _resolve_area(gu, dong)
    u = s.units
    m = u["vacant"] & u["vacant_days"].between(int(min_days), int(max_days)) & _area_mask(u, g, d)
    if single_unit_only:
        m &= u["is_single_unit"]
    service, cats, cat_label = _resolve_category(previous_category)
    if service or cats:
        m &= _cat_mask(u, service, cats, cat_col="last_category", service_col="last_service")
    v = u[m].sort_values("vacant_days", ascending=(sort != "longest"))

    by_dong = v.groupby(["gu", "dong"]).size().sort_values(ascending=False).head(10)
    rows = [{
        "address": r["addr"], "unit_id": r["uid"], "gu": r["gu"], "dong": r["dong"],
        "lat": r["lat"], "lon": r["lon"], "vacant_days": int(r["vacant_days"]), "vacant_since": r["last_close"],
        "last_store": r["last_name"], "last_category": r["last_category"], "last_store_years": r["last_life_years"],
        "closures_since_2010": int(r["closures_since_2010"]), "avg_years_since_2010": r["avg_life_since_2010_years"],
        "category_path": r["category_path"],
    } for _, r in v.head(limit).iterrows()]
    return _py({
        "area": label, "previous_category": cat_label, "total_vacant": int(len(v)),
        "vacant_days_median": None if v.empty else int(v["vacant_days"].median()),
        "top_dongs": [{"gu": k[0], "dong": k[1], "count": int(c)} for k, c in by_dong.items()],
        "units": rows, "shown": len(rows),
        "basis": _basis(definition=f"폐업 후 {min_days}~{max_days}일 동안 같은 자리에 {_services_label()} 신규 인허가가 없는 자리"
                                   + (" (동시영업 1개 이하 단일 점포 자리만)" if single_unit_only else ""),
                        caveat=f"분석 대상({_services_label()}) 외 업종으로 전환됐을 수 있으므로 현장 확인 필요. "
                               "10년 이상 공백은 철거·주소변경 가능성이 커 기본 제외."),
    })


# ─────────────────────────── Tool 6. find_risk_spots ───────────────────────────
def find_risk_spots(gu: str | None = None, dong: str | None = None, min_closures: int = 3,
                    since_year: int = C.SURVIVAL_START_YEAR, category: str | None = None, limit: int = 20) -> dict:
    """반복 폐업 지점 — 단일 점포 자리 중 교체가 잦고 존속기간이 짧은 곳.

    is_single_unit 으로 거르지 않으면 백화점 지하 1층처럼 매장이 많은 건물이 1위를 차지한다
    (기획서 문제 2). 데이터는 '교체가 잦다'만 말할 수 있고 이유는 알 수 없다는 점을 basis 에 밝힌다.
    """
    s = store()
    g, d, label = _resolve_area(gu, dong)
    st = s.stores
    c = st[st["closed"] & (st["ld"].dt.year >= int(since_year)) & _area_mask(st, g, d)]
    agg = c.groupby("uid").agg(closures=("name", "size"), avg_days=("dur_days", "mean"),
                               names=("name", lambda x: " → ".join(x.tolist()[-5:])))
    u = s.units.loc[agg.index]
    agg = agg[u["is_single_unit"].to_numpy()]
    if category:
        service, cats, _ = _resolve_category(category)
        ok = st[_cat_mask(st, service, cats)]["uid"].unique()
        agg = agg[agg.index.isin(ok)]
    risky = agg[agg["closures"] >= int(min_closures)].sort_values(["closures", "avg_days"], ascending=[False, True])

    area_units = s.units[_area_mask(s.units, g, d) & s.units["is_single_unit"]
                         & (s.units["last_open"].dt.year >= int(since_year))]
    rows = []
    for uid, r in risky.head(limit).iterrows():
        un = s.units.loc[uid]
        rows.append({
            "address": un["addr"], "unit_id": uid, "gu": un["gu"], "dong": un["dong"], "lat": un["lat"], "lon": un["lon"],
            "closures": int(r["closures"]), "avg_years_per_store": _years(r["avg_days"]),
            "recent_store_names": r["names"], "category_path": un["category_path"],
            "now": "공실" if un["vacant"] else f"영업중: {un['current_stores']}",
        })
    return _py({
        "area": label, "spots_found": int(len(risky)),
        "share_of_single_units_pct": round(len(risky) / max(len(area_units), 1) * 100, 1),
        "spots": rows,
        "basis": _basis(definition=f"{since_year}년 이후 개업해 폐업한 점포가 {min_closures}회 이상인 자리. 동시영업 1개 이하(단일 점포)만 포함해 백화점·푸드코트 등 다점포 건물 제외.",
                        caveat="교체가 잦다는 사실만 보여줄 뿐 원인(임대료·입지·운영)은 데이터로 알 수 없음."),
    })


# ─────────────────────────── Tool 7. compare_areas ───────────────────────────
def compare_areas(areas: list[str], category: str | None = None, since_year: int = C.SURVIVAL_START_YEAR) -> dict:
    """구·동 간 생존율·공실률·사이클·경쟁점포 수 교차 비교."""
    s = store()
    if not areas:
        areas = ["중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군", "군위군"]
    service, cats, cat_label = _resolve_category(category)
    base = s.stores[s.stores["ld"].dt.year >= int(since_year)]
    results, errors = [], []
    for a in areas:
        try:
            parts = a.replace(A.SIDO, "").split()
            gu_txt = parts[0] if parts and A.normalize_gu(parts[0]) else None
            dong_txt = parts[-1] if parts and (len(parts) > 1 or not gu_txt) else None
            g, d, label = _resolve_area(gu_txt, dong_txt)
        except ToolError as e:
            errors.append(str(e))
            continue
        f = base[_area_mask(base, g, d) & _cat_mask(base, service, cats)]
        sv = _survival(f, curve=False) if len(f) >= C.MIN_GROUP_N else {"n": int(len(f)), "note": "표본 부족"}

        vac = s.vacancy[(s.vacancy["level"] == ("동" if d else "구군")) & (s.vacancy["gu"] == g)]
        if d:
            vac = vac[vac["dong"].isin(d)]
        cyc, _ = _cycle_for(g, d)
        units_3y, vacant = int(vac["units_3y"].sum()), int(vac["vacant"].sum())

        active = s.stores[_area_mask(s.stores, g, d) & ~s.stores["closed"]]
        comp = int(_cat_mask(active, service, cats).sum())
        u = s.units[_area_mask(s.units, g, d)]
        results.append({
            "area": label,
            "survival": {k: sv.get(k) for k in ("n", "median_survival_years", "survival_1y_pct", "survival_3y_pct", "survival_5y_pct", "note") if k in sv},
            "vacancy_rate_pct": round(vacant / units_3y * 100, 1) if units_3y else None,
            "vacant_units": vacant, "units_active_within_3y": units_3y,
            "cycle_stage": cyc["stage"], "open_close_ratio_recent_3y": cyc["open_close_ratio_recent"],
            "active_stores_all": int(len(active)), "active_stores_same_category": comp,
            "repeat_closure_spots": int((u["is_single_unit"] & (u["closures_since_2010"] >= 3)).sum()),
            "top_active_categories": active["category"].value_counts().head(3).to_dict(),
        })

    def rank(key, reverse):
        ok = [r for r in results if (r["survival"].get(key) if key.startswith(("median", "survival_")) else r.get(key)) is not None]
        get = (lambda r: r["survival"][key]) if key.startswith(("median", "survival_")) else (lambda r: r[key])
        return [r["area"] for r in sorted(ok, key=get, reverse=reverse)]

    return _py({
        "category": cat_label, "areas": results, "errors": errors or None,
        "ranking": {
            "longest_median_survival": rank("median_survival_years", True),
            "highest_3y_survival": rank("survival_3y_pct", True),
            "lowest_vacancy_rate": rank("vacancy_rate_pct", False),
        },
        "basis": _basis(survival_cohort=f"{since_year}년 이후 인허가, Kaplan-Meier",
                        vacancy_definition="최근 3년 내 영업했던 자리 중 폐업 후 90일~3년간 신규 인허가 없는 자리 비율",
                        cycle="최근 3년 vs 직전 3년 개업/폐업 비율"),
    })


# ─────────────────────────── Tool 8. transition_matrix ───────────────────────────
def transition_matrix(from_category: str | None = None, to_category: str | None = None,
                      gu: str | None = None, dong: str | None = None, top_n: int = 10) -> dict:
    """같은 자리에서 A 업태 폐업 후 어떤 업태가 들어왔고, 그 후속 점포는 얼마나 버텼는가.

    from_category 만 주면 "한식 자리에 뭐가 들어왔나", to_category 만 주면 "카페는 원래 뭐였던 자리인가".
    단순 건수뿐 아니라 후속 점포의 생존율까지 계산해서, "많이 들어온다"와 "들어와서 잘 된다"를 구분한다.
    """
    s = store()
    g, d, label = _resolve_area(gu, dong)
    t = s.transitions[_area_mask(s.transitions, g, d)]
    t = t.assign(dur_days=t["to_dur_days"], closed=t["to_closed"].fillna(False).astype(bool))

    def successor_stats(frame):
        sm = summarize(frame["dur_days"], frame["closed"], curve_years=0)
        return {"median_survival_years": sm["median_survival_years"], "survival_1y_pct": sm["survival_1y_pct"],
                "survival_3y_pct": sm["survival_3y_pct"], "median_gap_days": int(frame["gap_days"].median())}

    basis = _basis(area=label, definition="단일 점포 자리에서 폐업한 점포 → 다음 인허가 점포 쌍. 후속 점포 생존은 Kaplan-Meier(영업중 중도절단).")
    if from_category or to_category:
        fs, fc, flabel = _resolve_category(from_category)
        ts, tc, tlabel = _resolve_category(to_category)
        m = _cat_mask(t, fs, fc, "from_category", "from_service") & _cat_mask(t, ts, tc, "to_category", "to_service")
        sub = t[m]
        if sub.empty:
            raise ToolError(f"{label}에서 '{flabel} → {tlabel}' 전이 사례가 없습니다.")
        col = "to_category" if from_category and not to_category else "from_category" if to_category and not from_category else None
        out = {"area": label, "from": flabel, "to": tlabel, "transitions": int(len(sub)),
               "overall_successor": successor_stats(sub)}
        if col:
            total = len(sub)
            rows = []
            for k, f in sub.groupby(col):
                if len(f) < 5:
                    continue
                rows.append({col: k, "count": int(len(f)), "share_pct": round(len(f) / total * 100, 1), **successor_stats(f)})
            rows.sort(key=lambda r: -r["count"])
            out["breakdown"] = rows[:top_n]
            if from_category and fc:
                out["same_category_reentry_pct"] = round(float(sub["to_category"].isin(fc).mean() * 100), 1)
        else:
            out["examples"] = sub.sort_values("to_open", ascending=False).head(5)[
                ["uid", "from_name", "from_life_years", "to_name", "to_open", "gap_days"]].to_dict("records")
        return _py(out | {"basis": basis})

    pairs = (t.groupby(["from_category", "to_category"]).size().sort_values(ascending=False)
             .head(top_n).reset_index(name="count"))
    svc = t.groupby(["from_service", "to_service"]).size().reset_index(name="count")
    return _py({"area": label, "transitions": int(len(t)), "top_pairs": pairs.to_dict("records"),
                "service_switch": svc.to_dict("records"), "basis": basis})


# ─────────────────────────── 보조 데이터 Tool (9~11) ───────────────────────────
EARTH_R = 6371000.0


def _distance_m(lat: float, lon: float, lats, lons):
    """한 점과 여러 점 사이의 거리(m). 하버사인 공식."""
    p1, p2 = math.radians(lat), np.radians(np.asarray(lats, dtype=float))
    dlat, dlon = p2 - p1, np.radians(np.asarray(lons, dtype=float) - lon)
    a = np.sin(dlat / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(a))


def _require(df, name: str):
    if df is None:
        raise ToolError(f"{name} 데이터가 준비되지 않았습니다. `python -m pipeline.external` 을 먼저 실행하세요.")
    return df


def _resolve_admin_dong(gu: str | None, dong: str | None) -> pd.DataFrame:
    """행정동 이름 또는 법정동 이름으로 area_context 행을 찾는다.

    인허가 주소는 법정동(삼덕동1가), 인구 통계는 행정동(삼덕동) 기준이라 둘을 모두 받아 준다.
    """
    ctx = _require(store().area_context, "동네 맥락")
    g = A.normalize_gu(gu) if gu else None
    if not dong:
        return ctx[ctx["gu"] == g] if g else ctx
    text = dong.replace(A.SIDO, "").replace("대구", "").strip().split()[-1]
    hit = ctx[ctx["admin_dong"] == text]
    if hit.empty:  # 법정동으로 들어온 경우 → 상가정보에서 학습한 매핑으로 행정동을 찾는다
        m = store().legal_admin
        if m is not None:
            names = m[m["legal_dong"].str.startswith(text.rstrip("동읍면"))]
            if g:
                names = names[names["gu"] == g]
            hit = ctx[ctx["admin_dong"].isin(names["admin_dong"]) & ctx["gu"].isin(names["gu"])]
    if hit.empty:
        hit = ctx[ctx["admin_dong"].str.startswith(text.rstrip("동읍면"))]
    if g:
        hit = hit[hit["gu"] == g]
    if hit.empty:
        raise ToolError(f"'{dong}'에 해당하는 행정동을 찾지 못했습니다 (예: 삼덕동, 범어3동, 다사읍).")
    if hit["gu"].nunique() > 1:
        raise ToolError(f"'{dong}'이(가) 여러 구에 있습니다: {sorted(hit['gu'].unique())}. 구를 함께 지정하세요.")
    return hit


def get_area_profile(gu: str | None = None, dong: str | None = None, top_n: int = 5) -> dict:
    """동네 프로필 — 상권 유형, 업종 구성·다양성, 인구·연령, 집객 시설, 인허가 기반 사이클·공실률."""
    s = store()
    hit = _resolve_admin_dong(gu, dong)
    if len(hit) > 1 and dong:
        rows = [{"gu": r["gu"], "admin_dong": r["admin_dong"], "poi_total": int(r["poi_total"]),
                 "market_type": r["market_type"]} for _, r in hit.nlargest(8, "poi_total").iterrows()]
        return _py({"matched": len(hit), "candidates": rows,
                    "hint": "행정동이 여러 개입니다. 하나를 골라 다시 물어보세요."})
    r = hit.nlargest(1, "poi_total").iloc[0] if len(hit) > 1 else hit.iloc[0]

    profile = {
        "area": f"{r['gu']} {r['admin_dong']}",
        "market_type": r["market_type"], "market_type_basis": r["market_type_basis"],
        "stores_now": int(r["poi_total"]), "food_stores_now": int(r["poi_food"]),
        "share_pct": {"음식": r["food_share_pct"], "소매": r["retail_share_pct"], "교육": r["edu_share_pct"],
                      "과학·기술+부동산+임대": r["office_share_pct"], "수리·개인+보건": r["personal_share_pct"],
                      "숙박": r["lodging_share_pct"], "음식 중 주점": r["pub_share_of_food_pct"]},
        "city_share_pct": {"음식": r["city_food"], "소매": r["city_retail"], "교육": r["city_edu"],
                           "과학·기술+부동산+임대": r["city_office"], "수리·개인+보건": r["city_personal"],
                           "숙박": r["city_lodging"], "음식 중 주점": r["city_pub"]},
        "diversity_index": r["diversity_index"], "city_diversity_index": r["city_diversity"],
        "diversity_note": "0에 가까울수록 한 업종 쏠림, 1에 가까울수록 고르게 분포",
        "top_categories": dict(list(json.loads(r["top_categories_json"]).items())[:top_n]),
        "population": {"total": r.get("pop_total"), "ref_month": r.get("pop_ref_month"),
                       "age_15_29_pct": r.get("age_15_29_pct"), "age_30_49_pct": r.get("age_30_49_pct"),
                       "age_65_plus_pct": r.get("age_65_plus_pct")},
        "facilities": {"traditional_markets": int(r.get("market_count", 0)),
                       "market_stores": int(r.get("market_stores", 0) or 0),
                       "parking_lots": int(r.get("parking_count", 0)),
                       "parking_slots": int(r.get("parking_slots", 0) or 0)},
    }

    # 인허가 데이터(시간축) 쪽 지표를 같은 동네 기준으로 붙인다
    legal = s.legal_admin
    legal_dongs = (legal.loc[(legal["gu"] == r["gu"]) & (legal["admin_dong"] == r["admin_dong"]), "legal_dong"]
                   .tolist() if legal is not None else [])
    st = s.stores[(s.stores["gu"] == r["gu"]) & s.stores["dong"].isin(legal_dongs)]
    if len(st) >= C.MIN_GROUP_N:
        coh = st[st["ld"].dt.year >= C.SURVIVAL_START_YEAR]
        profile["license_based"] = {
            "legal_dongs": legal_dongs,
            "records": int(len(st)), "active": int((~st["closed"]).sum()),
            "survival": _survival(coh, curve=False) if len(coh) >= C.MIN_GROUP_N else {"note": "표본 부족"},
        }
        vac = s.vacancy[(s.vacancy["level"] == "동") & (s.vacancy["gu"] == r["gu"])
                        & s.vacancy["dong"].isin(legal_dongs)]
        if len(vac):
            units_3y, vacant = int(vac["units_3y"].sum()), int(vac["vacant"].sum())
            profile["license_based"]["vacancy_rate_pct"] = round(vacant / units_3y * 100, 1) if units_3y else None
            profile["license_based"]["vacant_units"] = vacant
        cyc = s.cycle[(s.cycle["level"] == "동") & (s.cycle["gu"] == r["gu"]) & s.cycle["dong"].isin(legal_dongs)]
        if len(cyc):
            counts = cyc[_CYCLE_COUNTS].sum()
            profile["license_based"]["cycle"] = classify_stage(*counts.tolist())

    # 이름이 같은 지하철역이 있으면 참고로 붙인다(좌표가 없어 이름 기준 추정)
    if s.station is not None:
        base = r["admin_dong"].rstrip("0123456789동읍면가")
        near = s.station[s.station["station"].str.startswith(base)] if base else s.station.iloc[0:0]
        if len(near):
            row = near.nlargest(1, "daily_total").iloc[0]
            profile["nearby_station_by_name"] = {
                "station": row["station"], "daily_total": int(row["daily_total"]),
                "note": "역 좌표가 없어 이름이 같은 역을 참고로 연결한 값 — 실제 인접 여부는 확인 필요",
            }
    return _py(profile | {"basis": _basis(
        poi="소상공인시장진흥공단 상가(상권)정보 2026-06 현재 영업 점포",
        population=f"행정안전부 주민등록 인구 {r.get('pop_ref_month')}",
        definition="상권 유형은 업종 구성비를 대구 평균과 비교해 판정(절대 비중 기준 동시 충족)",
        caveat="상가정보는 현재 단면이라 과거 추이는 인허가 기반 지표(license_based)를 함께 보아야 함")})


def find_nearby(address: str, radius_m: int = C.NEARBY_RADIUS_M, category: str | None = None,
                limit: int = 10) -> dict:
    """특정 자리 반경 안의 경쟁 점포·공실·주차장·전통시장 — '이 자리 주변'을 보는 Tool."""
    s = store()
    poi = _require(s.poi, "상가정보")
    u, _ = _pick_unit(address)
    if pd.isna(u["lat"]) or pd.isna(u["lon"]):
        raise ToolError(f"'{u['addr']}'는 좌표가 없어 반경 분석을 할 수 없습니다.")
    lat, lon, radius = float(u["lat"]), float(u["lon"]), int(radius_m)

    d = _distance_m(lat, lon, poi["lat"], poi["lon"])
    near = poi[d <= radius].assign(dist_m=d[d <= radius].round(0))
    food = near[near["cat_l"] == "음식"]
    same = None
    if category:
        service, cats, cat_label = _resolve_category(category)
        # 상가정보는 분류 체계가 달라(인허가 '커피숍' ↔ 상가정보 '비알코올 음료점'),
        # config 의 검색어 사전을 거쳐 중·소분류 이름으로 부분 일치 검색한다.
        keys = {category.strip()}
        for c in (cats or []):
            keys |= set(C.POI_CATEGORY_KEYWORDS.get(c, [c]))
        keys |= set(C.POI_CATEGORY_KEYWORDS.get(category.strip(), []))
        m = pd.Series(False, index=near.index)
        for k in keys:
            m |= near["cat_m"].str.contains(k, na=False) | near["cat_s"].str.contains(k, na=False)
        same = {"query": cat_label, "count": int(m.sum()),
                "examples": near[m].nsmallest(min(limit, 5), "dist_m")[["name", "cat_s", "dist_m"]].to_dict("records")}

    units = s.units.dropna(subset=["lat", "lon"])
    du = _distance_m(lat, lon, units["lat"], units["lon"])
    near_u = units[du <= radius].assign(dist_m=du[du <= radius].round(0))
    vacant = near_u[near_u["recent_vacancy"]].nsmallest(limit, "dist_m")
    risky = near_u[near_u["is_single_unit"] & (near_u["closures_since_2010"] >= 3)].nsmallest(limit, "dist_m")

    out = {
        "center": {"address": u["addr"], "unit_id": u["uid"], "lat": lat, "lon": lon,
                   "status": "공실" if u["vacant"] else f"영업중: {u['current_stores']}"},
        "radius_m": radius,
        "stores_in_radius": int(len(near)), "food_stores_in_radius": int(len(food)),
        "food_share_pct": round(len(food) / len(near) * 100, 1) if len(near) else None,
        "top_categories": near["cat_m"].value_counts().head(5).to_dict(),
        "same_category": same,
        "recent_vacancies": [{"address": r["addr"], "dist_m": int(r["dist_m"]), "vacant_days": int(r["vacant_days"]),
                              "last_store": r["last_name"], "last_category": r["last_category"],
                              "lat": r["lat"], "lon": r["lon"]} for _, r in vacant.iterrows()],
        "recent_vacancy_count": int(near_u["recent_vacancy"].sum()),
        "repeat_closure_spots": [{"address": r["addr"], "dist_m": int(r["dist_m"]),
                                  "closures_since_2010": int(r["closures_since_2010"]),
                                  "category_path": r["category_path"], "lat": r["lat"], "lon": r["lon"]}
                                 for _, r in risky.iterrows()],
    }
    if s.parking is not None:
        dp = _distance_m(lat, lon, s.parking["lat"], s.parking["lon"])
        pk = s.parking[dp <= radius]
        out["parking"] = {"lots": int(len(pk)), "slots": int(pk["slots"].fillna(0).sum())}
    if s.market is not None:
        dm = _distance_m(lat, lon, s.market["lat"], s.market["lon"])
        mk = s.market[dm <= max(radius, 1000)].assign(dist_m=dm[dm <= max(radius, 1000)].round(0))
        out["traditional_markets_within_1km"] = [
            {"name": r["name"], "dist_m": int(r["dist_m"]), "stores": None if pd.isna(r["stores"]) else int(r["stores"])}
            for _, r in mk.nsmallest(3, "dist_m").iterrows()]
    return _py(out | {"basis": _basis(
        poi="소상공인시장진흥공단 상가(상권)정보 2026-06 현재 영업 점포(전 업종)",
        definition=f"중심 좌표에서 직선거리 {radius}m 이내",
        caveat="상가정보와 인허가는 출처가 달라 점포 수가 정확히 일치하지 않음. 직선거리라 실제 도보 거리와 다름")})


def get_station_traffic(station: str | None = None, top_n: int = 10) -> dict:
    """지하철 역별 승하차 인원과 시간대 구성 — 유동인구 대리지표."""
    st = _require(store().station, "지하철 승하차")
    basis = _basis(source="대구교통공사 역별 일별 시간별 승하차인원", period=st["period"].iat[0],
                   definition="일평균 승차·하차 인원. 시간대 비중은 하차(= 그 동네로 들어오는 사람) 기준",
                   caveat="역 좌표가 없어 특정 자리와의 거리는 계산하지 않음. 역세권 여부는 별도 확인 필요")
    cols = ["station", "daily_boarding", "daily_alighting", "daily_total",
            "morning_07_09_pct", "lunch_11_14_pct", "evening_17_20_pct", "night_22_24_pct", "peak_hour"]
    if not station:
        return _py({"stations": int(len(st)), "ranking_by_daily_total": st.head(top_n)[cols].to_dict("records"),
                    "basis": basis})
    key = station.replace("역", "").strip()
    hit = st[st["station"].str.contains(key, na=False)]
    if hit.empty:
        raise ToolError(f"'{station}' 역을 찾지 못했습니다. 예: 반월당, 동대구역, 범어")
    r = hit.nlargest(1, "daily_total").iloc[0]
    rank = int((st["daily_total"] > r["daily_total"]).sum()) + 1
    return _py({**{c: r[c] for c in cols}, "rank_by_daily_total": rank, "of_stations": int(len(st)),
                "city_median_daily_total": int(st["daily_total"].median()),
                "other_matches": hit["station"].tolist()[1:], "basis": basis})


TOOL_FUNCTIONS = {
    "get_market_cycle": get_market_cycle,
    "find_vacant_units": find_vacant_units,
    "get_survival_curve": get_survival_curve,
    "get_unit_history": get_unit_history,
    "find_risk_spots": find_risk_spots,
    "compare_areas": compare_areas,
    "transition_matrix": transition_matrix,
    "normalize_address": normalize_address,
    "get_area_profile": get_area_profile,
    "find_nearby": find_nearby,
    "get_station_traffic": get_station_traffic,
}
