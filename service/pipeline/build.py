"""야간 배치: 인허가 원본 CSV → 분석 테이블 사전 계산.

실행:  python -m pipeline.build          (약 15초)
입력:  data/raw/*.csv                    (공공데이터포털 인허가 CSV, CP949)
산출:  data/processed/{stores,units,transitions,area_year,area_cycle,survival,vacancy_area}.parquet, meta.json

무거운 계산은 전부 여기서 끝내고, 에이전트 Tool 은 이 산출물을 조회만 한다 (기획서 8장 설계 원칙).
그래서 웹 서버에는 원본 CSV 도, 좌표 변환 라이브러리(pyproj)도 필요 없다.

읽는 순서 — main() 이 목차다. 아래 8단계가 순서대로 호출된다.
    1 load_raw           CSV 적재 + 고유키 중복 제거
    2 clean              자료형 변환, 품질 점검, 기준일(ref)과 영업기간 계산
    3 build_address      주소 → 자리 키(uid), 구·동·층, 좌표 변환
    4 build_units        한 행 = 자리 1곳으로 집계 (동시영업 수, 공실 판정)
    5 build_transitions  같은 자리의 '앞 점포 → 다음 점포' 쌍
    6 build_cycle        지역별 사이클 판정 + 연도별 개·폐업
    7 build_survival     그룹별 Kaplan-Meier 요약
    8 build_vacancy_area 구·동별 공실률

용어: ld = 인허가일(개업), cd = 폐업일, ref = 기준일, uid = 자리 키, st = 점포 표(stores)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config as C  # noqa: E402
from core import address as A  # noqa: E402
from core.cycle import classify_stage  # noqa: E402
from core.survival import YEAR, summarize  # noqa: E402

# 업종마다 열 구성이 다르다(음식점 39열, 담배소매업 24열 …). 없는 열은 적재 후 빈 값으로 채운다.
USECOLS = [
    "개방자치단체코드", "관리번호", "인허가일자", "영업상태명", "폐업일자", "인허가취소일자", "소재지면적",
    "사업장명", "업태구분명", "위생업태명", "데이터갱신구분", "도로명주소", "지번주소",
    "좌표정보(X)", "좌표정보(Y)", "최종수정시점", "데이터갱신시점",
]
DAY = pd.Timedelta(days=1)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ─────────────────────────── 1. 적재 ───────────────────────────
def load_raw() -> tuple[pd.DataFrame, dict]:
    """data/raw 의 CSV 를 모두 읽어 한 장의 표로 합치고 중복을 제거한다."""
    frames = []
    for path in sorted(C.RAW_DIR.rglob("*.csv")):
        # 업종은 파일명으로 구분한다. config.SERVICES 의 이름이 파일명에 들어 있어야 한다.
        service = next((s for s in C.SERVICES if s in path.name), None)
        if service is None:
            log(f"  건너뜀(업종 미식별): {path.name}")
            continue
        # cp949 = 공공데이터포털 CSV 의 한글 인코딩. dtype=str 로 읽어 날짜·숫자 변환은 clean() 에서 한 번에 한다
        # (pandas 가 알아서 추측하게 두면 '0061-0003' 같은 번지가 숫자로 바뀌는 사고가 난다).
        df = pd.read_csv(path, encoding="cp949", encoding_errors="replace", dtype=str,
                         usecols=lambda c: c in USECOLS)  # 39개 열 중 쓰는 16개만
        for col in USECOLS:  # 이 업종 파일에 없는 열은 빈 값으로 만들어 이후 처리를 단순화한다
            if col not in df.columns:
                df[col] = pd.NA
        df["service"] = service
        df["service_id"] = service  # 고유키 구성요소 (업종 하나당 파일 하나)
        frames.append(df)
        log(f"  {path.name}: {len(df):,}행")
    if not frames:
        raise SystemExit(f"{C.RAW_DIR} 에 인허가 CSV 가 없습니다.")
    df = pd.concat(frames, ignore_index=True)
    n_raw = len(df)
    # 고유키 = 지자체코드 + 관리번호 + 개방서비스ID. 관리번호만으로는 다른 지자체·업종과 겹칠 수 있어 3개를 조합한다.
    # 증분(I=신규 / U=수정) 파일을 함께 넣어도 되도록, 정렬 후 마지막(=최종수정시점이 가장 늦은) 행만 남긴다.
    df = df.sort_values(["최종수정시점", "데이터갱신시점"], na_position="first")
    df = df.drop_duplicates(["개방자치단체코드", "관리번호", "service_id"], keep="last")
    return df.reset_index(drop=True), {"raw_rows": n_raw, "duplicates_removed": n_raw - len(df)}


# ─────────────────────────── 2. 정제 ───────────────────────────
def clean(df: pd.DataFrame, quality: dict) -> tuple[pd.DataFrame, pd.Timestamp]:
    """자료형을 맞추고, 품질을 점검하고, 분석 기준일과 영업기간을 만든다.

    반환하는 ref(기준일)가 이후 모든 계산의 '오늘'이다. 실행 날짜가 아니라 데이터의 최신 날짜를 쓴다.
    """
    df["ld"] = pd.to_datetime(df["인허가일자"], errors="coerce")  # ld = license date(개업)
    # cd = close date. 담배소매업·노래연습장업처럼 '인허가취소일자'로 종료를 기록하는 업종이 있어 함께 본다.
    df["cd"] = pd.to_datetime(df["폐업일자"], errors="coerce").fillna(
        pd.to_datetime(df["인허가취소일자"], errors="coerce"))
    # '폐업' 외에 '취소', '말소'도 영업 종료로 본다
    df["closed"] = df["영업상태명"].fillna("").str.contains("폐업|취소|말소")

    quality["missing_license_date"] = int(df["ld"].isna().sum())
    # 1900-01-01 같은 명백한 입력 오류 (담배소매업에서 4건 확인). 데이터 개방은 1960년대부터다.
    too_old = df["ld"].dt.year < 1960
    quality["license_date_before_1960"] = int(too_old.sum())
    df.loc[too_old, "ld"] = pd.NaT
    quality["closed_without_close_date"] = int((df["closed"] & df["cd"].isna()).sum())
    quality["date_contradiction"] = int((df["cd"] < df["ld"]).sum())

    in_daegu = df["지번주소"].map(A.is_daegu) | df["도로명주소"].map(A.is_daegu)
    quality["non_daegu_address"] = int((~in_daegu).sum())
    quality["non_daegu_examples"] = (df.loc[~in_daegu, "지번주소"].fillna(df.loc[~in_daegu, "도로명주소"])
                                     .head(5).tolist())

    # 분석에 쓸 수 있는 행만 남긴다: 대구 주소 + 개업일 있음 + (폐업인데 폐업일 없음) 아님 + 날짜 모순 아님
    ok = in_daegu & df["ld"].notna() & ~(df["closed"] & df["cd"].isna()) & ~(df["cd"] < df["ld"])
    df = df[ok].copy()
    # 기준일 = 데이터에 등장하는 가장 늦은 날짜. 배치를 언제 돌리든 같은 데이터면 같은 결과가 나온다.
    ref = max(df["ld"].max(), df["cd"].max()).normalize()

    # 업태: 업태구분명 → 위생업태명 → (둘 다 없는 업종은) 업종명 자체.
    # 담배소매업·노래연습장업은 업태 구분이 없어 업종명이 곧 업태가 된다.
    df["category"] = (df["업태구분명"].astype("string").fillna("").str.strip()
                      .replace("", pd.NA)
                      .fillna(df["위생업태명"].astype("string").str.strip())
                      .fillna(df["service"]).astype(str).str.strip())
    df["name"] = df["사업장명"].fillna("").str.strip()
    # 영업 종료일: 폐업했으면 폐업일, 영업 중이면 기준일(= 여기서 관측을 끊는다 → 생존분석의 '중도절단')
    df["end"] = df["cd"].where(df["closed"], ref)
    df["dur_days"] = (df["end"] - df["ld"]).dt.days.clip(lower=0)  # 영업 일수
    df["area_m2"] = pd.to_numeric(df["소재지면적"], errors="coerce")
    return df, ref


# ─────────────────────────── 3. 주소·좌표 ───────────────────────────
FLOOR_DOMINANCE = 0.8


def assign_floor_units(df: pd.DataFrame) -> pd.Series:
    """자리 키 = 건물 기본주소 + 층.

    층 기재는 2010년 이후에야 보편화되었으므로(2000년대 18% → 2020년대 86%),
    층이 없는 과거 레코드는 그 건물의 층 기재가 한 층에 80% 이상 몰려 있을 때만 그 층으로 합류시키고,
    아니면 '층 미상' 건물 키로 남긴다.
    """
    floored = df.dropna(subset=["floor"])
    share = floored.groupby(["building_key", "floor"]).size()          # 건물별·층별 레코드 수
    # transform("sum") 은 그룹 합계를 원래 행 수만큼 펼쳐 준다 → 건물 안에서 각 층이 차지하는 비율
    share = (share / share.groupby(level=0).transform("sum")).reset_index(name="share")
    dominant = (share[share["share"] >= FLOOR_DOMINANCE]               # 한 층이 80% 이상인 건물만
                .drop_duplicates("building_key").set_index("building_key")["floor"])
    floor = df["floor"].fillna(df["building_key"].map(dominant))       # 층이 없는 과거 레코드를 그 층으로 채움
    return np.where(floor.notna(), df["building_key"] + " " + floor.fillna(""), df["building_key"])


def build_address(df: pd.DataFrame, quality: dict) -> pd.DataFrame:
    """주소 문자열 → 자리 키(uid) · 구 · 동 · 층 · 위경도.

    이 함수가 만드는 uid 가 프로젝트 전체의 분석 단위다. 같은 자리의 레코드가 같은 uid 를 받아야
    "이 자리에서 몇 개가 망했는지"를 셀 수 있다.
    """
    jb = df["지번주소"].map(A.parse_jibun)
    rd = df["도로명주소"].map(A.parse_road)
    df["jibun_key"] = jb.map(lambda x: x["key"] if x else None)
    df["road_key"] = rd.map(lambda x: x["key"] if x else None)

    # 도로명 → 지번 매핑 학습 (둘 다 있는 레코드에서 최빈값).
    # 오래된 레코드에는 도로명이 없으므로 지번을 기준 키로 삼고,
    # 도로명만 있는 최근 레코드를 이 매핑으로 같은 지번 키에 합류시킨다 → 같은 자리의 과거와 현재가 이어진다.
    both = df.dropna(subset=["jibun_key", "road_key"])
    road2jibun = (both.groupby(["road_key", "jibun_key"]).size().reset_index(name="n")
                  .sort_values("n").drop_duplicates("road_key", keep="last")
                  .set_index("road_key")["jibun_key"])
    fallback_raw = df["지번주소"].fillna(df["도로명주소"]).fillna("").str.strip()
    # 키 우선순위: 지번 → (도로명을 지번으로 번역) → 도로명 그대로 → 원본 문자열
    df["uid"] = (df["jibun_key"].fillna(df["road_key"].map(road2jibun))
                 .fillna(df["road_key"]).fillna(fallback_raw))

    gu_j = jb.map(lambda x: x["gu"] if x else None)
    gu_r = rd.map(lambda x: x["gu"] if x else None)
    df["gu"] = gu_j.fillna(gu_r)
    df["gu"] = df["gu"].fillna(df["uid"].map(A.normalize_gu))
    # 동네 단위: 군 지역은 읍·면, 구 지역은 법정동
    dong_j = jb.map(lambda x: (x["eup"] or x["dong"]) if x else None)
    dong_r = rd.map(lambda x: (x["eup"] or x["dong"]) if x else None)
    df["dong"] = dong_j.fillna(dong_r)
    df["floor"] = [A.extract_floor(r, j) for r, j in zip(df["도로명주소"], df["지번주소"])]
    df["building_key"] = df["uid"]      # 층을 붙이기 전 = 건물 단위 키 (자리 이력의 '건물 전체 보기'에 쓴다)
    df["uid"] = assign_floor_units(df)  # 최종 자리 키 = 건물 + 층

    quality["address_unparsed"] = int((df["jibun_key"].isna() & df["road_key"].isna()).sum())

    # 인허가 데이터의 좌표는 EPSG:5174(한국 중부원점TM). 지도에 찍으려면 위경도(WGS84)로 바꿔야 한다.
    x = pd.to_numeric(df["좌표정보(X)"].str.strip(), errors="coerce").to_numpy()
    y = pd.to_numeric(df["좌표정보(Y)"].str.strip(), errors="coerce").to_numpy()
    lon, lat = Transformer.from_crs(C.SRC_CRS, C.DST_CRS, always_xy=True).transform(x, y)
    # 변환이 실패하거나 좌표가 비었으면 엉뚱한 값이 나오므로, 대구 범위를 벗어나면 결측 처리한다.
    valid = np.isfinite(lat) & (lat > 35.4) & (lat < 36.5) & (lon > 128.1) & (lon < 129.1)
    df["lat"] = np.where(valid, lat, np.nan)
    df["lon"] = np.where(valid, lon, np.nan)
    quality["coord_fill_pct"] = {
        s: round(float(g["lat"].notna().mean() * 100), 1) for s, g in df.groupby("service")
    }
    return df


# ─────────────────────────── 4. 자리(unit) ───────────────────────────
def max_concurrency(df: pd.DataFrame, ref: pd.Timestamp, tolerance_days: int) -> pd.Series:
    """시작=+1, 종료=-1 이벤트 누적합의 최댓값 = 동시 영업 점포 수 (기획서 문제2).

    같은 날 종료·시작은 '교체'이므로 종료(-1)를 먼저 정렬하고,
    양도·양수 시 신·구 인허가가 tolerance 이내로 겹치는 것도 교체로 본다.
    """
    end = df["cd"].where(df["closed"], ref + DAY)
    if tolerance_days:
        end = np.maximum(end - pd.Timedelta(days=tolerance_days), df["ld"] + DAY)
    ev = pd.DataFrame({
        "uid": np.concatenate([df["uid"].to_numpy(), df["uid"].to_numpy()]),
        "t": np.concatenate([df["ld"].to_numpy(), pd.to_datetime(end).to_numpy()]),
        "d": np.concatenate([np.ones(len(df), int), -np.ones(len(df), int)]),
    # 같은 날짜면 d 오름차순이라 종료(-1)가 시작(+1)보다 먼저 처리된다 → 같은 날 교체를 겹침으로 세지 않는다
    }).sort_values(["uid", "t", "d"])
    ev["cum"] = ev.groupby("uid")["d"].cumsum()  # 시간순 누적합 = 그 순간 영업 중인 점포 수
    return ev.groupby("uid")["cum"].max()        # 가장 많았던 순간이 그 자리의 동시영업 수


def build_units(st: pd.DataFrame, ref: pd.Timestamp) -> pd.DataFrame:
    """점포 표(한 행 = 인허가 1건) → 자리 표(한 행 = 자리 1곳).

    "이 자리에서 몇 개가 망했고, 지금 비어 있는가"를 미리 계산해 두는 단계다.
    """
    # assign 은 열을 추가한 새 데이터프레임을 돌려준다(원본을 건드리지 않음)
    st = st.assign(active=~st["closed"],
                   closed_2010=st["closed"] & (st["ld"].dt.year >= C.SURVIVAL_START_YEAR))
    g = st.groupby("uid")
    # agg 에 이름=(열, 함수) 형태로 주면 결과 열 이름을 그대로 지정할 수 있다
    units = g.agg(
        gu=("gu", "first"), dong=("dong", "first"),
        n_records=("ld", "size"), n_active=("active", "sum"), n_closed=("closed", "sum"),
        closures_since_2010=("closed_2010", "sum"),
        first_open=("ld", "min"), last_open=("ld", "max"), last_close=("cd", "max"),
        lat=("lat", "median"), lon=("lon", "median"),
        n_services=("service", "nunique"), n_categories=("category", "nunique"),
    )
    closed = st[st["closed"]]
    units["avg_life_closed_years"] = (closed.groupby("uid")["dur_days"].mean() / YEAR).round(2)
    c10 = st[st["closed_2010"]]
    units["avg_life_since_2010_years"] = (c10.groupby("uid")["dur_days"].mean() / YEAR).round(2)

    # 화면에 보여줄 주소는 도로명이 친숙하다. 한 자리에 여러 도로명 표기가 있으면 가장 많이 쓰인 것을 고른다
    # (정렬 후 마지막만 남기는 것이 "최빈값 고르기"의 흔한 관용구다).
    road = (st.dropna(subset=["road_key"]).groupby(["uid", "road_key"]).size().reset_index(name="n")
            .sort_values("n").drop_duplicates("uid", keep="last").set_index("uid")["road_key"])
    units["floor"] = st.groupby("uid")["floor"].agg(lambda s: s.mode().iat[0] if s.notna().any() else None)
    units["building_key"] = g["building_key"].first()
    units["road_addr"] = road
    units["jibun_addr"] = units["building_key"]
    units["addr"] = (units["road_addr"].fillna(units["jibun_addr"])
                     + units["floor"].map(lambda f: f" {f}" if isinstance(f, str) else ""))

    ordered = st.sort_values(["uid", "ld", "end"])       # 자리별 시간순
    last = ordered.groupby("uid").tail(1).set_index("uid")  # 자리마다 마지막 레코드 = 가장 최근 점포
    units["last_name"] = last["name"]
    units["last_category"] = last["category"]
    units["last_service"] = last["service"]
    units["last_life_years"] = (last["dur_days"] / YEAR).round(2)
    units["category_path"] = ordered.groupby("uid")["category"].agg(lambda s: " → ".join(s.tolist()[-8:]))
    units["current_stores"] = (st[st["active"]].groupby("uid")["name"]
                               .agg(lambda s: ", ".join(s.tolist()[:3])))

    units["max_concurrent"] = max_concurrency(st, ref, C.HANDOVER_TOLERANCE_DAYS)
    units["max_concurrent_naive"] = max_concurrency(st, ref, 0)  # 허용 오차 없이 센 값(비교·검증용)
    # 동시영업이 1 이하 = 진짜 '한 자리'. 백화점·푸드코트 같은 다점포 건물을 반복폐업·업종전이 분석에서 제외하는 기준
    units["is_single_unit"] = units["max_concurrent"] <= 1

    units["vacant"] = units["n_active"] == 0  # 영업 중인 점포가 하나도 없으면 공실 후보
    units["vacant_days"] = np.where(units["vacant"], (ref - units["last_close"]).dt.days, np.nan)
    # 유효 매물 = 90일~3년. 너무 최근은 정리 중일 수 있고, 10년 넘게 비었으면 철거·주소 변경일 가능성이 크다
    units["recent_vacancy"] = units["vacant"] & units["vacant_days"].between(C.VACANCY_MIN_DAYS, C.VACANCY_MAX_DAYS)
    # pd.cut = 연속값을 구간으로 묶기. 경계 [-1, 89, 365, ...] 는 '89일 이하', '90~365일' 식으로 나뉜다
    units["vacancy_bucket"] = pd.cut(units["vacant_days"], [-1, 89, 365, 365 * 3, 365 * 10, 1e9],
                                     labels=["3개월 미만", "3개월~1년", "1~3년", "3~10년", "10년 이상"]).astype(str)
    units.loc[~units["vacant"], "vacancy_bucket"] = "영업중"
    units.index.name = "uid"
    return units.reset_index()


# ─────────────────────────── 5. 업종 전이 ───────────────────────────
def build_transitions(st: pd.DataFrame, units: pd.DataFrame) -> pd.DataFrame:
    """같은 자리의 '앞 점포 → 다음 점포' 쌍을 만든다.

    "한식이 망한 자리에 뭐가 들어왔고, 그건 얼마나 버텼나"를 답하기 위한 표다.
    다점포 건물은 '다음 점포'가 옆 가게일 뿐이라 단일 점포 자리만 대상으로 한다.
    """
    single = set(units.loc[units["is_single_unit"], "uid"])
    s = st[st["uid"].isin(single)].sort_values(["uid", "ld", "end"]).reset_index(drop=True)
    # shift(-1) = 각 행에 '한 칸 아래 행'의 값을 붙인다. groupby 안에서 하므로 다른 자리와 섞이지 않는다.
    nxt = s.groupby("uid")[["ld", "category", "service", "name", "dur_days", "closed"]].shift(-1)
    m = nxt["ld"].notna() & s["closed"]  # 다음 점포가 있고, 앞 점포가 실제로 폐업한 경우만
    t = pd.DataFrame({
        "uid": s["uid"], "gu": s["gu"], "dong": s["dong"],
        "from_name": s["name"], "from_category": s["category"], "from_service": s["service"],
        "from_life_years": (s["dur_days"] / YEAR).round(2),
        "to_name": nxt["name"], "to_category": nxt["category"], "to_service": nxt["service"],
        "to_open": nxt["ld"], "to_dur_days": nxt["dur_days"], "to_closed": nxt["closed"].astype("boolean"),
        "gap_days": (nxt["ld"] - s["cd"]).dt.days,
    })[m]
    # gap_days 가 음수 = 앞 가게 폐업신고 전에 새 가게가 인허가를 받은 경우(양도·양수). 60일까지는 정상 교체로 본다.
    return t[t["gap_days"] >= -C.HANDOVER_TOLERANCE_DAYS].reset_index(drop=True)


# ─────────────────────────── 6. 상권 사이클 ───────────────────────────
def build_cycle(st: pd.DataFrame, ref: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """지역별 사이클 판정표와 연도별 개·폐업 시계열을 만든다."""
    w = pd.DateOffset(years=C.CYCLE_WINDOW_YEARS)
    t1, t0 = ref - w, ref - w - w   # t0 ---- 직전 3년 ---- t1 ---- 최근 3년 ---- ref
    # 조건을 True/False 열로 만들어 두면, 나중에 sum() 한 번으로 지역별 건수가 나온다(True = 1).
    st = st.assign(
        open_recent=st["ld"] > t1, close_recent=st["closed"] & (st["cd"] > t1),
        open_prev=(st["ld"] > t0) & (st["ld"] <= t1),
        close_prev=st["closed"] & (st["cd"] > t0) & (st["cd"] <= t1),
        active_now=~st["closed"],
        # 3년 전 시점에 영업 중이었나 = 그때 이미 개업했고, 아직 안 망했거나 그 이후에 망했다
        active_then=(st["ld"] <= t1) & (~st["closed"] | (st["cd"] > t1)),
    )
    cols = ["open_recent", "close_recent", "open_prev", "close_prev", "active_now", "active_then"]
    parts = []
    for level, keys in (("구군", ["gu"]), ("동", ["gu", "dong"]), ("대구", [])):
        agg = (st.groupby(keys)[cols].sum().reset_index() if keys
               else st[cols].sum().to_frame().T)
        agg["level"] = level
        parts.append(agg)
    cyc = pd.concat(parts, ignore_index=True)
    cyc[cols] = cyc[cols].astype(int)
    # 행마다 판정 규칙을 적용한다. result_type="expand" 는 함수가 돌려준 dict 를 여러 열로 펼친다.
    staged = cyc.apply(lambda r: classify_stage(r["open_recent"], r["close_recent"], r["open_prev"],
                                                r["close_prev"], r["active_now"], r["active_then"]),
                       axis=1, result_type="expand")
    cyc = pd.concat([cyc, staged], axis=1)
    cyc["window_recent"] = f"{t1.date()} ~ {ref.date()}"
    cyc["window_prev"] = f"{t0.date()} ~ {t1.date()}"

    # 연도별 개업·폐업·연말 영업점포 수
    yrs = []
    for level, keys in (("구군", ["gu"]), ("동", ["gu", "dong"]), ("대구", [])):
        o = st.assign(year=st["ld"].dt.year).groupby(keys + ["year"]).size().rename("opens")
        c = (st[st["closed"]].assign(year=st["cd"].dt.year).groupby(keys + ["year"]).size().rename("closes"))
        y = pd.concat([o, c], axis=1).fillna(0).astype(int).reset_index().sort_values(keys + ["year"])
        # 연말 영업 점포 수 = (그해까지 개업 누적) - (그해까지 폐업 누적). 누적합 한 번으로 구한다.
        net = y["opens"] - y["closes"]
        y["active_end_of_year"] = net.groupby([y[k] for k in keys]).cumsum() if keys else net.cumsum()
        y["level"] = level
        y["year"] = y["year"].astype(int)
        yrs.append(y[y["year"] >= 2000])
    area_year = pd.concat(yrs, ignore_index=True)
    area_year["partial_year"] = area_year["year"] == ref.year
    return cyc, area_year


# ─────────────────────────── 7. 생존분석 ───────────────────────────
def build_survival(st: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """그룹별 Kaplan-Meier 요약표 + 생존편향 점검용 연대별 1년 생존율."""
    # 2010년 이전 개업은 전산화 이전 단명 업소가 DB 에서 누락돼 생존율이 과대추정된다(기획서 문제 3).
    coh = st[st["ld"].dt.year >= C.SURVIVAL_START_YEAR]
    rows = []

    def add(level, frame, **keys):
        if len(frame) < C.MIN_GROUP_N:  # 표본이 30건 미만이면 숫자를 믿을 수 없으니 아예 만들지 않는다
            return
        s = summarize(frame["dur_days"], frame["closed"])
        rows.append({"level": level, "service": keys.get("service"), "category": keys.get("category"),
                     "gu": keys.get("gu"), "dong": keys.get("dong"),
                     **{k: v for k, v in s.items() if k != "curve"},
                     "curve_json": json.dumps(s["curve"], ensure_ascii=False)})

    add("전체", coh)
    for sv, f in coh.groupby("service"):
        add("업종", f, service=sv)
    for cat, f in coh.groupby("category"):
        add("업태", f, category=cat, service=f["service"].mode().iat[0])
    for gu, f in coh.groupby("gu"):
        add("구군", f, gu=gu)
        for sv, ff in f.groupby("service"):
            add("구군×업종", ff, gu=gu, service=sv)
        for cat, ff in f.groupby("category"):
            add("구군×업태", ff, gu=gu, category=cat)
        for dong, ff in f.groupby("dong"):
            add("동", ff, gu=gu, dong=dong)
    surv = pd.DataFrame(rows)

    # 생존편향 점검용: 개업 연대별 1년 생존율 (전 기간).
    # 1990년대가 99.9% 로 나오는 것이 "데이터가 좋아서"가 아니라 "단명 업소가 기록되지 않아서"라는 증거다.
    # 이 숫자를 meta.json 에 남겨 두고 대시보드에서 근거로 보여 준다.
    decade = []
    for dec, f in st.assign(decade=(st["ld"].dt.year // 10) * 10).groupby("decade"):
        if dec < 1980 or len(f) < C.MIN_GROUP_N:
            continue
        s = summarize(f["dur_days"], f["closed"], curve_years=0)
        decade.append({"decade": f"{dec}년대", "n": s["n"], "survival_1y_pct": s["survival_1y_pct"]})
    return surv, decade


# ─────────────────────────── 8. 공실률 ───────────────────────────
def build_vacancy_area(units: pd.DataFrame) -> pd.DataFrame:
    """구·동별 공실률.

    분모 정의가 핵심이다. 1990년대에 사라진 자리까지 분모에 넣으면 공실률이 실제보다 낮아 보이므로,
    '최근 3년 안에 영업한 적이 있는 자리'만 분모로 삼는다. 기획서의 공실률보다 높게 나오는 이유다.
    """
    live = units[~units["vacant"] | (units["vacant_days"] <= C.VACANCY_MAX_DAYS)]
    out = []
    for level, keys in (("구군", ["gu"]), ("동", ["gu", "dong"])):
        g = live.groupby(keys).agg(units_3y=("uid", "size"), vacant=("recent_vacancy", "sum"),
                                   occupied=("vacant", lambda v: int((~v).sum())))
        g["vacancy_rate_pct"] = (g["vacant"] / g["units_3y"] * 100).round(1)
        g["level"] = level
        out.append(g.reset_index())
    return pd.concat(out, ignore_index=True)


# ─────────────────────────── main ───────────────────────────
def main() -> None:
    t_start = time.time()
    C.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    log("1/8 원본 적재")
    df, quality = load_raw()
    log("2/8 정제")
    df, ref = clean(df, quality)
    log(f"    기준일(데이터 최신일) = {ref.date()}")
    log("3/8 주소 정규화 · 좌표 변환(EPSG:5174→WGS84)")
    df = build_address(df, quality)

    keep = ["uid", "building_key", "service", "category", "name", "ld", "cd", "closed", "dur_days", "end", "gu", "dong",
            "floor", "도로명주소", "지번주소", "road_key", "lat", "lon", "area_m2", "관리번호", "개방자치단체코드"]
    st = df[keep].rename(columns={"도로명주소": "road_addr_raw", "지번주소": "jibun_addr_raw",
                                  "관리번호": "mgmt_no", "개방자치단체코드": "org_code"})

    log("4/8 자리(unit) 집계 · 동시영업 수 계산")
    units = build_units(st, ref)
    log("5/8 업종 전이")
    trans = build_transitions(st, units)
    log("6/8 상권 사이클")
    cycle, area_year = build_cycle(st, ref)
    log("7/8 Kaplan-Meier 생존분석")
    surv, decade = build_survival(st)
    log("8/8 공실률")
    vac = build_vacancy_area(units)

    # 업종 확장 효과 (문제4): 일반음식점만 봤다면 공실로 오판했을 자리
    latest = st.sort_values("ld").groupby("uid").tail(1).set_index("uid")
    switch = trans[(trans["from_service"] != trans["to_service"]) & (trans["to_closed"] == False)]  # noqa: E712
    switch_units = switch[switch["uid"].isin(latest.index[~latest["closed"]])]["uid"].nunique()

    naive_top = units.sort_values("n_closed", ascending=False).head(5)
    single = units[units["is_single_unit"]]
    single_top = single.sort_values("n_closed", ascending=False).head(5)

    meta = {
        "reference_date": str(ref.date()),
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "quality": quality,
        "records": {
            sv: {"total": int(len(f)), "closed": int(f["closed"].sum()), "active": int((~f["closed"]).sum()),
                 "unique_units": int(f["uid"].nunique()),
                 "date_min": str(f["ld"].min().date()), "date_max": str(max(f["ld"].max(), f["cd"].max()).date())}
            for sv, f in st.groupby("service")
        } | {"통합": {"total": int(len(st)), "closed": int(st["closed"].sum()),
                     "active": int((~st["closed"]).sum()), "unique_units": int(st["uid"].nunique())}},
        "records_by_gu": st["gu"].value_counts().to_dict(),
        "vacancy_buckets_all_vacant_units": units.loc[units["vacant"], "vacancy_bucket"].value_counts().to_dict(),
        "recent_vacancy_units": int(units["recent_vacancy"].sum()),
        "single_unit_ratio_pct": round(float(units["is_single_unit"].mean() * 100), 1),
        "max_closures_all_units_top5": naive_top[["addr", "n_closed", "max_concurrent"]].to_dict("records"),
        "max_closures_single_units_top5": single_top[["addr", "n_closed", "category_path"]].to_dict("records"),
        "service_switch_units": int(switch_units),
        "survival_by_decade_1y": decade,
        "params": {k: getattr(C, k) for k in ("SURVIVAL_START_YEAR", "VACANCY_MIN_DAYS", "VACANCY_MAX_DAYS",
                                               "HANDOVER_TOLERANCE_DAYS", "CYCLE_WINDOW_YEARS", "CYCLE_MIN_EVENTS")},
    }

    st.drop(columns=["end"]).to_parquet(C.PROCESSED_DIR / "stores.parquet", index=False)
    units.to_parquet(C.PROCESSED_DIR / "units.parquet", index=False)
    trans.to_parquet(C.PROCESSED_DIR / "transitions.parquet", index=False)
    cycle.to_parquet(C.PROCESSED_DIR / "area_cycle.parquet", index=False)
    area_year.to_parquet(C.PROCESSED_DIR / "area_year.parquet", index=False)
    surv.to_parquet(C.PROCESSED_DIR / "survival.parquet", index=False)
    vac.to_parquet(C.PROCESSED_DIR / "vacancy_area.parquet", index=False)
    (C.PROCESSED_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str),
                                               encoding="utf-8")
    log(f"완료 ({time.time() - t_start:.0f}초) → {C.PROCESSED_DIR}")


if __name__ == "__main__":
    main()
