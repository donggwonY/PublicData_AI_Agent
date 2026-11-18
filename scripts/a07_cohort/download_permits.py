"""A-07 30대 2단계 입력: 국토교통부 건축HUB 건축인허가 기본개요(대구 법정동별) 수집.

- 출처: https://www.data.go.kr/data/15136267/openapi.do (ArchPmsHubService/getApBasisOulnInfo)
- 법정동 코드: docs/d03/daegu_legal_codes.json (code.go.kr 법정동코드 전체자료, D-03이 2026-11-07 내려받음)
- 키: 로컬 .env 의 DATA_GO_KR_SERVICE_KEY (출력하지 않음)
- 저장: data/raw/a07_cohort/permits/ (Git 제외). 법정동별 JSON, 이미 받은 동은 건너뛴다.
실행(저장소 루트):
  python scripts/a07_cohort/download_permits.py --size   # 법정동별 전체 건수만(동마다 1회)
  python scripts/a07_cohort/download_permits.py          # 전체 수집(100행씩)
"""
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/raw/a07_cohort/permits"
URL = "https://apis.data.go.kr/1613000/ArchPmsHubService/getApBasisOulnInfo"
KEEP = ["platPlc", "sigunguCd", "bjdongCd", "bun", "ji", "mgmPmsrgstPk", "archGbCdNm", "mainPurpsCdNm",
        "hhldCnt", "hoCnt", "fmlyCnt", "archPmsDay", "stcnsSchedDay", "realStcnsDay", "useAprDay", "crtnDay"]


def key():
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"\s*DATA_GO_KR_SERVICE_KEY\s*=\s*(.*)", line)
        if m:
            return urllib.parse.unquote(m.group(1).strip().strip('"').strip("'"))
    raise SystemExit("DATA_GO_KR_SERVICE_KEY 없음")


def fetch(k, code, page, rows):
    q = urllib.parse.urlencode({"serviceKey": k, "sigunguCd": code[:5], "bjdongCd": code[5:], "numOfRows": rows,
                                "pageNo": page, "_type": "json"})
    for attempt in range(20):  # 게이트웨이 503 이 간헐적으로 나서 넉넉히 다시 시도한다
        try:
            d = json.loads(urllib.request.urlopen(f"{URL}?{q}", timeout=60).read())["response"]
            if str(d["header"].get("resultCode")) != "00":
                raise RuntimeError(d["header"])
            b = d.get("body", {})
            it = b.get("items", {})
            it = it.get("item", []) if isinstance(it, dict) else []
            return int(b.get("totalCount", 0)), [it] if isinstance(it, dict) else it
        except Exception as exc:  # noqa: BLE001
            print(code, page, "재시도", attempt + 1, type(exc).__name__, str(exc)[:120], flush=True)
            time.sleep(min(60, 5 * (attempt + 1)))
    raise RuntimeError(f"{code} {page} 실패")


def main():
    k = key()
    codes = json.loads((ROOT / "docs/d03/daegu_legal_codes.json").read_text(encoding="utf-8"))["codes"]
    dongs = sorted({c for c in codes.values() if not c.endswith("00000")})
    OUT.mkdir(parents=True, exist_ok=True)
    if "--size" in sys.argv:
        part = OUT / "sizes_partial.json"
        sizes = json.loads(part.read_text(encoding="utf-8")) if part.exists() else {}
        for c in dongs:
            if c in sizes:
                continue
            sizes[c] = fetch(k, c, 1, 1)[0]
            part.write_text(json.dumps(sizes), encoding="utf-8")
            time.sleep(0.25)
        total = sum(sizes.values())
        pages = sum(math.ceil(v / 100) for v in sizes.values())
        (OUT / "sizes.json").write_text(json.dumps({"dongs": len(dongs), "records": total, "pages": pages,
                                                    "by_code": sizes}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("법정동", len(dongs), "건수 있는 동", sum(v > 0 for v in sizes.values()), "전체 기록", total, "필요 요청", pages)
        return
    calls = 0
    for c in dongs:
        path = OUT / f"{c}.json"
        if path.exists():
            continue
        total, items = fetch(k, c, 1, 100)
        calls += 1
        for page in range(2, math.ceil(total / 100) + 1):
            items += fetch(k, c, page, 100)[1]
            calls += 1
            time.sleep(0.25)
        if len(items) != total:
            raise RuntimeError(f"{c}: {len(items)} != {total}")
        path.write_text(json.dumps({"code": c, "total": total, "received": time.strftime("%Y-%m-%d"),
                                    "items": [{f: x.get(f) for f in KEEP} for x in items]}, ensure_ascii=False),
                        encoding="utf-8")
        print(c, total, "누적 요청", calls, flush=True)
    print("DONE 요청", calls)


if __name__ == "__main__":
    main()
