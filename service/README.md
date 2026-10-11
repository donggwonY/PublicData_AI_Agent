# 상권 생애주기 추론 AI 에이전트 (대구)

### ▶ [웹앱 바로가기 — daegulifecycleagent.streamlit.app](https://daegulifecycleagent.streamlit.app)

대구에서 창업하려는 사람에게 **그 자리의 과거를 데이터로 확인시켜주는** 대화형 AI 에이전트.
행정안전부 지방행정 인허가 데이터(대구 7개 업종 197,356건)를 주소로 묶고 시간순으로 정렬해
공실·생존곡선·사이클·업종 전이·반복 폐업을 추론하고, LLM이 11개 Tool을 호출해 대화로 답한다.
소상공인 상가정보·주민등록 인구·도시철도 승하차 등 보조 데이터로 상권 유형과 업종 다양성까지 함께 본다.

> 이 폴더는 [daegu_lifecycle_agent](https://github.com/donggwonY/daegu_lifecycle_agent) `main`(1932844)에서 2026-10-11에 옮겨 온 서비스 코드다.
> 아래 명령은 모두 **`service/` 폴더 안에서** 실행한다. 팀 작업 흐름과 배포 절차는 저장소 루트의 [README](../README.md)와 [docs](../docs/)를 따른다.

## 빠른 시작

배포(Streamlit Cloud)와 같은 **Python 3.12 + 고정 버전**으로 돌리기 위해 가상환경 `.venv` 를 만들어 그 안에서만 실행한다.
시스템 `python` 으로 바로 돌리면 패키지 버전이 달라 로컬 결과가 배포와 같다고 보장할 수 없다.

```powershell
py -3.12 -m venv .venv                # 최초 1회. Python 3.12 가 없으면 먼저 설치
.venv\Scripts\Activate.ps1            # 터미널을 열 때마다 (macOS·Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt   # 웹만 돌릴 땐 requirements.txt

python -m pipeline.build          # 인허가 배치(약 40초) → data/processed
python -m pipeline.external       # 보조 데이터 배치(약 10초) → 상가정보·인구·지하철·주차장·전통시장
python -m unittest tests.test_core_units   # 주소 정규화·사이클 판정 단위 테스트 (데이터 불필요)
python -m tests.smoke_test        # Tool 11종 점검 (API 키 불필요)
streamlit run app.py              # 웹 UI
```

패키지 버전은 `requirements.txt`·`requirements-dev.txt` 에 `==` 로 고정돼 있다. 올릴 때는 `.venv` 에서 위 테스트를 다시 통과시킨 뒤 바꾼다.
야간 배치 `run_batch.ps1` 도 `.venv` 의 Python 만 쓰고, 종료 코드를 로그에 남긴다.

- **AI 상담** 탭은 LLM API 키가 필요하다. 기본은 **Google Gemini 무료 등급**(`LLM_PROVIDER="gemini"`), 설정 하나로 Claude 로 전환.
  키는 `.streamlit/secrets.toml`(예: `secrets.toml.example`) 또는 환경변수 `GEMINI_API_KEY` 에 두거나, 비워 두면 방문자가 사이드바에 자기 키를 입력한다.
  **대시보드 / 자리 이력 조회** 탭은 키 없이 동작한다.
- 터미널 대화: `python agent.py gemini` 또는 `python agent.py claude`

## 웹 배포 (Streamlit Community Cloud, 무료)

1. 배치 산출물(`data/processed`, 약 19MB)을 포함해 GitHub 에 푸시한다. 원본 CSV(`data/raw`)는 올리지 않는다.
2. https://share.streamlit.io 에서 GitHub 로 로그인 → **Create app** → 저장소 `donggwonY/PublicData_AI_Agent`, 브랜치 `deploy`, 파일 `service/app.py`.
   **Advanced settings** 에서 Python 3.12 선택, **Secrets** 에 `secrets.toml.example` 내용을 채워 붙여넣는다.
3. Deploy → `https://<이름>.streamlit.app` 주소로 공개된다. 멘티 작업은 `main` 에 쌓이고, 검증된 시점의 `main` 을 `deploy` 브랜치로 올린 뒤 Reboot 해야 공개 앱이 바뀐다.

데이터 갱신: 로컬에서 새 CSV 로 `python -m pipeline.build` → `data/processed` 커밋·푸시(`main`) → 검증 후 `deploy` 반영.

**운영자 키 보호 장치** — 운영자 키를 Secrets 에 넣으면 세션당 질문 수(`MAX_QUESTIONS_PER_SESSION`)와
전체 방문자 합산 분당 질문 수(`GLOBAL_QUESTIONS_PER_MINUTE`)를 제한한다. 무료 한도(429)에 걸리면 `config.GEMINI_MODELS`
순서대로 다음 모델을 시도한다(모델별 한도가 따로 잡힘). 방문자 키는 그 브라우저 세션에만 보관하고 서버 환경변수에 쓰지 않는다.
- MCP 서버(Claude Desktop·Claude Code 연결): `python mcp_server.py`

### API 키 없이 대화형 시연 — Claude Desktop + MCP

Claude Desktop 앱이 claude.ai 계정으로 대화를 처리하고, 이 프로젝트의 Tool 8종을 MCP 로 호출한다(API 결제 불필요).
설정 후 앱을 **완전히 종료했다가 재실행** → 채팅 입력창 `+` 메뉴에서 `daegu-lifecycle` 연결 확인 →
프롬프트 **"대구 창업 상권 상담 시작"**(`startup_consult`)을 선택하면 숫자 원칙이 적용된 상태로 상담을 시작한다.

`%APPDATA%\Claude\claude_desktop_config.json` 에 `mcpServers` 추가 (기존 설정은 유지):

```json
{
  "mcpServers": {
    "daegu-lifecycle": {
      "command": "C:\\claude_workspace\\PublicData_AI_Agent\\service\\.venv\\Scripts\\python.exe",
      "args": ["C:\\claude_workspace\\PublicData_AI_Agent\\service\\mcp_server.py"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

## 구조

```
data/raw/                 인허가 원본 CSV (CP949). 증분 파일도 여기에 추가 → 고유키 기준 최신 행 채택
data/external/            보조 데이터 CSV (상가정보·주민등록인구·도시철도·주차장·전통시장)
pipeline/build.py         인허가 배치: 정제 → 주소 정규화 → 좌표 변환 → 자리 집계 → 전이 → 사이클 → 생존 → 공실률
pipeline/external.py      보조 데이터 배치: 업종 구성·다양성 지수·상권 유형·인구·역별 승하차 집계
data/processed/           배치 산출물 (parquet + meta.json). Tool 은 여기만 조회
core/address.py           주소 정규화 (지번·도로명 파싱, 층 추출)
core/survival.py          Kaplan-Meier (영업 중 = 중도절단)
core/cycle.py             사이클 단계 판정 규칙
core/tools.py             Tool 8종 (근거 수치·정의·기준일을 반환값에 포함)
core/tool_specs.py        Claude API Tool 스키마
agent.py                  공통(시스템 프롬프트·Tool 실행) + Claude 도구 호출 루프 + create_agent(provider)
agent_gemini.py           Gemini 도구 호출 루프 (무료 등급, 모델 자동 대체)
mcp_server.py             같은 Tool 8종을 MCP 로 노출
app.py, ui_visuals.py     Streamlit UI (상담 · 대시보드 · 자리 이력)
run_batch.ps1             작업 스케줄러용 야간 배치 스크립트
tests/                    test_core_units(주소·사이클 단위), smoke_test(Tool), agent_loop_test·gemini_loop_test(가짜 클라이언트로 루프), mcp_check(MCP stdio)
```

## 기획서 → 구현 대응

| 기획서 | 구현 |
| --- | --- |
| 좌표계 EPSG:5174 → WGS84 | `pyproj` 변환, 대구 범위 밖 좌표는 결측 처리 |
| 고유키 3개 조합, 증분 I/U | `개방자치단체코드 + 관리번호 + 개방서비스ID`, `최종수정시점` 최신 행 채택 |
| 문제1 공실 67% 과대판정 | 공실 = 폐업 후 **90일~3년** 신규 인허가 없음 (`config.VACANCY_*`) |
| 문제2 백화점이 '죽음의 자리' | 시작/종료 이벤트 누적합 최댓값 = 동시영업 수. 같은 날 교체는 종료 먼저, 양도·양수 60일 중첩 허용 |
| 문제3 생존편향 | 생존분석 기본 코호트 **2010년 이후 개업** (`since_year` 로 변경 가능) |
| 문제4 업종 확장 | 일반+휴게 통합 자리 키. 업종 전환 자리 수를 meta 에 기록 |
| Tool 8종 | `get_market_cycle, find_vacant_units, get_survival_curve, get_unit_history, find_risk_spots, compare_areas, transition_matrix, normalize_address` |
| 9장 업종 확장 | 7종 197,356건(음식 3종 + 미용업·세탁업·노래연습장업·담배소매업). `config.SERVICES` 에 한 줄 + CSV 추가로 확장 |
| 9장 상권 유형·다양성 | 보조 데이터 Tool 3종 추가: `get_area_profile, find_nearby, get_station_traffic` |
| 설계 원칙 | 무거운 계산은 배치, Tool 은 조회(대부분 10~300ms) · 반환값에 n·정의·기준일 · 시스템 프롬프트 "Tool 이 반환한 값만" |

**자리(unit) 정의** — 건물 기본주소(지번 우선, 도로명은 지번으로 매핑) + 층. 층 기재는 2010년 이후 보편화(2000년대 18% → 2020년대 86%)되어,
층이 없는 과거 레코드는 해당 건물 층 기재의 80% 이상이 한 층일 때만 그 층으로 합산한다.

**사이클 판정** — 최근 3년 개업/폐업 비율 r, 직전 3년 rp: r≥1.1 성장기(rp<0.9 이면 회복기), 0.9≤r<1.1 성숙기, r<0.9 쇠퇴기(rp≥0.9 이면 쇠퇴 진입기), 이벤트 20건 미만 판정 보류.

## 실측 결과 (기준일 2026-09-08) — 기획서와의 차이

| 항목 | 기획서 | 이 구현 | 비고 |
| --- | --- | --- | --- |
| 전 기간 KM (전체/일반/휴게 중앙생존) | 6.6 / 7.4 / 4.4년 | **6.6 / 7.4 / 4.4년** | 1·3·5년 생존율까지 동일 재현 |
| 연대별 1년 생존율 | 99.9 / 91.9 / 88.8 / 80.5% | **동일** | |
| 2010년 이후 코호트 중앙생존 | — | 전체 5.1년, 일반 5.9, 휴게 3.9 | 에이전트 기본값. 기획서 6-1 표(전 기간)는 문제3 해결 전 수치 |
| 커피숍 중앙생존 | 4.7년 | 4.6년 (2010~), 카페 별칭 합산 4.7년 | |
| 고유 자리 수 | 96,399 (주소 문자열) | 55,628 (건물+층) | 같은 건물의 표기 차이(호수·건물명)를 합침 |
| 단일 점포 자리 비율 | 87.3% | 73.4% | 자리 정의가 넓어져 다점포 비율 상승 |
| 유효 공실(90일~3년) | 7,387 | 4,794 | 자리 수 차이에 비례 |
| 공실률 | 전체 자리 분모 (6.4~9.6%) | 최근 3년 내 영업한 자리 분모 (9.2~17.4%) | 오래 전 사라진 자리를 분모에서 제외 |
| 반복 폐업 최댓값(단일 점포) | 5건 | 11건 (달서구 달구벌대로 1734 1층) | |
| 업종 전환으로 공실 오판 방지 | 337곳 | 1,893곳 | 일반↔휴게 전환 후 현재 영업 중인 자리 |

## 보조 데이터 (2026-09 추가)

| 데이터 | 규모 | 쓰임 |
| --- | --- | --- |
| 소상공인 상가(상권)정보 2026-06 | 118,357개 점포(전 업종) | 업종 구성·다양성 지수·상권 유형 판정, 반경 내 경쟁 점포 |
| 주민등록 인구(행정동) 2026-08 | 대구 150개 행정동 | 인구 규모·연령 구성 |
| 대구교통공사 역별 승하차 2026-01~07 | 94개 역 | 유동인구 대리지표, 시간대 구성 |
| 전국주차장 표준데이터 | 대구 1,086곳 | 집객 여건 |
| 소상공인 전통시장 | 대구 106곳 | 시장상권 판정, 반경 내 시장 |

**상권 유형 판정** — 행정동의 업종 구성비를 대구 평균과 비교하되, 희소 업종에서 배수가 튀지 않도록 절대 비중 기준을 함께 요구한다.
우선순위: 시장상권(전통시장 + 소매 비중) → 유흥상권(음식 중 주점 18%↑) → 대학·학원가(교육 비중 + 청년 인구) →
오피스상권(과학·기술+부동산+임대) → 관광·숙박상권(숙박 3%↑) → 주거상권 → 혼합상권.
결과: 혼합 45 · 주거 36 · 대학·학원가 24 · 유흥 18 · 관광·숙박 11 · 오피스 9 · 시장 7곳.

**업종 다양성 지수** — 업종 중분류 구성의 Shannon 엔트로피를 0~1로 정규화. 대구 평균 0.823,
서문시장이 있는 중구 대신동은 0.362(소매 85% 쏠림).

**행정동 vs 법정동** — 인허가 주소는 법정동, 인구 통계는 행정동 기준이다. 상가정보에 두 값이 함께 있어
법정동→행정동 대표 매핑(212건)을 학습해 두 체계를 연결한다.

## 업종 확장 결과 (7종)

| 업종 | 레코드 | 폐업 | 영업 중 | 중앙생존(2010~) | 좌표 채움률 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 일반음식점 | 97,114 | 67,713 | 29,401 | 5.9년 | 95.9% |
| 담배소매업 | 33,750 | 27,323 | 6,427 | 4.2년 | 87.9% |
| 휴게음식점 | 30,972 | 21,871 | 9,101 | 3.9년 | 97.5% |
| 미용업 | 24,888 | 14,102 | 10,786 | 7.5년 | 97.3% |
| 제과점영업 | 4,001 | 3,000 | 1,001 | 2.9년 | 97.8% |
| 세탁업 | 3,584 | 2,629 | 955 | 7.4년 | 94.2% |
| 노래연습장업 | 3,051 | 1,673 | 1,378 | 관측기간 내 미도달 | 97.6% |
| **통합** | **197,356** | **138,307** | **59,049** | | |

- **자리 76,363곳** · 단일 점포 68.5% · 최근 공실 5,473곳
- **업종 전환으로 공실 오판을 막은 자리 2,789곳** (3종일 때 2,067곳) — 기획서 문제4
- 한 자리에 두 업종 이상이 거쳐간 곳 21,992곳. 대표 전이: 음식점↔미용업 1,783건, 담배소매업→일반음식점 227건
- 서빙 메모리 134MB, 산출물 34.6MB — 이 규모까지는 DB 없이 parquet 으로 충분하다

**업종별 스키마 차이** — 담배소매업·노래연습장업은 `업태구분명`·`소재지면적`이 없고 종료를 `인허가취소일자`로 기록한다.
없는 열은 적재 시 빈 값으로 채우고, 업태가 없으면 업종명을 업태로 쓴다.

**단명 폐업 경고** — 제과점영업은 폐업의 29.5%가 30일 이내다. 백화점 지하 팝업(신세계동대구 '뵈르카페' 21건,
현대백화점 '네쥬' 14건 등)이 섞인 결과다. 생존분석 결과에 단명 비율이 10%를 넘으면 경고 문구가 자동으로 붙는다.

## 한계

- 인허가는 영업 신고 기록이다. 매출·임대료·유동인구·폐업 사유는 알 수 없다.
- 공실은 "음식점 인허가 공백"이다. 소매·사무실 등 타 업종 전환 가능성이 있어 현장 확인이 필요하다.
- 확장(미용업·세탁업 등 동일 스키마)은 `config.SERVICES` 에 업종명·서비스ID 를 추가하고 CSV 를 `data/raw` 에 넣으면 된다.
