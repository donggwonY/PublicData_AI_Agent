# E-01 데모 실행·구조·배포 흐름 재현

담당: 염동권 · 기간: 2026-09-30 ~ 2026-10-12 · 상태: **완료** — 남은 위험은 E-04로 넘김

이 문서는 참고 구현(데모)이 **어디서 계산되고, 무엇을 로드하며, 어떻게 배포되는지**를 실제 코드와 실행 결과로 확인하고, 그 결과로 정한 것을 정리한다. 앞부분(1~5절)은 **현재 상태와 따라 할 절차**, 뒷부분(부록)은 **조사 당시 기록**이다. "확인"은 코드를 읽거나 직접 실행한 항목, "미검증"은 문서만 근거인 항목이다.

**데모를 내 PC에서 실행해 보려면 [3절 로컬 재현 절차](#3-로컬-재현-절차-팀원용)부터 본다.**

## 한눈에 보기

| 항목 | 현재 |
| --- | --- |
| 코드 위치 | 이 저장소의 `service/` (2026-10-11 원래 저장소 [daegu_lifecycle_agent](https://github.com/donggwonY/daegu_lifecycle_agent) `main` 1932844에서 이전) |
| 공개 앱 | [pubdai.streamlit.app](https://pubdai.streamlit.app) — `deploy` 브랜치 · `service/app.py` · Python 3.12 |
| 배포 방식 | `main` 푸시는 공개 앱을 바꾸지 않는다. 염동권이 `main` → `deploy` fast-forward 후 Reboot ([작업 흐름](../TEAM_WORKFLOW.md)) |
| 실행 환경 | Python **3.12** 가상환경 + `service/requirements.txt`의 `==` 고정 버전 (로컬과 배포가 같은 조합) |
| 데이터 | 앱 시작 시 13개 표를 메모리에 한 번 로드. 2026-10-16부터 출처는 Supabase DB, 실패 시 저장소 parquet ([E-02](../e02/README.md)) |
| 위험 R1~R8 | 해결 3 · 일부 해결 4 · 미해결 1 (4절) |
| 넘긴 일 | 전이 의존성 고정, 배치 실패 알림, 보조 데이터 시점 기록 → E-04 (5절) |

## 1. 결정 기록

| 날짜 | 결정 | 근거 | 결정 |
| --- | --- | --- | --- |
| 10-01 | 패키지를 검증된 버전으로 `==` 고정한다 (R6) | 앱이 시작될 때마다 최신 버전을 새로 설치하는 구조를 배포 로그로 확인. 발표 기간 안정성 우선. 고정값은 실제 서비스 중이던 조합(부록 A-4) | 염동권 |
| 10-01 | 팀 기준 Python을 3.12로 한다 (R7) | 배포가 3.12. 로컬 3.13·devcontainer 3.11과 달랐다 | 염동권 |
| 10-01 | 로컬은 `.venv`만 쓴다 (R8) | 로컬이 배포에서 "알려진 segfault"로 걸러지는 pyarrow 25.0.1로 테스트하고 있었다 | 염동권 |
| 10-11 | 서비스 코드를 이 저장소 `service/`로 옮기고, 공개 앱은 `deploy` 브랜치에서 배포한다 | 팀원이 서비스 코드에 접근하게 하면서 "직접 푸시 = 배포"를 막기 위해(부록 B) | 염동권 |
| 10-12 | pubdai.streamlit.app을 공식 주소로 한다. 기존 앱은 남기고 원래 저장소 README에 이전 안내 | 새 앱에서 로그·화면 확인 완료(부록 B-3) | 염동권 |

## 2. 현재 구성

### 2-1. 실행·배포 흐름

```
[염동권 PC] service/data/raw (인허가 CSV 16개), service/data/external (보조 CSV)   ← Git 제외
   │  python -m pipeline.build      (인허가)
   │  python -m pipeline.external   (보조 데이터)
   ▼
service/data/processed/*.parquet 13개 + meta.json                                  ← Git 커밋
   │  ├─ python -m pipeline.load_supabase … --activate  → Supabase app 스키마 (E-02)
   │  └─ main 푸시 (테스트 통과 후)
   ▼
deploy 브랜치 (염동권이 main 커밋을 fast-forward) → Streamlit Cloud Reboot
   │  app.py 시작 → core.tools.store() 가 13개 표를 메모리에 한 번 로드
   │                 (DB 먼저, 실패하면 저장소 parquet)
   ▼
대시보드·자리 이력 (키 불필요) / AI 상담 (Gemini 키: Secrets 또는 방문자 입력)
```

- 배치는 서버가 아니라 **개인 PC**에서 돈다. 원본 CSV가 Git에 없으므로 원본을 가진 PC에서만 재계산할 수 있다.
- `store()`는 `@lru_cache(maxsize=1)`로 **프로세스당 한 번** 로드하고 모든 방문자가 공유한다. 조회는 빠르고 실행 중 데이터가 일관되지만, 새 데이터를 반영하려면 Reboot가 필요하다. 첫 방문·슬립 복귀 때 로딩 지연이 있다.
- 접속이 없으면 앱이 잠들고 깨우는 데 수 초 걸린다. 발표 전에는 미리 접속해 깨운다.

### 2-2. 패키지

`service/requirements.txt`(웹)과 `service/requirements-dev.txt`(웹 + 로컬 전용 2개). 코드의 import와 대조해 빠진 패키지는 없다(2026-10-01 확인).

| 패키지 | 고정 버전 | 쓰는 곳 | 환경 |
| --- | --- | --- | --- |
| pandas | 3.0.6 | `core/tools.py`, `app.py`, `ui_visuals.py`, `pipeline/` | 웹·배치 |
| pyarrow | 24.0.0 | parquet 읽기·쓰기. 25.0.1은 Streamlit Cloud가 segfault 문제로 교체하므로 24 고정 | 웹·배치 |
| numpy | 2.5.3 | `core/survival.py`, `core/tools.py` | 웹·배치 |
| streamlit | 1.64.0 | `app.py`, `ui_visuals.py` | 웹 |
| plotly | 7.1.0 | `ui_visuals.py` 차트 | 웹 |
| pydeck | 0.9.3 | `ui_visuals.py` 지도 | 웹 |
| google-genai | 2.26.0 | `agent_gemini.py` | 웹 (AI 상담) |
| anthropic | 1.11.0 | `agent.py`. `app.py`가 import하므로 Gemini만 써도 필요 | 웹 |
| psycopg[binary] | 3.3.6 | `core/datasource.py` DB 읽기 (2026-10-16 추가, E-02) | 웹·적재 |
| pyproj | 3.8.0 | `pipeline/build.py` 좌표 변환 | 로컬 배치 |
| mcp | 2.2.0 | `mcp_server.py` | 로컬 MCP |

이 목록에 없는 전이 의존성(설치 로그 기준 약 51개)은 고정하지 않았다. 10일 사이 8개가 실제로 바뀌었다(부록 B-3). 버전을 올릴 때는 Python 3.12에서 같은 테스트를 다시 통과시킨 뒤 바꾼다.

### 2-3. 설정값과 비밀값

`app.py`는 `st.secrets` → 환경변수 → `config.py` 기본값 순서로 읽는다. 값은 이 문서에 적지 않는다.

| 이름 | 비밀 | 두는 곳 | 없을 때 |
| --- | --- | --- | --- |
| `GEMINI_API_KEY` | 비밀 | Streamlit Secrets (운영자 키) | 방문자가 사이드바에 자기 키 입력. 그 브라우저 세션에만 보관 |
| `LLM_PROVIDER` | 설정 | Secrets | `config.py` 기본값 `"gemini"` |
| `APP_DATABASE_URL` | 비밀 | Secrets. 읽기 전용 `app_reader` 접속 정보만 ([E-02 2-3절](../e02/README.md#2-3-권한)) | parquet로 읽음 |
| `APP_DATA_SOURCE`, `APP_DATA_VERSION` | 설정 | Secrets (필요할 때만) | `auto`, `current_version`이 가리키는 버전 |
| `MAX_QUESTIONS_PER_SESSION` / `GLOBAL_QUESTIONS_PER_MINUTE` | 설정 | Secrets에 없음 | 기본 20 / 3 |
| `ANTHROPIC_API_KEY` | 비밀 | 없음 (Claude로 바꿀 때만) | — |
| `GH_TOKEN` | 비밀 | 각 멘티 PC의 `.env` (이 저장소 푸시 전용) | 푸시 때 다시 요청 |

`.streamlit/secrets.toml`과 `.env`는 Git에서 제외되고 예시 파일 `service/.streamlit/secrets.toml.example`만 커밋한다.

## 3. 로컬 재현 절차 (팀원용)

데모 앱을 내 PC에서 띄우고 테스트를 돌리는 순서다. 가공 데이터(`service/data/processed`)가 저장소에 있어서 **원본 CSV 없이도 앱과 테스트가 돈다.** Windows 11에서 확인했고 macOS·Linux는 미검증이다.

### 3-1. 준비물

| 준비물 | 확인 | 없으면 |
| --- | --- | --- |
| 이 저장소 클론 | `git status` | `/mentee-init` 또는 `git clone https://github.com/donggwonY/PublicData_AI_Agent.git` |
| Python **3.12** | `py -3.12 --version` | `winget install Python.Python.3.12` 또는 python.org. 다른 버전이 있어도 함께 설치된다 |
| 디스크 여유 | 1GB 이상 | 가상환경 약 490MB (측정값) |

배포가 3.12라서 3.12로 맞춘다. 다른 버전으로도 실행은 될 수 있지만 결과가 배포와 같다고 보장할 수 없다.

### 3-2. 가상환경 (최초 1회)

PowerShell에서 저장소 루트 기준으로 실행한다. 저장소가 **경로가 긴 폴더**에 있으면 설치 중 `[WinError 206] 파일 이름이나 확장명이 너무 깁니다`가 난다(확인). 그때는 `C:\work`처럼 짧은 경로에 클론한다.

```powershell
cd service
py -3.12 -m venv .venv                # 약 10초
.venv\Scripts\Activate.ps1            # 프롬프트 앞에 (.venv) 가 붙는다
pip install -r requirements-dev.txt   # 약 2~3분
python --version                      # Python 3.12.x 확인
```

- `Activate.ps1`이 실행 정책 때문에 막히면(미검증) 켜지 않고 `.venv\Scripts\python.exe -m pip …`처럼 가상환경의 Python을 직접 부른다. 아래 명령도 `python` 자리에 `.venv\Scripts\python.exe`를 쓰면 된다(확인).
- macOS·Linux(미검증): `python3.12 -m venv .venv` → `source .venv/bin/activate`.
- 웹 화면만 볼 거면 `requirements.txt`만 설치해도 된다. `-dev`는 배치(pyproj)와 MCP 서버(mcp)를 더한다.

### 3-3. 테스트

터미널을 새로 열었으면 `service` 폴더에서 `.venv\Scripts\Activate.ps1`부터 실행한다.

```powershell
python -m unittest tests.test_core_units   # 기대: "Ran 14 tests ... OK"
python -m tests.smoke_test                  # 기대: 마지막 줄 "ALL PASSED 0"
```

`smoke_test` 출력의 `[ERR]` 3줄(삼덕동, 없는구, 없는주소)은 잘못된 입력을 제대로 거르는지 보는 의도된 검사다. API 키는 필요 없다.

### 3-4. 앱 실행

```powershell
streamlit run app.py
```

브라우저에서 `http://localhost:8501`이 열린다. 끝낼 때는 `Ctrl+C`. 로컬에는 DB 접속 정보가 없으므로 저장소 parquet를 읽는다.

아래 값이 보이면 공개 앱과 같은 데이터다(2026-10-16, 15업종 · 기준일 2026-10-13. 데이터를 갱신하면 달라진다).

| 위치 | 기대값 |
| --- | --- |
| 사이드바 누적 인허가 / 폐업 / 영업 중 | 225,858 / 154,315 / 71,543 |
| 사이드바 아래 | 기준일 2026-10-13 · 배치 2026-10-16 14:46:59 · 데이터 parquet (공개 앱은 db v3) |
| 대시보드, 지역 "대구 전체" | 상권 사이클 "쇠퇴 진입기" |
| 자리 이력 조회 `대구 중구 동성로5길 83` | "대구광역시 중구 동성로5길 83 1층", 인허가 레코드 6 |

**AI 상담 탭**은 Gemini API 키가 있어야 답한다. [Google AI Studio](https://aistudio.google.com/apikey)에서 본인 키를 받아 사이드바에 넣거나, `service\.streamlit\secrets.toml.example`을 `secrets.toml`로 복사해 채운다. 키를 코드·커밋·채팅·문서에 붙여넣지 않고, 공개 앱의 운영자 키는 공유하지 않는다.

### 3-5. 배치 재계산 (선택, 원본 CSV 필요)

분석·화면 확인만 할 때는 필요 없다. 원본 CSV는 Git에 없으므로 필요하면 염동권에게 받아 `service\data\raw\`(인허가 16개, 파일 목록은 [E-02 2-1절](../e02/README.md#2-1-데이터))와 `service\data\external\`(보조)에 둔다. 원본은 커밋하지 않는다.

```powershell
python -m pipeline.build       # 인허가 배치 → data\processed
python -m pipeline.external    # 보조 데이터 배치
```

- 원본이 없으면 `data\raw 에 인허가 CSV 가 없습니다.`로 끝나고 `data\processed`는 그대로다(확인).
- 배치는 `data\processed`를 **바로 덮어쓴다**(R1). 실행 후 `git status`로 바뀐 것을 보고, 의도하지 않았으면 `git checkout -- data/processed`로 되돌린다.
- 내용이 같아도 pyarrow 버전이 다르면 parquet 바이트가 달라져 "변경됨"으로 잡힌다.
- `data\processed` 변경을 `main`에 올리는 것과 DB 적재는 염동권과 확인한다([작업 흐름](../TEAM_WORKFLOW.md)).

### 3-6. 자주 막히는 곳

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| `[WinError 206] 파일 이름이나 확장명이 너무 깁니다` | 폴더 경로가 김 | 짧은 경로에 다시 클론 (확인) |
| `py -3.12`가 "not found" | 3.12 미설치 | 3-1대로 설치 후 새 터미널 |
| `python --version`이 3.12가 아님 | 가상환경이 꺼짐 | `.venv\Scripts\Activate.ps1` |
| 한글 깨짐, `UnicodeEncodeError` | 터미널 인코딩 | `$env:PYTHONIOENCODING = "utf-8"` 후 다시 |
| `data/processed 에 배치 산출물이 없습니다` | `data\processed`가 비었음 | `git checkout -- data/processed` |
| `ModuleNotFoundError: No module named 'tests'`·`'core'` | `service` 폴더 밖에서 실행 | `cd service` 후 실행 |
| 포트 8501 사용 중 | 다른 Streamlit이 떠 있음 | `streamlit run app.py --server.port 8502` |

## 4. 위험 요소 현재 상태 (2026-10-16)

| # | 위험 | 상태 | 근거·남은 부분 |
| --- | --- | --- | --- |
| R1 | 배치 저장 도중 실패하면 새 파일과 옛 파일이 섞인다 | 일부 해결 | 공개 앱이 읽는 DB는 버전 단위로 적재·검증 후 `current_version`만 바꾼다(E-02, 부록 A-3의 선택지 C). `pipeline/build.py`의 parquet 순차 덮어쓰기는 그대로 → 커밋 전 `git status` 확인 |
| R2 | 쓰는 도중 중단되면 깨진 parquet가 남는다 | 일부 해결 | R1과 같음 |
| R3 | 배치 실패를 알 수 없다 | 일부 해결 | `run_batch.ps1`이 종료 코드를 로그에 남기고 그 코드로 종료. 알림은 없음 → E-04 |
| R4 | 보조 데이터 갱신 시점이 기록되지 않는다 | 미해결 | `pipeline/external.py`가 `meta.json`을 갱신하지 않음. 15업종 확장 때도 보조 데이터는 다시 만들지 않아 시점이 인허가와 다름 → E-04 |
| R5 | README 수치가 실제와 다르다 | 일부 해결 | 15업종 확장 절은 추가됨. 그러나 `service/README.md` 첫 소개는 아직 "7개 업종 197,356건", 구조·MCP 설명은 "Tool 8종"(실제 11개), "실측 결과 (기준일 2026-09-08)" 절 그대로 |
| R6 | 재배포마다 최신 버전 설치 | 해결 (직접 지정 패키지) | `==` 고정 후 배포 로그에서 지정 버전 설치 확인. 전이 의존성은 미고정 → E-04 |
| R7 | 환경마다 Python 버전 다름 | 해결 | 팀 기준 3.12, 로컬·배포 모두 3.12. `service/.devcontainer`는 루트가 아니라 동작하지 않음(3.11 설정 그대로) |
| R8 | 로컬이 배포와 다른 패키지로 실행 | 해결 | 로컬도 `.venv` + 같은 고정 버전. 시스템 Python 직접 실행을 막는 장치는 `run_batch.ps1`에만 있음 |

위험이 처음 확인된 근거는 부록 A-3에 있다.

## 5. 남은 일

- [ ] 전이 의존성 고정 여부 (R6 남은 부분) → E-04
- [ ] 배치 실패 알림 (R3) → E-04
- [ ] `service/README.md` 첫 소개·Tool 수 표기를 15업종·11개로 갱신 (R5)
- [ ] 보조 데이터 시점 기록 (R4) → E-04 또는 보조 데이터 갱신 때
- [ ] 서버 메모리: 조사 당시 DataFrame 약 165MB(7업종). 15업종 확장과 DB 전환 후 Streamlit Cloud 한도 대비 확인 (E-02 운영 확인과 함께)
- [ ] Gemini 운영자 키의 무료 등급 한도가 분당 3질문(질문 1개 ≈ 모델 호출 2~4회)을 감당하는지 ([AI Studio Rate limits](https://aistudio.google.com/rate-limit))
- [ ] `service/.devcontainer` 정리 여부, D-01 보고서 스크립트가 출처로 적는 원래 저장소 주소·커밋(김세은 확인)

---

## 부록 A. 조사 기록 (2026-09-30 ~ 10-02, 원래 저장소 기준)

### A-1. 첫 로컬 실행 (2026-09-30, Windows 11, 시스템 Python 3.13)

| 단계 | 명령 | 결과 |
| --- | --- | --- |
| 단위 테스트 | `python -m unittest tests.test_core_units` | 14개 통과 |
| Tool 점검 | `python -m tests.smoke_test` | ALL PASSED, API 키 불필요 |
| 웹 UI | `streamlit run app.py` (10-01) | 기준일 2026-09-23, 대시보드·자리 이력 정상. 키가 없어 AI 상담은 입력란만 확인 |
| 데이터 로드 | `T.store()` 단독 측정 | 0.78초(import 0.81초 별도), DataFrame 합계 약 165MB, `data/processed` 디스크 34MB |
| 배치 재계산 | `pipeline.build`, `pipeline.external` (10-01, 3.12 `.venv`) | 임시 폴더로 실행해 커밋된 13개 parquet·`meta.json`과 내용 일치. 약 19초 + 4초 |

당시 데이터는 7업종, 누적 197,356 / 폐업 138,307 / 영업 중 59,049, 기준일 2026-09-23 · 배치 2026-09-29 21:16:54.

### A-2. 공개 앱·관리 화면 확인 (2026-10-01)

daegulifecycleagent.streamlit.app(당시 공개 앱)의 화면 수치와 기준일은 로컬과 같았다. 소유자 계정으로 본 관리 화면:

| 항목 | 결과 |
| --- | --- |
| 저장소·브랜치·메인 파일 | `donggwonY/daegu_lifecycle_agent` · `main` · `app.py` |
| Python | 3.12.14 (로컬 3.13과 다름 → R7) |
| Secrets | `LLM_PROVIDER`, `GEMINI_API_KEY` 2개. 질문 제한은 코드 기본값 |
| 설치 방식 | 시작할 때마다 `uv pip install`로 `requirements.txt`를 새로 해석해 59개 설치 → R6이 실제로 일어나는 구조 |
| 플랫폼 개입 | pyarrow 25.0.1을 "known segfault"(apache/arrow#50471)로 감지해 24.0.0으로 교체 → 로컬은 25.0.1로 테스트 중(R8) |
| 재배포 | `main` 푸시 후 Reboot로 반영. 푸시만으로 자동 재배포되는지는 미확인 |
| 슬립 | 접속이 없으면 잠들고 깨우는 데 수 초 |

배포와 로컬의 주요 패키지 차이: pandas 3.0.6/3.0.5, numpy 2.5.3/2.3.2, pyarrow 24.0.0/25.0.1, streamlit 1.64.0/1.63.0, plotly 7.1.0/7.0.0, google-genai 2.26.0/2.23.0, anthropic 1.11.0/1.5.0 (pydeck 같음). 이 배포 조합을 그대로 고정 버전으로 정했다.

### A-3. 위험이 처음 확인된 근거

| # | 근거 (원래 저장소 코드) |
| --- | --- |
| R1·R2 | `pipeline/build.py` 477–485행이 parquet 7개를 최종 경로에 순서대로 직접 쓰고 `meta.json`을 마지막에 씀. 계산 단계(1/8~8/8) 실패는 쓰기 전이라 안전하고, 저장 단계 실패만 문제 |
| R3 | `run_batch.ps1`이 종료 코드를 확인하지 않고 로그만 남김 |
| R4 | `pipeline/external.py`가 `meta.json`을 갱신하지 않음 |
| R5 | README "기준일 2026-09-08" ↔ `meta.json` 2026-09-23. Tool 수 "11개"와 "8종" 혼재(실제 등록 11개) |
| R6 | 모든 패키지가 `>=` 하한만 지정, lock 파일 없음 |
| R7 | 로컬 3.13 / devcontainer 3.11 / 배포 3.12 |
| R8 | A-2의 pyarrow 교체 |

R1·R2 개선 선택지 (원리는 모두 "새 결과를 다른 곳에 전부 쓰고, 검증한 뒤, 한 번에 바꾼다"):

| 선택지 | 방식 | 결과 |
| --- | --- | --- |
| A. 임시 폴더 후 교체 | `processed_tmp/`에 쓰고 검증 후 폴더 교체 | 채택 안 함 |
| B. 버전 폴더 + 포인터 | `processed/<기준일>/` + `current` | 채택 안 함 |
| C. DB 트랜잭션 적재 (염동권 제안) | 스테이징에 적재·검증 후 한 번에 교체 | E-02에서 버전 + `current_version` 방식으로 구현 |

### A-4. 고정 버전 적용 경과 (원래 저장소)

| 날짜 | 내용 |
| --- | --- |
| 10-01 | Python 3.12.10 `.venv` + 배포 조합 8개로 단위 14개·smoke·agent/gemini 루프 테스트(가짜 클라이언트, 등록 도구 11개)·앱 실행 통과 |
| 10-01 | [PR #10](https://github.com/donggwonY/daegu_lifecycle_agent/pull/10) 병합(`main` f553901) → Reboot. 배포 로그에서 8개 모두 지정 버전, pyarrow 교체 메시지 사라짐 |
| 10-01 | [PR #11](https://github.com/donggwonY/daegu_lifecycle_agent/pull/11) 병합(`main` 1932844): README·`run_batch.ps1`·실행 설정이 `.venv`만 사용, `requirements-dev.txt` 고정 |
| 10-02 | 새 폴더 클론 재현(아래 A-5) |

### A-5. 새 폴더 클론 재현 (2026-10-02, `main` 1932844, Python 3.12.10)

| 단계 | 결과 |
| --- | --- |
| `git clone` / `venv` 생성 | 7초 / 9초 |
| `pip install -r requirements-dev.txt` | 종료 코드 0, 139초 |
| 단위 테스트 / smoke | OK (14개) / ALL PASSED (`PYTHONIOENCODING` 유무 모두) |
| `streamlit run app.py` | 서버 상태 응답 `ok` |
| `pipeline.build` (원본 없음) | 안내 메시지와 함께 종료, `data\processed` 변경 없음 |

확인하지 못한 것: 실행 정책이 Restricted인 PC의 `Activate.ps1`, macOS·Linux, 팀원이 받은 원본으로 돌린 배치.

## 부록 B. 코드 이전 (2026-10-11 ~ 10-12)

### B-1. 선택지

당시 사실: 원래 저장소 협업자는 donggwonY 1명이라 다른 멘티는 서비스 코드를 수정할 수 없었고, 허브 저장소는 멘티 3명이 `main`에 직접 푸시하는 구조였다. 옮기면 "직접 푸시 = 배포"가 된다.

| | A. 분리 유지 | B. 허브로 전부 이전 | C. 역할 분리 |
| --- | --- | --- | --- |
| 방식 | 허브=문서, 데모=코드·배포 | 앱·배치·데이터를 허브로 | 허브=분석, 데모=서비스, 염동권이 PR로 반영 |
| 팀원 참여 | 코드 접근 불가 | 같은 곳에서 작업 | 서비스 반영은 염동권 경유 |
| 배포 안정성 | 높음 | 배포 전용 브랜치 필요 | 높음 |
| 이전 비용 | 없음 | 앱 재생성·Secrets 재입력·주소 변경 | 작음 |

10-01에는 보류(당시 에이전트 의견 C). **10-11에 B로 결정**하고 약점은 `deploy` 브랜치로 막았다. [구현 설계](../IMPLEMENTATION_DESIGN.md)·[작업 흐름](../TEAM_WORKFLOW.md)에 반영.

### B-2. 이전 실행 (2026-10-11)

| 항목 | 내용 |
| --- | --- |
| 가져온 것 | 원래 저장소 `main` 1932844 전체 파일을 `service/`에. 커밋 이력은 원래 저장소에 남김 |
| 내용 일치 | 가져온 직후 `service/` 트리 해시 = 원래 `main` 트리 해시(`e1d3bf4`) |
| 고친 것 | `service/README.md`(위치·배포 안내·MCP 경로), `service/run_batch.ps1`(주석 경로), `service/.claude/launch.json` 삭제 |
| 분석 스크립트 | D-01·D-02 스크립트 5개 경로를 `service/`로. 9개 재실행 결과 분석 수치·입력 13개 해시 동일 |
| 테스트 | 새 `.venv`에서 단위 14·smoke·MCP·앱 기동 통과. 루트 `tests/` 20개 중 18개(실패 2개는 이전부터 있던 Windows 파일 권한 검사) |
| 비밀값 검사 | `service/` 44개 파일, 해당 없음 |

### B-3. 배포 전환 (2026-10-11 ~ 10-12)

새 앱 pubdai.streamlit.app을 `deploy`(4e60b70)·`service/app.py`로 만들어 확인:

| 확인 | 결과 |
| --- | --- |
| 시작 로그 | `branch: 'deploy'`, `main module: 'service/app.py'`, Python 3.12.15, `service/requirements.txt`에서 설치 |
| 고정 8개 | 모두 지정 버전, pyarrow 교체 메시지 없음 |
| 화면 | 누적·기준일·대시보드 값이 기존 앱·로컬과 같음. AI 상담 "사용 가능", 남은 질문 20회(질문은 보내지 않음) |
| 테마 | 하위 폴더 배포에서도 주황 계열 적용(화면 비교) |

고정하지 않은 전이 의존성은 10일 사이 실제로 바뀌었다: google-auth 2.59.1→2.61.0, pydantic 2.13.5→2.14.0, pydantic-core 2.46.5→2.50.0, narwhals 2.26.0→2.27.1, httptools 0.8.0→0.9.0, pycparser 3.0→3.11, markupsafe 3.0.3→3.0.4, rpds-py 2026.6.3→2026.9.1, Python 3.12.14→3.12.15. 문제는 없었지만 R6 남은 부분의 근거다.

10-12 결정: pubdai.streamlit.app을 공식 주소로 쓴다. 기존 앱 daegulifecycleagent.streamlit.app은 원래 저장소 `main`에 연결된 채 이전 시점 스냅샷으로 남기고, 원래 저장소 README 맨 위에 이전 안내를 넣었다([PR #12](https://github.com/donggwonY/daegu_lifecycle_agent/pull/12)).

## 부록 C. 재현 확인 기록

| 날짜 | 환경 | 결과 |
| --- | --- | --- |
| 2026-10-02 | 원래 저장소 새 클론, Python 3.12.10 | 부록 A-5 |
| 2026-10-11 | 이 저장소 `service/` 새 `.venv` | 설치·단위/smoke·앱 기동 통과 |
| 2026-10-16 | `service/.venv`, 15업종 parquet | 단위 14개 OK, smoke ALL PASSED 0. 3-4절 기대값(누적 225,858, 기준일 2026-10-13, 대구 전체 "쇠퇴 진입기", 동성로5길 83 레코드 6)을 도구 호출로 확인 |
