"""보조 데이터 배치: 상가정보·인구·지하철·주차장·전통시장 → 동네 맥락 테이블.

실행:  python -m pipeline.external          (build.py 와 독립적으로 돌아간다)
입력:  data/external/*.csv
산출:  data/processed/{poi,area_context,legal_admin_map,station_traffic,parking,market}.parquet

인허가 데이터가 '시간축'(누가 언제 열고 닫았나)을 준다면, 여기 데이터는 '현재 단면'(지금 이 동네가 어떤 곳인가)을 준다.
    소상공인 상가정보  현재 영업 중인 전 업종 점포 → 업종 구성·다양성 지수·상권 유형 (기획서 9장)
    주민등록 인구      행정동별 인구와 연령 구성
    지하철 승하차      역별 유동인구 대리지표
    주차장·전통시장     집객 시설

행정동 vs 법정동
    인허가 주소는 법정동(삼덕동1가), 인구 통계는 행정동(삼덕동)으로 집계된다.
    상가정보에는 두 값이 함께 있어서, 이 데이터로 법정동→행정동 대표 매핑을 학습해 둘을 잇는다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config as C  # noqa: E402

GU_LIST = ["중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군", "군위군"]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False), errors="coerce")


def read_external(key: str, **kwargs) -> pd.DataFrame | None:
    """data/external 의 CSV 를 읽는다. 파일이 없으면 None (해당 기능만 비활성화)."""
    path = C.EXTERNAL_DIR / C.EXTERNAL_FILES[key]
    if not path.exists():
        log(f"  없음: {path.name} → 건너뜀")
        return None
    for enc in ("utf-8-sig", "cp949"):
        try:
            df = pd.read_csv(path, encoding=enc, dtype=str, low_memory=False, **kwargs)
            log(f"  {path.name}: {len(df):,}행")
            return df
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"{path.name} 인코딩을 알 수 없습니다.")


# ─────────────────────────── 1. 상가정보 (현재 영업 점포) ───────────────────────────
def build_poi() -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    df = read_external("poi")
    if df is None:
        return None, None
    poi = pd.DataFrame({
        "name": df["상호명"].fillna("").str.strip(),
        "branch": df["지점명"],
        "cat_l": df["상권업종대분류명"], "cat_m": df["상권업종중분류명"], "cat_s": df["상권업종소분류명"],
        "gu": df["시군구명"], "admin_dong": df["행정동명"], "legal_dong": df["법정동명"],
        "floor": df["층정보"], "addr": df["도로명주소"].fillna(df["지번주소"]),
        "lat": _num(df["위도"]), "lon": _num(df["경도"]),
    }).dropna(subset=["lat", "lon"])
    poi = poi[poi["gu"].isin(GU_LIST)]

    # 법정동 → 행정동 대표 매핑 (가장 많이 함께 나타난 조합)
    pairs = (poi.dropna(subset=["legal_dong", "admin_dong"])
             .groupby(["gu", "legal_dong", "admin_dong"]).size().reset_index(name="n"))
    total = pairs.groupby(["gu", "legal_dong"])["n"].transform("sum")
    pairs["share"] = (pairs["n"] / total).round(3)
    mapping = pairs.sort_values("n").drop_duplicates(["gu", "legal_dong"], keep="last")
    return poi.reset_index(drop=True), mapping.reset_index(drop=True)


# ─────────────────────────── 2. 인구 (행정동) ───────────────────────────
AGE_BUCKETS = {"age_0_14": range(0, 15), "age_15_29": range(15, 30), "age_30_49": range(30, 50),
               "age_50_64": range(50, 65), "age_65_plus": range(65, 111)}


def build_population() -> pd.DataFrame | None:
    df = read_external("population")
    if df is None:
        return None
    df = df[df["시도명"] == "대구광역시"]
    out = pd.DataFrame({
        "gu": df["시군구명"], "admin_dong": df["읍면동명"],
        "pop_total": _num(df["계"]), "pop_male": _num(df["남자"]), "pop_female": _num(df["여자"]),
    })
    for label, ages in AGE_BUCKETS.items():
        cols = [c for a in ages for c in (f"{a}세남자", f"{a}세여자") if c in df.columns]
        out[label] = sum(_num(df[c]) for c in cols)
    out["pop_ref_month"] = df["기준연월"].iloc[0] if len(df) else None
    for label in AGE_BUCKETS:
        out[label + "_pct"] = (out[label] / out["pop_total"] * 100).round(1)
    return out.reset_index(drop=True)


# ─────────────────────────── 3. 지하철 승하차 ───────────────────────────
HOUR_COLS = [f"{h:02d}시-{h + 1:02d}시" for h in range(5, 24)]
TIME_SLOTS = {"morning_07_09": ["07시-08시", "08시-09시"],
              "lunch_11_14": ["11시-12시", "12시-13시", "13시-14시"],
              "evening_17_20": ["17시-18시", "18시-19시", "19시-20시"],
              "night_22_24": ["22시-23시", "23시-24시"]}


def build_station_traffic() -> pd.DataFrame | None:
    df = read_external("subway_hourly")
    if df is None:
        return None
    cols = [c for c in HOUR_COLS if c in df.columns]
    for c in cols + ["일계"]:
        df[c] = _num(df[c])
    days = df.groupby(["역명", "월", "일"]).ngroups / max(df["역명"].nunique(), 1)

    g = df.groupby(["역명", "승하차"])[cols + ["일계"]].sum().reset_index()
    wide = g.pivot(index="역명", columns="승하차", values="일계").fillna(0)
    out = pd.DataFrame({
        "station": wide.index,
        "daily_boarding": (wide.get("승차", 0) / days).round(0),
        "daily_alighting": (wide.get("하차", 0) / days).round(0),
    })
    out["daily_total"] = out["daily_boarding"] + out["daily_alighting"]

    # 시간대 구성 (하차 기준 = 그 동네로 들어오는 사람)
    alight = g[g["승하차"] == "하차"].set_index("역명")
    denom = alight[cols].sum(axis=1).replace(0, np.nan)
    for slot, slot_cols in TIME_SLOTS.items():
        use = [c for c in slot_cols if c in alight.columns]
        out[slot + "_pct"] = (alight[use].sum(axis=1) / denom * 100).round(1).reindex(out["station"]).to_numpy()
    peak = alight[cols].idxmax(axis=1).reindex(out["station"])
    out["peak_hour"] = peak.to_numpy()
    out["period"] = f"{df['월'].min()}~{df['월'].max()}월 일평균"
    return out.sort_values("daily_total", ascending=False).reset_index(drop=True)


# ─────────────────────────── 4. 주차장 · 전통시장 ───────────────────────────
def build_parking() -> pd.DataFrame | None:
    df = read_external("parking")
    if df is None:
        return None
    addr = df["소재지도로명주소"].fillna(df["소재지지번주소"]).fillna("")
    df = df[addr.str.startswith("대구")]
    out = pd.DataFrame({
        "name": df["주차장명"], "kind": df["주차장구분"], "addr": addr[df.index],
        "slots": _num(df["주차구획수"]), "lat": _num(df["위도"]), "lon": _num(df["경도"]),
    }).dropna(subset=["lat", "lon"])
    out["gu"] = out["addr"].str.split().str[1]
    return out.reset_index(drop=True)


def build_market() -> pd.DataFrame | None:
    df = read_external("market")
    if df is None:
        return None
    addr = df["소재지도로명주소"].fillna(df["소재지지번주소"]).fillna("")
    df = df[addr.str.startswith("대구")]
    out = pd.DataFrame({
        "name": df["시장명"], "kind": df["시장유형"], "addr": addr[df.index],
        "stores": _num(df["점포수"]), "parking": df["주차장보유여부"],
        "lat": _num(df["위도"]), "lon": _num(df["경도"]),
    }).dropna(subset=["lat", "lon"])
    out["gu"] = out["addr"].str.split().str[1]
    return out.reset_index(drop=True)


# ─────────────────────────── 5. 동네 맥락 (행정동 단위) ───────────────────────────
def shannon_diversity(counts: pd.Series) -> float:
    """업종 다양성 지수 0~1. 한 업종에 쏠릴수록 0, 고르게 퍼질수록 1 (기획서 9장)."""
    p = counts[counts > 0] / counts.sum()
    if len(p) <= 1:
        return 0.0
    return float(-(p * np.log(p)).sum() / np.log(len(p)))


def classify_market_type(r: dict, city: dict) -> tuple[str, str]:
    """업종 구성으로 상권 유형을 고르고 판정 근거 문장을 함께 돌려준다.

    비율(시 평균 대비 배수)만 쓰면 숙박처럼 전체 비중이 1%뿐인 희소 업종에서 배수가 쉽게 튄다.
    그래서 '절대 비중 기준'과 '시 평균 대비'를 함께 요구하고, 우선순위가 높은 규칙부터 확인한다.
    """
    if r["poi_total"] < C.MIN_POI_FOR_PROFILE:
        return "표본 부족", f"점포 {r['poi_total']}개로 판정 보류"
    food, retail = r["food_share_pct"], r["retail_share_pct"]
    youth, city_youth = r.get("age_15_29_pct"), city["youth_pct"]

    if r.get("market_count", 0) >= 1 and retail >= city["retail"] * 1.3:
        return "시장상권", f"전통시장 {int(r['market_count'])}곳 · 소매 비중 {retail}%(시 평균 {city['retail']}%)"
    if r["pub_share_of_food_pct"] >= 18 and food >= city["food"]:
        return "유흥상권", f"음식 중 주점 비중 {r['pub_share_of_food_pct']}%(시 평균 {city['pub']}%) · 음식 비중 {food}%"
    if r["edu_share_pct"] >= city["edu"] * 1.5 and youth is not None and youth >= city_youth:
        return "대학·학원가", f"교육 비중 {r['edu_share_pct']}%(시 평균 {city['edu']}%) · 15~29세 {youth}%(시 평균 {city_youth}%)"
    if r["office_share_pct"] >= city["office"] * 1.4 and r["personal_share_pct"] <= city["personal"]:
        return "오피스상권", f"과학·기술+부동산+임대 비중 {r['office_share_pct']}%(시 평균 {city['office']}%)"
    if r["lodging_share_pct"] >= max(city["lodging"] * 3, 3.0):
        return "관광·숙박상권", f"숙박 비중 {r['lodging_share_pct']}%(시 평균 {city['lodging']}%)"
    if r["personal_share_pct"] >= city["personal"] * 1.1 and food <= city["food"]:
        return "주거상권", f"수리·개인서비스+보건 비중 {r['personal_share_pct']}%(시 평균 {city['personal']}%) · 음식 비중 {food}%"
    return "혼합상권", f"음식 {food}% · 소매 {retail}% 모두 시 평균({city['food']}% / {city['retail']}%)에 가까움"


OFFICE_CATS = ["과학·기술", "부동산", "시설관리·임대"]
PERSONAL_CATS = ["수리·개인", "보건의료"]


def _share(g: pd.DataFrame, cats: list[str]) -> float:
    return round(g["cat_l"].isin(cats).mean() * 100, 1)


def build_area_context(poi: pd.DataFrame, pop: pd.DataFrame | None, park: pd.DataFrame | None,
                       market: pd.DataFrame | None) -> pd.DataFrame:
    """행정동별 업종 구성·다양성·상권 유형 + 인구·주차장·전통시장을 한 표로."""
    rows = []
    for (gu, dong), g in poi.groupby(["gu", "admin_dong"]):
        food = g[g["cat_l"] == "음식"]
        pub = (food["cat_m"] == "주점").mean() * 100 if len(food) else 0.0
        rows.append({
            "gu": gu, "admin_dong": dong,
            "poi_total": len(g), "poi_food": len(food),
            "food_share_pct": round(len(food) / len(g) * 100, 1),
            "retail_share_pct": _share(g, ["소매"]),
            "edu_share_pct": _share(g, ["교육"]),
            "office_share_pct": _share(g, OFFICE_CATS),
            "personal_share_pct": _share(g, PERSONAL_CATS),
            "lodging_share_pct": _share(g, ["숙박"]),
            "pub_share_of_food_pct": round(pub, 1),
            "diversity_index": round(shannon_diversity(g["cat_m"].value_counts()), 3),
            # parquet 은 dict 를 첫 행의 키로 고정된 구조체로 저장해 다른 행의 키가 사라진다 → JSON 문자열로 저장
            "top_categories_json": json.dumps(g["cat_m"].value_counts().head(8).to_dict(), ensure_ascii=False),
            "lat": float(g["lat"].median()), "lon": float(g["lon"].median()),
        })
    ctx = pd.DataFrame(rows)

    if pop is not None:
        ctx = ctx.merge(pop, on=["gu", "admin_dong"], how="left")
    # 좌표만 있는 시설은 가장 가까운 점포의 행정동에 배정해 집계한다
    for src, prefix, value_col in ((park, "parking", "slots"), (market, "market", "stores")):
        if src is None:
            continue
        agg = (_assign_dong(src, poi).groupby(["gu", "admin_dong"])
               .agg(**{f"{prefix}_count": ("name", "size"), f"{prefix}_{value_col}": (value_col, "sum")})
               .reset_index())
        ctx = ctx.merge(agg, on=["gu", "admin_dong"], how="left")
    for col in ("parking_count", "parking_slots", "market_count", "market_stores"):
        if col in ctx:
            ctx[col] = ctx[col].fillna(0)

    # 시 평균: 각 동을 같은 기준으로 비교하기 위한 기준선
    city = {
        "food": round((poi["cat_l"] == "음식").mean() * 100, 1),
        "retail": _share(poi, ["소매"]),
        "edu": _share(poi, ["교육"]),
        "office": _share(poi, OFFICE_CATS),
        "personal": _share(poi, PERSONAL_CATS),
        "lodging": _share(poi, ["숙박"]),
        "pub": round((poi[poi["cat_l"] == "음식"]["cat_m"] == "주점").mean() * 100, 1),
        "youth_pct": round(float(ctx["age_15_29_pct"].median()), 1) if "age_15_29_pct" in ctx else 0.0,
        "diversity": round(shannon_diversity(poi["cat_m"].value_counts()), 3),
    }
    judged = ctx.apply(lambda r: classify_market_type(r.to_dict(), city), axis=1, result_type="expand")
    ctx["market_type"], ctx["market_type_basis"] = judged[0], judged[1]
    for k, v in city.items():
        ctx[f"city_{k}"] = v
    return ctx


def _assign_dong(points: pd.DataFrame, poi: pd.DataFrame) -> pd.DataFrame:
    """좌표만 있는 시설(주차장·시장)을 가장 가까운 상가정보 점포의 행정동에 배정한다."""
    plat, plon = np.radians(poi["lat"].to_numpy()), np.radians(poi["lon"].to_numpy())
    out = points.copy()
    dongs, gus = [], []
    for lat, lon in zip(np.radians(out["lat"].to_numpy()), np.radians(out["lon"].to_numpy())):
        d = (plat - lat) ** 2 + ((plon - lon) * np.cos(lat)) ** 2  # 가까운 거리 비교용 근사
        i = int(np.argmin(d))
        dongs.append(poi["admin_dong"].iat[i])
        gus.append(poi["gu"].iat[i])
    out["admin_dong"], out["gu"] = dongs, gus
    return out


def main() -> None:
    t0 = time.time()
    C.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    log("1/5 상가정보")
    poi, mapping = build_poi()
    if poi is None:
        raise SystemExit("상가정보 CSV 가 없어 보조 데이터 배치를 건너뜁니다.")
    log("2/5 주민등록 인구")
    pop = build_population()
    log("3/5 지하철 승하차")
    station = build_station_traffic()
    log("4/5 주차장 · 전통시장")
    park, market = build_parking(), build_market()
    log("5/5 동네 맥락 집계")
    ctx = build_area_context(poi, pop, park, market)

    poi.to_parquet(C.PROCESSED_DIR / "poi.parquet", index=False)
    mapping.to_parquet(C.PROCESSED_DIR / "legal_admin_map.parquet", index=False)
    ctx.to_parquet(C.PROCESSED_DIR / "area_context.parquet", index=False)
    for name, df in (("station_traffic", station), ("parking", park), ("market", market)):
        if df is not None:
            df.to_parquet(C.PROCESSED_DIR / f"{name}.parquet", index=False)
    log(f"완료 ({time.time() - t0:.0f}초) · 점포 {len(poi):,} · 행정동 {len(ctx)} · "
        f"역 {0 if station is None else len(station)} · 주차장 {0 if park is None else len(park)} · "
        f"시장 {0 if market is None else len(market)}")


if __name__ == "__main__":
    main()
