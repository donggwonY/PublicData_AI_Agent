"""주소 정규화.

'자리(unit)' 의 키는 건물 단위 기본주소다.
  1순위: 지번 기본주소  (대구광역시 중구 삼덕동1가 28-6)   ← 1960년대 레코드까지 채워져 있음
  2순위: 도로명 기본주소 (대구광역시 중구 동성로5길 83)   → 지번이 함께 있는 레코드로 학습한 매핑으로 지번 키에 합류
층·호수는 연도별 기재 방식이 달라 키에서 제외하고, 다점포 건물 여부는 동시영업 수로 따로 판별한다.
"""
from __future__ import annotations

import re

SIDO = "대구광역시"

_WS = re.compile(r"\s+")
# 정규식의 (?P<gu>...) 는 '이름 붙은 그룹'. 매칭 결과를 m["gu"] 로 꺼낼 수 있어
# m.group(3) 보다 읽기 쉽고, 패턴 중간에 그룹을 추가해도 코드가 깨지지 않는다.
#   예) "대구광역시 달성군 다사읍 부곡리 691-4" → gu=달성군, eup=다사읍, dong=부곡리, main=691, sub=4
_JIBUN = re.compile(
    r"^대구광역시\s+(?P<gu>\S+?[구군])\s+"
    r"(?:(?P<eup>\S+?[읍면])\s+)?"
    r"(?P<dong>\S+?(?:동|가|리|로))\s+"
    r"(?P<san>산\s*)?(?P<main>\d+)(?:\s*-\s*(?P<sub>\d+))?"
)
_ROAD = re.compile(
    r"^대구광역시\s+(?P<gu>\S+?[구군])\s+"
    r"(?:(?P<eup>\S+?[읍면])\s+)?"
    r"(?P<road>\S+?(?:로|길))\s+"
    r"(?P<under>지하\s*)?(?P<main>\d+)(?:\s*-\s*(?P<sub>\d+))?"
)
_PAREN_DONG = re.compile(r"\((?P<dong>[^,()]+?(?:동|가|리))(?:,|\))")
_FLOOR = re.compile(r"(지하\s*\d+\s*층|\d+\s*층)")


def _clean(s: str | None) -> str:
    """공백을 하나로 줄이고 시·도 표기를 '대구광역시'로 통일한다."""
    if not isinstance(s, str):
        return ""  # None 이나 결측값이 들어와도 예외 없이 빈 문자열로 처리
    s = _WS.sub(" ", s.replace("　", " ")).strip()
    # 사용자가 "대구 수성구 ..." 처럼 줄여 쓴 경우
    if s.startswith("대구시 "):
        s = SIDO + s[3:]
    elif s.startswith("대구 "):
        s = SIDO + s[2:]
    return s


def _num(main: str, sub: str | None) -> str:
    """번지를 표준형으로. '0028'-'0006' → '28-6', '0061'-'0000' → '61'.

    같은 자리가 원본에 '0028-0006' 과 '28-6' 으로 다르게 적혀 있어도 같은 키가 되게 하는 정규화다.
    int() 를 거치면 앞자리 0이 자연스럽게 사라진다.
    """
    main = str(int(main))
    if sub and int(sub) != 0:
        return f"{main}-{int(sub)}"
    return main


def parse_jibun(addr: str | None) -> dict | None:
    """지번주소 → 자리 키. 파싱 실패 시 None.

    예) "대구광역시 중구 삼덕동1가 0028-0006 2층 " → key="대구광역시 중구 삼덕동1가 28-6"
    층·건물명 같은 뒤쪽 상세는 키에서 뺀다(층은 extract_floor 가 따로 뽑는다).
    """
    s = _clean(addr)
    m = _JIBUN.match(s)
    if not m:
        return None
    parts = [SIDO, m["gu"]]
    if m["eup"]:
        parts.append(m["eup"])
    parts.append(m["dong"])
    lot = ("산" if m["san"] else "") + _num(m["main"], m["sub"])
    parts.append(lot)
    return {"key": " ".join(parts), "gu": m["gu"], "eup": m["eup"], "dong": m["dong"]}


def parse_road(addr: str | None) -> dict | None:
    """도로명주소 → 자리 키 + 괄호 안 법정동.

    예) "대구광역시 중구 동성로5길 83, 2층 (삼덕동1가)" → key="대구광역시 중구 동성로5길 83", dong="삼덕동1가"
    도로명주소는 2014년 전면 시행이라 과거 레코드에는 비어 있는 경우가 많다.
    그래서 지번을 1순위 키로 쓰고, 도로명만 있는 레코드는 배치에서 지번 키에 합류시킨다
    (pipeline/build.py 의 road2jibun 매핑).
    """
    s = _clean(addr)
    m = _ROAD.match(s)
    if not m:
        return None
    parts = [SIDO, m["gu"]]
    if m["eup"]:
        parts.append(m["eup"])
    parts.append(m["road"])
    parts.append(("지하 " if m["under"] else "") + _num(m["main"], m["sub"]))
    pd_ = _PAREN_DONG.search(s)
    dong = pd_["dong"].strip() if pd_ else None
    return {"key": " ".join(parts), "gu": m["gu"], "eup": m["eup"], "dong": dong, "road": m["road"]}


def extract_floor(*addrs: str | None) -> str | None:
    """주소 문자열에서 층을 뽑는다. "지하 1 층" → "지하1층". 없으면 None.

    인자를 여러 개 받아 앞에서부터 먼저 찾아지는 값을 쓴다(도로명 → 지번 순으로 넘겨 쓴다).
    """
    for a in addrs:
        if isinstance(a, str):
            m = _FLOOR.search(a)
            if m:
                return _WS.sub("", m.group(1))
    return None


def normalize_gu(text: str | None) -> str | None:
    """'수성', '수성구', '대구 수성구' → '수성구'. 대구의 구·군이 아니면 None.

    사용자가 말한 지역명이나 AI 가 Tool 인자로 넘긴 문자열을 정확한 구 이름으로 맞추는 용도다.
    끝 글자를 뗀 약칭도 허용하므로 '동' 한 글자가 '동구'로 인식되는 한계가 있다(코드리뷰 연습 과제).
    """
    if not text:
        return None
    t = _clean(text).replace(SIDO, "").strip()
    for gu in ("중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군", "군위군"):
        if t == gu or t == gu[:-1] or t.startswith(gu + " ") or t.startswith(gu[:-1] + " "):
            return gu
    return None


def is_daegu(addr: str | None) -> bool:
    return _clean(addr).startswith(SIDO)
