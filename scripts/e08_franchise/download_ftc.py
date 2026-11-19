"""E-08 공정거래위원회 가맹정보 API 4종 내려받기 (2026-11-19).

- 브랜드 목록(15125467)            FftcBrandRlsInfo2_Service/getBrandinfo                    jngBizCrtraYr
- 브랜드별 가맹점 현황(15110241)    FftcBrandFrcsStatsService/getBrandFrcsStats               yr
- 브랜드 지역별 가맹·직영(15125490) FftcBrandFrcsDropInfo3_Service/getbrandFrcsDmsstus2       jngBizCrtraYr
- 외식 브랜드 통합정보(15165094)    FftcBrandFrcsBzmnIntgInfoEatoutTpbizStats2_Service/
                                   getBrandFrcsBzmnIntgInfoEatoutTpbiz2                       jngBizCrtrYr (브랜드 번호 가명)
출력(Git 제외): data/raw/e08_franchise/<api>_<연도>.jsonl.gz, sources.json(행 수·SHA-256·받은 시각).
개인 이름(가맹본부 대표자명)과 사업자·법인등록번호는 분석에 쓰지 않아 저장하지 않는다.
인증키는 저장소 루트 .env 의 DATA_GO_KR_SERVICE_KEY 를 읽고 출력하지 않는다.
실행(저장소 루트): service/.venv/Scripts/python scripts/e08_franchise/download_ftc.py [연도 ...]
"""
import gzip
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/raw/e08_franchise"
HOST = "https://apis.data.go.kr/1130000/"
APIS = {
    "brand_list": ("FftcBrandRlsInfo2_Service/getBrandinfo", "jngBizCrtraYr"),
    "brand_stats": ("FftcBrandFrcsStatsService/getBrandFrcsStats", "yr"),
    "brand_region": ("FftcBrandFrcsDropInfo3_Service/getbrandFrcsDmsstus2", "jngBizCrtraYr"),
    "eatout": ("FftcBrandFrcsBzmnIntgInfoEatoutTpbizStats2_Service/getBrandFrcsBzmnIntgInfoEatoutTpbiz2", "jngBizCrtrYr"),
}
DROP = {"jnghdqrtrsRprsvNm", "brno", "crno"}  # 대표자 이름·사업자/법인등록번호: 저장하지 않음
YEARS = [str(y) for y in range(2017, 2027)]
PAGE = 10000


def service_key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        k, _, v = line.partition("=")
        if k.strip() == "DATA_GO_KR_SERVICE_KEY":
            return v.strip().strip("\"'")
    raise SystemExit(".env 에 DATA_GO_KR_SERVICE_KEY 가 없습니다.")


def fetch(key: str, path: str, ypar: str, year: str, page: int) -> dict:
    q = urllib.parse.urlencode({"serviceKey": key, "pageNo": page, "numOfRows": PAGE, "resultType": "json", ypar: year})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(HOST + path + "?" + q, timeout=180) as r:
                d = json.loads(r.read().decode("utf-8"))
            if d.get("resultCode") not in ("00", None):
                raise RuntimeError(f"resultCode={d.get('resultCode')} {d.get('resultMsg')}")
            return d
        except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403):
                raise SystemExit(f"{path}: 인증 오류 {e.code} (활용 신청·승인 확인)") from None
            wait = 3 * (attempt + 1)
            print(f"    재시도 {attempt + 1}/5 ({type(e).__name__}) {wait}s 뒤", flush=True)
            time.sleep(wait)
    raise SystemExit(f"{path} {year} p{page}: 5회 실패")


def items_of(d: dict) -> list[dict]:
    it = d.get("items") or []
    if isinstance(it, dict):
        it = it.get("item", [])
    return [it] if isinstance(it, dict) else list(it)


def main():
    years = sys.argv[1:] or YEARS
    key = service_key()
    OUT.mkdir(parents=True, exist_ok=True)
    meta_path = OUT / "sources.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    for name, (path, ypar) in APIS.items():
        for year in years:
            t0 = time.time()
            first = fetch(key, path, ypar, year, 1)
            total = int(first.get("totalCount") or 0)
            rows = items_of(first)
            for page in range(2, (total + PAGE - 1) // PAGE + 1):
                rows += items_of(fetch(key, path, ypar, year, page))
            if len(rows) != total:
                raise SystemExit(f"{name} {year}: 받은 행 {len(rows)} ≠ totalCount {total}")
            f = OUT / f"{name}_{year}.jsonl.gz"
            body = "".join(json.dumps({k: v for k, v in r.items() if k not in DROP}, ensure_ascii=False) + "\n" for r in rows)
            f.write_bytes(gzip.compress(body.encode("utf-8"), mtime=0))
            meta[f.name] = {"api": path, "year": year, "rows": total,
                            "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                            "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
            print(f"{name} {year}: {total:,}행 {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
