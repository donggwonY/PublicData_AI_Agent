"""자리 주변 같은 업종 세기 (2026-11-21, E-13 후속).

두 출처로 센다.
A. 인허가(기본): 반경 안에서 같은 업태로 지금 영업 중인 가게. 앱의 주 자료라 모든 업태를 셀 수 있다.
   한 가게가 인허가를 여러 개 가진 경우(편의점의 담배소매업+휴게음식점 등)는 occupant_id 로 한 곳으로 센다.
B. 상가정보(보조): 인허가 업태와 상가정보 소분류의 대응을 데이터로 만든 뒤, 대응이 분명한 업태만 센다.
   대응표 = 같은 법정동 + 같은 상호로 이어진 영업 중 가게에서, 업태별로 가장 많이 붙은 소분류와 그 비율.
   소분류가 흩어지면 중분류로 한 번 더 본다. 비율이 POI_MAP_MIN_SHARE 이상이고 이어진 가게가
   POI_MAP_MIN_LINKED 곳 이상일 때만 쓴다. 중분류는 그 중분류에 대응한 가장 큰 업태에만 준다. 상가정보가 분기마다 바뀌어도 앱을 띄울 때 다시 계산한다.

같은 건물 안 가게는 '주변 경쟁'과 따로 센다(인허가는 building_key, 상가정보는 도로명 건물번호 일치).
"""
from __future__ import annotations

import re

import pandas as pd

import config as C
from core import address as A
from core import tools as T

POI_MAP_MIN_SHARE = 0.6
POI_MAP_MIN_LINKED = 30
_CACHE: dict = {}


def _norm_name(x) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", str(x).lower())


def active_stores() -> pd.DataFrame:
    """좌표가 있는 영업 중 인허가(단기 행사 등록 제외)."""
    s = T.store()
    key = ("active", id(s))
    if key not in _CACHE:
        st = s.stats_stores
        _CACHE[key] = st[~st["closed"] & st["lat"].notna() & st["lon"].notna()]
    return _CACHE[key]


def poi_category_map() -> pd.DataFrame:
    """인허가 업태 → 상가정보 분류 대응표. 열: category, level(cat_s|cat_m), poi_class, share, linked, active, usable."""
    s = T.store()
    key = ("poi_map", id(s))
    if key in _CACHE:
        return _CACHE[key]
    cols = ["category", "level", "poi_class", "share", "linked", "active", "usable"]
    if s.poi is None:
        _CACHE[key] = pd.DataFrame(columns=cols)
        return _CACHE[key]
    st = s.stats_stores
    act = st[~st["closed"]]
    act = act.assign(k=act["dong"].astype(str) + "|" + act["name"].map(_norm_name))
    poi = s.poi.assign(k=s.poi["legal_dong"].astype(str) + "|" + s.poi["name"].map(_norm_name))
    poi = poi.drop_duplicates("k", keep=False)[["k", "cat_m", "cat_s"]]   # 같은 동·같은 상호가 여러 곳이면 연결하지 않음
    m = act.drop_duplicates("occupant_id")[["category", "k"]].merge(poi, on="k", how="left")
    rows = []
    for cat, f in m.groupby("category"):
        best = (cat, None, None, 0.0, 0, len(f), False)
        # 소분류가 한쪽으로 몰리면 소분류, 아니면 중분류(예: 한식은 소분류가 백반·고기구이 등으로 흩어짐)
        for level in ("cat_s", "cat_m"):
            linked = f[level].dropna()
            if linked.empty:
                break
            vc = linked.value_counts(normalize=True)
            share = float(vc.iloc[0])
            ok = share >= POI_MAP_MIN_SHARE and len(linked) >= POI_MAP_MIN_LINKED
            if level == "cat_s" or ok:
                best = (cat, level, vc.index[0], round(share, 3), int(len(linked)), len(f), ok)
            if ok:
                break
        rows.append(best)
    out = pd.DataFrame(rows, columns=cols)
    # 중분류는 넓다(한식 = 백반·고기구이·탕 전부). 같은 중분류로 대응한 업태가 여럿이면 가장 큰 업태만 쓰고
    # 나머지(식육(숯불구이)·탕류 등)는 '한 가지로 대응하지 않음'으로 둔다. 숯불구이 경쟁을 한식 전체로 세지 않게.
    mid = out[out["usable"] & out["level"].eq("cat_m")]
    for cls, f in mid.groupby("poi_class"):
        keep = f["active"].idxmax()
        out.loc[f.index.difference([keep]), "usable"] = False
    _CACHE[key] = out
    return _CACHE[key]


def category_choices() -> list[str]:
    """화면 선택지: '카페' 묶음 + 지금 영업 중 가게가 있는 업태(많은 순)."""
    s = T.store()
    key = ("choices", id(s))
    if key not in _CACHE:
        counts = active_stores().drop_duplicates(["occupant_id", "category"])["category"].value_counts()
        _CACHE[key] = ["카페"] + [c for c in counts.index if c != "카페"]
    return _CACHE[key]


def category_label(category: str) -> str:
    """'한식' → '한식 (일반음식점)'. 업태 이름만으로 뜻이 흐린 경우(기타·영업장판매 등)를 구분한다."""
    if category == "카페":
        return "카페 (커피숍·다방 등 묶음)"
    s = T.store()
    key = ("svc", id(s))
    if key not in _CACHE:
        _CACHE[key] = active_stores().groupby("category")["service"].agg(lambda x: x.value_counts().index[0]).to_dict()
    svc = _CACHE[key].get(category)
    return f"{category} ({svc})" if svc and svc != category else category


def nearby_same_category(unit_id: str, category: str, radius_m: int = C.NEARBY_RADIUS_M) -> dict:
    """자리 반경 안 같은 업태 가게 수(인허가 기준 + 상가정보 기준)."""
    s = T.store()
    if unit_id not in s.units.index:
        raise T.ToolError("자리를 찾지 못했어요. 주소로 다시 조회해 주세요.")
    u = s.units.loc[unit_id]
    if pd.isna(u["lat"]) or pd.isna(u["lon"]):
        raise T.ToolError(f"'{u['addr']}'는 위치 정보가 없어 주변을 셀 수 없어요.")
    _, cats, label = T._resolve_category(category)
    cats = cats or [category]
    lat, lon, radius = float(u["lat"]), float(u["lon"]), int(radius_m)

    # A. 인허가
    act = active_stores()
    same = act[act["category"].isin(cats)]
    d = T._distance_m(lat, lon, same["lat"], same["lon"])
    near = same[d <= radius].assign(dist_m=d[d <= radius].round(0))
    in_bldg = near["building_key"].eq(u["building_key"]) if pd.notna(u["building_key"]) else pd.Series(False, index=near.index)
    outside = near[~in_bldg].sort_values("dist_m").drop_duplicates("occupant_id")
    permit = {
        "count": int(len(outside)),
        "in_building": int(near[in_bldg]["occupant_id"].nunique()),
        "examples": [{"name": r["name"], "category": r["category"], "dist_m": int(r["dist_m"])}
                     for _, r in outside.head(5).iterrows()],
        "basis": f"영업 인허가 기준일 {s.ref:%Y-%m-%d} · 지금 영업 중 · 같은 가게의 여러 인허가는 한 곳",
    }

    # B. 상가정보 (대응이 분명한 업태만)
    pm = poi_category_map()
    usable = pm[pm["category"].isin(cats) & pm["usable"]]
    poi_out = None
    if s.poi is not None and len(usable):
        mask = pd.Series(False, index=s.poi.index)
        for level, cls in zip(usable["level"], usable["poi_class"]):
            mask |= s.poi[level].eq(cls)
        targets = sorted(set(usable["poi_class"]))
        poi = s.poi[mask].drop_duplicates()
        dp = T._distance_m(lat, lon, poi["lat"], poi["lon"])
        pn = poi[dp <= radius]
        center = (A.parse_road(u["addr"]) or {}).get("key")
        same_bldg = (pn["addr"].map(lambda a: (A.parse_road(a) or {}).get("key")).eq(center)
                     if center else pd.Series(False, index=pn.index))
        poi_out = {
            "count": int((~same_bldg).sum()) if center else int(len(pn)),
            "in_building": int(same_bldg.sum()) if center else None,
            "includes_building": center is None,
            "poi_class": targets,
            "share_pct": [round(x * 100) for x in usable["share"]],
            "basis": f"상가(상권)정보 {C.POI_MONTH} · 분류 {', '.join(targets)}",
        }
    units = s.units.dropna(subset=["lat", "lon"])
    du = T._distance_m(lat, lon, units["lat"], units["lon"])
    vacancies = int(((du <= radius) & units["recent_vacancy"].astype(bool) & (units.index != unit_id)).sum())
    unmapped = pm[pm["category"].isin(cats) & ~pm["usable"]]
    return {
        "unit_id": unit_id, "category_label": label, "radius_m": radius,
        "permit": permit, "poi": poi_out, "vacancies": vacancies,
        "poi_note": None if poi_out else (
            "상가정보와 분류가 한 가지로 대응하지 않는 업태라 인허가 기준만 보여 줘요."
            if len(unmapped) else "상가정보에서 대응하는 분류를 찾지 못해 인허가 기준만 보여 줘요."),
    }
