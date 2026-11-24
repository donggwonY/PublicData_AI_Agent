"""인허가 42종을 공공데이터포털 API로 받는다 (E-04 데이터 주간 갱신, 2026-11-23).

파일 사이트(대구 전체 압축) 대신 업종별 API(`docs/e04/license_apis.json`)에서 대구 9개 자치단체 행만 받는다.
받은 행은 배치(`pipeline.build.load_raw`)가 읽는 한글 열 이름으로 바꿔 업종별 CSV 하나로 쓴다.

    # 전체(처음 한 번, 지금 파일과 대조용)
    python -m pipeline.fetch_license --full --out data/raw_api/full_20261123
    # 갱신분(지난 실행 이후 바뀐 행만)
    python -m pipeline.fetch_license --since "2026-11-06 00:00:00" --out data/raw_api/delta_20261123

- 인증키는 저장소 루트 .env 의 DATA_GO_KR_SERVICE_KEY. 키·요청 주소는 출력하지 않는다.
- 포털 응답이 들쭉날쭉해(2026-11-23 확인: 같은 API가 시간 초과 → 다음엔 정상) 시간 초과·5xx는 다시 시도한다.
- 업종 파일이 이미 있으면 건너뛴다. 업종 안에서는 구·군·페이지 단위로 .parts/ 에 중간 저장해 실패한 페이지부터 이어 받는다.
  --overwrite 로 다시 받는다.
- 결과 폴더의 manifest.json 에 업종·자치단체별 totalCount 와 받은 행 수를 남기고, 둘이 다르면 실패로 표시한다.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
ROOT = SERVICE_DIR.parent
sys.path.insert(0, str(SERVICE_DIR))
import config as C  # noqa: E402

APIS = ROOT / "docs/e04/license_apis.json"
# 대구 9개 개방자치단체코드(2026-11-06 대구 전체 압축의 실제 값): 중·동·서·남·북·수성·달서·달성 + 군위
DAEGU_CODES = ["3410000", "3420000", "3430000", "3440000", "3450000", "3460000", "3470000", "3480000", "5141000"]
PAGE = 100            # API 한 페이지 최대 행 수
TRIES = 10
# 배치가 읽는 열(build.USECOLS) ← API 필드. 업종에 없는 필드는 빈 값이 된다(배치도 없는 열을 빈 값으로 채운다).
FIELD_MAP = {
    "개방자치단체코드": "OPN_ATMY_GRP_CD", "관리번호": "MNG_NO", "인허가일자": "LCPMT_YMD",
    "영업상태명": "SALS_STTS_NM", "폐업일자": "CLSBIZ_YMD", "인허가취소일자": "LCPMT_RTRCN_YMD",
    "소재지면적": "LCTN_AREA", "사업장명": "BPLC_NM", "업태구분명": "BZSTAT_SE_NM", "위생업태명": "SNTTN_BZSTAT_NM",
    "데이터갱신구분": "DAT_UPDT_SE", "도로명주소": "ROAD_NM_ADDR", "지번주소": "LOTNO_ADDR",
    "좌표정보(X)": "CRD_INFO_X", "좌표정보(Y)": "CRD_INFO_Y", "최종수정시점": "LAST_MDFCN_PNT",
    "데이터갱신시점": "DAT_UPDT_PNT",
}


class AuthError(SystemExit):
    pass


def service_key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        k, _, v = line.partition("=")
        if k.strip() == "DATA_GO_KR_SERVICE_KEY":
            return v.strip().strip("\"'")
    raise SystemExit(".env 에 DATA_GO_KR_SERVICE_KEY 가 없습니다.")


def load_apis(services: list[str] | None = None) -> list[dict]:
    apis = json.loads(APIS.read_text(encoding="utf-8"))["apis"]
    if services:
        unknown = set(services) - {a["service"] for a in apis}
        if unknown:
            raise SystemExit(f"모르는 업종: {', '.join(sorted(unknown))}")
        apis = [a for a in apis if a["service"] in services]
    return apis


def file_name(api: dict) -> str:
    """'행정안전부_식품_일반음식점 조회서비스' → '식품_일반음식점_api.csv' (배치는 두 번째 칸을 업종으로 읽는다)."""
    group = api["title"].split("_")[1]
    return f"{group}_{api['service']}_api.csv"


def request(key: str, endpoint: str, page: int, cond: dict) -> dict:
    q = {"serviceKey": key, "pageNo": page, "numOfRows": PAGE, "returnType": "JSON"} | cond
    url = f"{endpoint}/info?{urllib.parse.urlencode(q)}"
    for attempt in range(TRIES):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                d = json.loads(r.read().decode("utf-8"))
            code = str(d["response"]["header"]["resultCode"])
            if code not in ("0", "00"):
                raise RuntimeError(f"resultCode {code} {d['response']['header'].get('resultMsg', '')}")
            return d["response"]["body"]
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise AuthError(f"{endpoint.rsplit('/', 1)[1]}: 인증 오류 HTTP {e.code} (활용신청·승인 확인)") from None
            if e.code < 500 and e.code != 429:
                raise RuntimeError(f"HTTP {e.code}") from None
            err = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError, KeyError, RuntimeError) as e:
            err = type(e).__name__ if not isinstance(e, RuntimeError) else str(e)
        if attempt < TRIES - 1:
            time.sleep(min(60, 5 * 2 ** attempt))
    raise RuntimeError(f"{TRIES}회 실패 ({err})")


def items_of(body: dict) -> list[dict]:
    it = body.get("items") or []
    if isinstance(it, dict):
        it = it.get("item", [])
    return [it] if isinstance(it, dict) else list(it)


def fetch_code(key: str, api: dict, code: str, since: str | None, part: Path | None = None,
               page_workers: int = 1) -> tuple[list[dict], int]:
    """한 업종·한 자치단체의 모든 페이지. 반환: (행, API totalCount).

    part 를 주면 페이지를 받을 때마다 중간 저장하고, 다시 부르면 아직 못 받은 페이지만 받는다.
    저장 형식: total, rows(1 ~ next-1 페이지를 이어 붙인 것), next, extra(next 이후에 따로 받은 페이지 {번호: 행}).
    page_workers > 1 이면 페이지를 동시에 받는다(포털이 페이지마다 수십 초 걸려, 2026-11-24 일반음식점 약 40초/페이지).
    """
    cond = {"cond[OPN_ATMY_GRP_CD::EQ]": code}
    if since:
        cond["cond[DAT_UPDT_PNT::GTE]"] = since
    st = json.loads(part.read_text(encoding="utf-8")) if part and part.exists() else None
    if st is None:
        first = request(key, api["endpoint"], 1, cond)
        st = {"total": int(first.get("totalCount") or 0), "rows": items_of(first), "next": 2}
    st.setdefault("extra", {})
    pages = (st["total"] + PAGE - 1) // PAGE
    lock = threading.Lock()

    def save():
        if part:
            part.write_bytes(json.dumps(st, ensure_ascii=False).encode("utf-8"))

    def one(page: int):
        got = items_of(request(key, api["endpoint"], page, cond))
        with lock:
            st["extra"][str(page)] = got
            while str(st["next"]) in st["extra"]:          # 앞에서부터 이어진 페이지는 rows 로 옮긴다
                st["rows"] += st["extra"].pop(str(st["next"]))
                st["next"] += 1
            save()

    todo = [n for n in range(st["next"], pages + 1) if str(n) not in st["extra"]]
    if page_workers > 1 and len(todo) > 1:
        with ThreadPoolExecutor(max_workers=page_workers) as ex:
            for f in as_completed([ex.submit(one, n) for n in todo]):
                f.result()
    else:
        for n in todo:
            one(n)
    if st["extra"]:
        raise RuntimeError(f"{code}: 이어지지 않는 페이지 {sorted(st['extra'])[:3]}")
    save()
    return st["rows"], st["total"]


def fetch_service(key: str, api: dict, out: Path, since: str | None, page_workers: int = 1) -> dict:
    t0 = time.time()
    rows, per_code = [], {}
    parts = out / ".parts"
    parts.mkdir(exist_ok=True)
    for code in DAEGU_CODES:
        part = parts / f"{api['service']}_{code}.json"       # 페이지마다 중간 저장(실패 후 다시 실행하면 이어 받기)
        got, total = fetch_code(key, api, code, since, part, page_workers)
        per_code[code] = {"total": total, "received": len(got)}
        rows += got
    path = out / file_name(api)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(list(FIELD_MAP))
        for r in rows:
            w.writerow([("" if r.get(src) is None else str(r.get(src)).strip()) for src in FIELD_MAP.values()])
    tmp.replace(path)
    for code in DAEGU_CODES:
        (parts / f"{api['service']}_{code}.json").unlink(missing_ok=True)
    missing = sorted({k for k in FIELD_MAP.values() if rows and k not in rows[0]})
    return {"service": api["service"], "file": path.name, "rows": len(rows), "per_code": per_code,
            "complete": all(v["total"] == v["received"] for v in per_code.values()),
            "fields_absent": missing, "seconds": round(time.time() - t0, 1)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--full", action="store_true", help="대구 전체 행")
    g.add_argument("--since", help='이 갱신시점(DAT_UPDT_PNT) 이후 바뀐 행만, 예 "2026-11-06 00:00:00"')
    ap.add_argument("--out", required=True, help="결과 폴더(service 기준 상대 경로 가능)")
    ap.add_argument("--services", nargs="*", help="일부 업종만")
    ap.add_argument("--workers", type=int, default=4, help="동시에 받을 업종 수")
    ap.add_argument("--page-workers", type=int, default=1, help="한 자치단체 안에서 동시에 받을 페이지 수")
    ap.add_argument("--overwrite", action="store_true", help="이미 받은 업종 파일도 다시 받기")
    a = ap.parse_args(argv)

    out = Path(a.out) if Path(a.out).is_absolute() else SERVICE_DIR / a.out
    out.mkdir(parents=True, exist_ok=True)
    key = service_key()
    apis = load_apis(a.services)
    todo = [x for x in apis if a.overwrite or not (out / file_name(x)).exists()]
    print(f"업종 {len(apis)}개 중 받을 것 {len(todo)}개 · {'전체' if a.full else '갱신분 ' + a.since} → {out}", flush=True)

    man_path = out / "manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {"services": {}}
    manifest.update({"mode": "full" if a.full else "since", "since": a.since, "codes": DAEGU_CODES,
                     "field_map": FIELD_MAP})
    failed = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(fetch_service, key, x, out, a.since, a.page_workers): x for x in todo}
        for f in as_completed(futs):
            name = futs[f]["service"]
            try:
                r = f.result()
            except AuthError as e:
                ex.shutdown(cancel_futures=True)
                raise SystemExit(str(e))
            except Exception as e:  # noqa: BLE001 — 한 업종 실패가 나머지를 막지 않게
                failed.append(name)
                print(f"[실패] {name}: {e}", flush=True)
                continue
            r["fetched_at"] = datetime.now().isoformat(timespec="seconds")
            manifest["services"][name] = r
            man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
            flag = "" if r["complete"] else "  ⚠ totalCount 와 받은 행 수가 다름"
            print(f"[완료] {name}: {r['rows']:,}행 ({r['seconds']}s){flag}", flush=True)
    done = {k: v for k, v in manifest["services"].items() if k in {x["service"] for x in apis}}
    incomplete = [k for k, v in done.items() if not v["complete"]]
    print(f"\n완료 {len(done)}/{len(apis)} · 실패 {len(failed)} {failed or ''} · 행 수 불일치 {incomplete or '없음'}"
          f" · 합계 {sum(v['rows'] for v in done.values()):,}행", flush=True)
    return 0 if not failed and not incomplete and len(done) >= len(apis) else 1


if __name__ == "__main__":
    sys.exit(main())
