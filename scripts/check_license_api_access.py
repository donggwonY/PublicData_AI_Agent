"""인허가 42종 API 활용신청 확인 (E-04 데이터 갱신, 2026-11-22).

docs/e04/license_apis.json 의 업종별 API를 한 건씩(numOfRows=1) 불러 승인 여부만 확인한다.
인증키는 저장소 루트 .env 의 DATA_GO_KR_SERVICE_KEY 를 읽고, 키·요청 주소·응답 원문은 출력하지 않는다.

실행: service/.venv/Scripts/python scripts/check_license_api_access.py [업종 ...]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APIS = ROOT / "docs/e04/license_apis.json"


def service_key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        k, _, v = line.partition("=")
        if k.strip() == "DATA_GO_KR_SERVICE_KEY":
            return v.strip().strip("\"'")
    raise SystemExit(".env 에 DATA_GO_KR_SERVICE_KEY 가 없습니다.")


def probe(key: str, endpoint: str, tries: int = 3) -> tuple[str, str]:
    """반환: (상태, 설명). 상태는 OK / 미승인 / 오류. 시간 초과·연결 오류는 tries 번까지 다시 시도한다."""
    q = urllib.parse.urlencode({"serviceKey": key, "pageNo": 1, "numOfRows": 1, "returnType": "JSON"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(f"{endpoint}/info?{q}", timeout=60) as r:
                body = r.read().decode("utf-8", "replace")
            break
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return "미승인", f"HTTP {e.code}"
            if e.code < 500 or attempt == tries - 1:          # 5xx(서버 일시 오류)만 다시 시도
                return "오류", f"HTTP {e.code}" + (f" ({tries}회 시도)" if e.code >= 500 else "")
            time.sleep(5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == tries - 1:
                return "오류", f"{type(e).__name__} ({tries}회 시도)"
            time.sleep(5 * (attempt + 1))
    try:
        d = json.loads(body)
    except json.JSONDecodeError:
        # 키가 등록되지 않으면 XML 오류 문서가 200으로 오기도 한다
        return ("미승인", "등록되지 않은 키") if "SERVICE_KEY" in body else ("오류", "JSON 아님")
    head = d.get("response", {}).get("header", d.get("header", {})) if isinstance(d, dict) else {}
    code = str(head.get("resultCode", d.get("resultCode", "")))
    total = d.get("response", {}).get("body", {}).get("totalCount") if isinstance(d.get("response"), dict) else None
    return ("OK", f"전국 {total:,}건" if isinstance(total, int) else f"resultCode {code}") if code in ("0", "00", "") else ("오류", f"resultCode {code}")


def main() -> int:
    key = service_key()
    apis = json.loads(APIS.read_text(encoding="utf-8"))["apis"]
    only = set(sys.argv[1:])              # 업종 이름을 주면 그 업종만 확인(예: 실패한 것만 다시)
    if only:
        apis = [a for a in apis if a["service"] in only]
    counts = {"OK": 0, "미승인": 0, "오류": 0}
    for a in apis:
        status, note = probe(key, a["endpoint"])
        counts[status] += 1
        print(f"[{status:3}] {a['service']:<16} {note}" + (f"  → {a['page']}" if status != "OK" else ""), flush=True)
        time.sleep(0.3)
    print(f"\n승인 {counts['OK']} · 미승인 {counts['미승인']} · 오류 {counts['오류']} / {len(apis)}")
    return 0 if counts["OK"] == len(apis) else 1


if __name__ == "__main__":
    sys.exit(main())
