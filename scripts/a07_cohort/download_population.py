"""A-07 코호트 추가 실험용 입력: 행안부 행정동별 연령별 인구(월간, 거주자, 10세 구간)를 다시 받는다.

- 출처: https://jumin.mois.go.kr/ageStatMonth.do (전체읍면동현황 CSV, 등록구분 거주자 sltUndefType=Y)
- 2016-01~2026-10을 3개월씩 요청하고, 전국 응답의 SHA-256을 기록한 뒤 대구 행만 UTF-8로 저장한다.
- 저장: data/raw/a07_cohort/src/ (Git 제외). 이미 받은 구간은 건너뛴다.
실행(저장소 루트): python scripts/a07_cohort/download_population.py [--single-age]
  --single-age: 1세 단위(0~99세, 100세 이상), 성별 구분 없이 합계만. 저장 data/raw/a07_cohort/src_1y/ (C안, docs/a07/cohort_plan_c.md)
"""
import hashlib
import sys
import http.cookiejar
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SINGLE = "--single-age" in sys.argv
OUT = ROOT / ("data/raw/a07_cohort/src_1y" if SINGLE else "data/raw/a07_cohort/src")
PAGE = "https://jumin.mois.go.kr/ageStatMonth.do"
URL = "https://jumin.mois.go.kr/downloadCsvAge.do?searchYearMonth=month&xlsStats=3"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def chunks(start=(2016, 1), end=(2026, 10), size=3):
    y, m = start
    while (y, m) <= end:
        months = []
        for _ in range(size):
            if (y, m) > end:
                break
            months.append((y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        yield months[0], months[-1]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA), ("Referer", PAGE)]
    opener.open(PAGE, timeout=60).read()
    manifest_path = OUT / "sources.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    for (ys, ms), (ye, me) in chunks():
        name = f"pop_{ys}{ms:02d}_{ye}{me:02d}.csv"
        if name in manifest and (OUT / name).exists():
            continue
        form = {"sltOrgType": "1", "sltOrgLvl1": "A", "sltOrgLvl2": "", "sum": "sum",
                "sltUndefType": "Y", "searchYearStart": str(ys), "searchMonthStart": f"{ms:02d}",
                "searchYearEnd": str(ye), "searchMonthEnd": f"{me:02d}", "sltOrderType": "1",
                "sltOrderValue": "ASC", "sltArgTypes": "1" if SINGLE else "10", "sltArgTypeA": "0",
                "sltArgTypeB": "100", "category": "month"}
        if not SINGLE:
            form["gender"] = "gender"  # B안 입력은 성별 열을 포함한 형식으로 받았다(값 분석에는 합계만 사용)
        for attempt in range(3):  # 응답이 중간에 끊기면(IncompleteRead) 다시 요청
            try:
                raw = opener.open(urllib.request.Request(URL, data=urllib.parse.urlencode(form).encode()),
                                  timeout=180).read()
                break
            except Exception as exc:  # noqa: BLE001
                print(name, "재시도", attempt + 1, type(exc).__name__, flush=True)
                time.sleep(10)
        else:
            raise RuntimeError(f"{name}: 3회 실패")
        text = raw.decode("cp949")
        lines = text.splitlines()
        keep = [lines[0]] + [ln for ln in lines[1:] if ln.startswith('"대구광역시')]
        if len(keep) < 100:
            raise RuntimeError(f"{name}: 대구 행이 너무 적음({len(keep) - 1})")
        (OUT / name).write_text("\n".join(keep) + "\n", encoding="utf-8", newline="\n")
        manifest[name] = {"months": [f"{ys}-{ms:02d}", f"{ye}-{me:02d}"], "request_url": URL, "form": form,
                          "national_response_sha256": hashlib.sha256(raw).hexdigest(),
                          "national_response_bytes": len(raw), "daegu_rows": len(keep) - 1,
                          "received": time.strftime("%Y-%m-%d")}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(name, len(raw), "bytes, 대구", len(keep) - 1, "행", flush=True)
        time.sleep(4)
    print("DONE", len(manifest))


if __name__ == "__main__":
    main()
