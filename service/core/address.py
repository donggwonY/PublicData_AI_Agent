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
# 번지를 '*' 로 가린 원본 주소(2026-11-20 E-12: 건강기능식품·동물 업종 11,335건, 예 "대구광역시 남구 대명동 ****-*").
# 자리를 특정할 수 없으므로 자리 키는 만들지 않고, 구·읍면·동만 읽는다.
_MASKED_JIBUN = re.compile(
    r"^대구광역시\s+(?P<gu>\S+?[구군])\s+"
    r"(?:(?P<eup>\S+?[읍면])\s+)?"
    r"(?P<dong>\S+?(?:동|가|리)|남성로|시장북로)\s+(?:산\s*)?\*[\d*]*(?:\s*-\s*[\d*]+)?"  # 그 밖의 '…로'는 도로명
)
_MASKED_ROAD = re.compile(
    r"^대구광역시\s+(?P<gu>\S+?[구군])\s+"
    r"(?:(?P<eup>\S+?[읍면])\s+)?"
    r"(?P<road>\S+?(?:로|길))\s+(?:지하\s*)?\*[\d*]*(?:\s*-\s*[\d*]+)?"
)
# 이름이 '로'로 끝나는 대구 법정동(중구). 그 밖의 '…로'는 도로명이다(E-12 후속, 2026-11-20 확인).
LEGAL_DONGS_ENDING_RO = frozenset({"남성로", "시장북로"})
GU_NAMES = ("중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군", "군위군")
_GU_ANY = re.compile(r"^대구광역시\s*(?P<gu>" + "|".join(GU_NAMES) + r")")
_AREA_TOKEN = re.compile(r"[가-힣]+(?:\s*[\d.·]+\s*)?(?:동\d*가|동|가|리|읍|면)")
_PAREN_DONG = re.compile(r"\((?P<dong>[^,()]+?(?:동|가|리))(?:,|\))")
_FLOOR = re.compile(r"(지하\s*\d+\s*층|\d+\s*층)")
# 줄표 변형(‐ ‑ ‒ – — ― − －)은 '-'로 맞춘다. 그대로 두면 '28–6'의 부번을 버리고 '28' 자리를 찾는다(E-12 10절).
_DASHES = re.compile("[‐-―−－]")
_SHORT_GA = re.compile(r"^(?P<base>[가-힣]+?)(?P<ga>\d+가)$")


def _clean(s: str | None) -> str:
    """공백을 하나로 줄이고 시·도 표기를 '대구광역시'로 통일한다."""
    if not isinstance(s, str):
        return ""  # None 이나 결측값이 들어와도 예외 없이 빈 문자열로 처리
    s = _WS.sub(" ", _DASHES.sub("-", s.replace("　", " "))).strip()
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


def parse_masked(addr: str | None) -> dict | None:
    """번지가 '*' 로 가려진 주소 → 구·읍면·동(자리 키 없음). 가려진 주소가 아니면 None.

    예) "대구광역시 남구 대명동 ****-*" → gu=남구, eup=None, dong=대명동
        "대구광역시 군위군 군위읍 중앙길 ***-*" → gu=군위군, eup=군위읍, dong=None(도로명은 괄호 법정동이 있을 때만)
    """
    s = _clean(addr)
    m = _MASKED_JIBUN.match(s)
    if m:
        return {"gu": m["gu"], "eup": m["eup"], "dong": m["dong"]}
    m = _MASKED_ROAD.match(s)
    if m:
        pd_ = _PAREN_DONG.search(s)
        return {"gu": m["gu"], "eup": m["eup"], "dong": pd_["dong"].strip() if pd_ else None}
    return None


_ADMIN_DONG_NAME = re.compile(r"^(?P<base>\S+?)\d[\d.,]*동$")


def admin_to_legal_dong(dong: str | None) -> str | None:
    """행정동식 이름 → 같은 이름의 법정동 후보. '대명10동'→'대명동', '내당2.3동'→'내당동'. 아니면 None.

    후보일 뿐이다(성내1동처럼 같은 이름의 법정동이 없는 경우도 있다). 배치는 실제로 있는 법정동일 때만 쓴다.
    """
    m = _ADMIN_DONG_NAME.match(dong or "")
    return m["base"] + "동" if m else None


def short_ga_to_full(dong: str | None) -> str | None:
    """'동'을 뺀 약식 표기 → 법정동 후보. '삼덕1가'→'삼덕동1가', '노원3가'→'노원동3가'. 아니면 None.

    '동성로2가'·'종로1가'처럼 원래 '…로N가'인 법정동과 이미 '…동N가'인 이름은 해당 없다.
    """
    m = _SHORT_GA.match(dong or "")
    if not m or m["base"].endswith(("동", "로")):
        return None
    return f"{m['base']}동{m['ga']}"


def legal_dong_candidates(dong: str | None) -> list[str]:
    """지번에 적힌 동 이름의 법정동 후보(행정동식 이름·약식 '…N가' 보정). 확인은 부르는 쪽에서 한다."""
    return [c for c in (admin_to_legal_dong(dong), short_ga_to_full(dong)) if c]


def clean(s: str | None) -> str:
    """검색어 정리(공백·줄표·'대구시' 표기 통일). 공개용 이름."""
    return _clean(s)


def parse_area_loose(addr: str | None, known: dict[str, set[str]], area_gu: dict[str, str]) -> dict | None:
    """정규 형식으로 못 읽은 주소에서 구·동만 느슨하게 읽는다(자리 키는 만들지 않음, E-12 후속).

    예) "대구광역시 북구 태전동496-12"(번지와 붙여 씀) → 북구·태전동
        "대구광역시 남구 대명06동1052-1"(행정동식 번호) → 남구·대명동
        "대구광역시 동구신서동 543"(구와 동을 붙여 씀) → 동구·신서동
        "대구광역시 다사읍 세천로 80"(구 없음) → 달성군·다사읍 (area_gu: 한 구에만 있는 동·읍면 → 그 구)
    잘못 읽지 않도록, 결과는 정규 형식 주소에서 이미 확인된 그 구의 동(known[구])일 때만 받는다.
    군 지역은 배치와 같게 읍·면을 동 자리에 쓴다.
    """
    s = _clean(addr)
    if not s.startswith(SIDO):
        return None
    m = _GU_ANY.match(s)
    gu, rest = (m["gu"], s[m.end():]) if m else (None, s[len(SIDO):])
    for tok in _AREA_TOKEN.findall(rest):
        tok = re.sub(r"\s+", "", tok)
        cands = [re.sub(r"[\d.·]+동$", "동", tok), tok]   # 법정동 우선: 대명06동·내당2.3동 → 대명동·내당동
        for c in cands:
            g = gu or area_gu.get(c)
            if g and c in known.get(g, ()):
                return {"gu": g, "dong": c}
    return None


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
