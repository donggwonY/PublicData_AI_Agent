# E-01 데모 실행·구조·배포 흐름 재현

담당: 염동권 · 상태: 진행 중 · 대상: [daegu_lifecycle_agent](https://github.com/donggwonY/daegu_lifecycle_agent) `origin/main` (조사 시작 5d3e1cd → PR #10·#11 병합 후 1932844). 2026-10-11에 이 코드를 이 저장소의 `service/`로 옮겼다(9절)

**데모를 내 PC에서 실행해 보려면 [10절 로컬 재현 절차](#10-로컬-재현-절차-팀원용)부터 본다.**

이 문서는 참고 구현이 **어디서 계산되고, 무엇을 로드하며, 어떻게 배포되는지**를 실제 코드와 실행 결과로 확인한 기록이다. "확인"은 코드를 읽거나 직접 실행한 항목, "미검증"은 README 등 문서만 근거인 항목이다.

## 1. 실행·배포 흐름

```
[로컬 PC] data/raw (인허가 CSV 7종), data/external (보조 CSV 7종)   ← Git 제외
   │  python -m pipeline.build      (run_batch.ps1: 야간 스케줄 예시)
   │  python -m pipeline.external
   ▼
data/processed/*.parquet 13개 + meta.json                          ← Git 커밋 (약 35MB)
   │  git push origin main
   ▼
[Streamlit Community Cloud] main 푸시 → 자동 재배포 (미검증: README 근거)
   │  app.py 시작 → core.tools.store() 가 parquet 전부 메모리 로드 (확인)
   ▼
대시보드·자리 이력 (키 불필요) / AI 상담 (Gemini 키: Secrets 또는 방문자 입력)
```

- 배치는 서버가 아니라 **개인 PC**에서 돈다. 원본 CSV가 Git에 없으므로 원본을 가진 PC에서만 재계산할 수 있다. (확인: `.gitignore`)
- 배포본은 로컬 폴더가 아니라 **푸시된 커밋**을 읽는다. 로컬 배치가 실패해도 푸시하지 않으면 배포 서비스는 이전 스냅샷을 유지한다.

## 2. 로컬 재현 결과 (2026-09-30, Windows 11, Python 3.13)

| 단계 | 명령 | 결과 |
| --- | --- | --- |
| 패키지 | `pip install -r requirements-dev.txt` | 이미 설치됨 (streamlit 1.63, pandas 3.0, pyproj, mcp) |
| 단위 테스트 | `python -m unittest tests.test_core_units` | 14개 통과 |
| Tool 점검 | `python -m tests.smoke_test` | ALL PASSED, API 키 불필요 |
| 웹 UI | `streamlit run app.py` (2026-10-01) | 동작. 사이드바 기준일 2026-09-23 표시, 대시보드(대구 전체)·자리 이력(“대구 중구 동성로5길 83” → 1층 레코드 6건) 정상, 브라우저·서버 오류 없음. AI 상담 탭은 키가 없어 방문자 키 입력란만 확인 |
| 데이터 로드 | `T.store()` 단독 측정 | 로드 0.78초(모듈 import 0.81초 별도), 메모리의 DataFrame 합계 약 165MB, `data/processed` 디스크 34MB |
| 배치 재계산 | `python -m pipeline.build`, `python -m pipeline.external` (2026-10-01, Python 3.12 `.venv`) | 임시 폴더로 실행해 커밋된 `data/processed`와 parquet 13개·`meta.json` 내용 일치. 인허가 배치 약 19초, 보조 배치 약 4초 |

이 표는 처음 조사할 때의 기록이다(시스템 Python 3.13). 이후 기준 환경을 Python 3.12 `.venv`로 바꿨고, 지금 따라 할 절차는 10절에 있다.

## 3. 데이터 로딩 방식 (확인)

- `app.py` 36행이 화면을 그리기 전에 `T.store()`를 호출한다. `core/tools.py`의 `DataStore`가 parquet 13개와 `meta.json`을 한 번에 읽는다.
- `store()`는 `@lru_cache(maxsize=1)`로 **프로세스당 한 번** 로드하고 모든 방문자가 공유한다.
- 결과: 조회는 빠르고, 실행 중에는 메모리 스냅샷이 일관된다. 새 데이터 반영에는 프로세스 재시작(재배포)이 필요하다. 첫 방문과 슬립 복귀 시 로딩 지연이 있다.

## 4. 위험 요소

| # | 위험 | 근거 | 영향 |
| --- | --- | --- | --- |
| R1 | 저장 도중 실패하면 새 파일과 옛 파일이 섞인다 | `pipeline/build.py` 477–485행이 parquet 7개를 순서대로 직접 덮어쓰고 `meta.json`을 마지막에 씀 | 재시작 후 표끼리 숫자가 맞지 않고, 기준일은 옛 날짜로 표시 |
| R2 | 파일을 쓰는 도중 중단되면 깨진 parquet가 남을 수 있다 | `to_parquet`가 최종 경로에 바로 기록 | 앱 시작 실패 |
| R3 | 배치 실패를 알 수 없다 | `run_batch.ps1`이 종료 코드를 확인하지 않고 로그만 남김 | 실패한 결과를 모르고 푸시할 위험 |
| R4 | 보조 데이터의 갱신 시점이 기록되지 않는다 | `pipeline/external.py`가 `meta.json`을 갱신하지 않음 | 화면의 기준일과 보조 데이터 시점이 다를 수 있음 |
| R5 | README 수치가 실제와 다르다 | README "기준일 2026-09-08" ↔ `meta.json` `reference_date` 2026-09-23 (빌드 2026-09-29). Tool 개수도 "11개"와 "8종"이 섞여 있음 | 발표 자료 오류 위험 |

계산 단계(1/8~8/8)에서 실패하면 파일을 쓰기 전이라 이전 parquet가 그대로 남는다. 저장 단계에서 실패할 때만 R1·R2가 생긴다.

### 위험 요소 현재 상태 (2026-10-01)

R6~R8은 6절과 7절에서 확인한 위험이다.

| # | 위험 | 상태 | 근거 |
| --- | --- | --- | --- |
| R1 | 저장 도중 실패 시 parquet 섞임 | 미해결 | 선택지 A·B·C 정리(5절), E-02에서 판단 |
| R2 | 쓰는 도중 중단 시 깨진 parquet | 미해결 | R1과 같음 |
| R3 | 배치 실패를 알 수 없음 | 일부 해결 | `run_batch.ps1`이 종료 코드를 로그에 남기고 그 코드로 종료. 알림은 없음 |
| R4 | 보조 데이터 갱신 시점 미기록 | 미해결 | — |
| R5 | README 수치가 실제와 다름 | 일부 해결 | 도구 수 표기 1곳 수정. 기준일 2026-09-08 표기와 "Tool 8종" 나머지 표기는 그대로 |
| R6 | 재배포마다 최신 버전 설치 | 해결 (직접 지정 8개) | [PR #10](https://github.com/donggwonY/daegu_lifecycle_agent/pull/10) 병합, 배포 로그 확인. 전이 의존성 51개는 미고정 |
| R7 | 환경마다 Python 버전 다름 | 해결 | 팀 기준 3.12. README가 `py -3.12 -m venv .venv`로 안내. devcontainer는 3.11 그대로 |
| R8 | 로컬이 배포와 다른 패키지로 실행 | 해결 | [PR #11](https://github.com/donggwonY/daegu_lifecycle_agent/pull/11): README·`run_batch.ps1`·실행 설정이 `.venv`만 사용, `requirements-dev.txt` 고정. `.venv`에서 배치를 임시 폴더로 돌려 커밋된 `data/processed`와 parquet 13개·`meta.json` 내용 일치 확인 |

PR #11은 2026-10-01 09:45 UTC에 병합됐다 (`main` 1932844). 배포 파일은 바뀌지 않아 Reboot는 하지 않았다.

R8 한계: 각 PC에서 `.venv`를 만들어 쓰는 것은 README 안내에 따른다. 시스템 `python`으로 직접 실행하는 것을 막는 장치는 `run_batch.ps1`에만 있다. 같은 내용이어도 pyarrow 버전이 다르면 parquet 파일 바이트가 달라져 Git에는 변경으로 잡힌다.

## 5. 개선 선택지 (R1·R2)

원리는 모두 같다: **새 결과를 다른 곳에 전부 쓰고, 검증한 뒤, 한 번에 바꾼다.**

| 선택지 | 방식 | 장점 | 비용·전제 |
| --- | --- | --- | --- |
| A. 임시 폴더 후 교체 | `processed_tmp/`에 전부 쓰고 검증을 통과하면 폴더 교체 | 변경이 작고 지금 구조에서 바로 가능 | 교체 순간의 짧은 공백 |
| B. 버전 폴더 + 포인터 | `processed/<기준일>/`로 쌓고 `current`가 가리키는 버전만 로드 | 되돌리기 쉬움, 여러 버전 비교 가능 | 용량 증가, 로더 수정 |
| C. DB 트랜잭션 적재 (염동권 제안) | 스테이징 테이블에 적재하고 검증한 뒤 한 번에 교체 | Supabase 이전과 함께 해결, 서버 재시작 없이 갱신 가능 | E-02 범위. 테이블별 DELETE→INSERT로 적재하면 같은 문제가 재발하므로 적재 설계가 핵심 |

결정 보류: 선택지는 E-02(데이터 계약·Supabase 이행) 설계와 함께 판단한다.

## 6. 의존성·비밀값 목록 (확인, 2026-10-01)

### 6-1. 실행 환경별 패키지

`requirements.txt`는 웹 서비스용, `requirements-dev.txt`는 그것에 로컬 전용 2개를 더한다. 코드의 import와 대조했으며 빠진 패키지는 없다.

| 패키지 | 요구 버전 | 로컬 설치 | 쓰는 곳 | 필요한 환경 |
| --- | --- | --- | --- | --- |
| pandas | >=2.2 | 3.0.5 | `core/tools.py`, `app.py`, `ui_visuals.py`, `pipeline/` | 웹·배치 |
| pyarrow | >=15 | 25.0.1 | parquet 읽기·쓰기 (pandas가 내부 사용) | 웹·배치 |
| numpy | >=1.26 | 2.3.2 | `core/survival.py`, `core/tools.py` | 웹·배치 |
| streamlit | >=1.40 | 1.63.0 | `app.py`, `ui_visuals.py` | 웹 |
| plotly | >=5.24 | 7.0.0 | `ui_visuals.py` 차트 | 웹 |
| pydeck | >=0.9 | 0.9.3 | `ui_visuals.py` 지도 | 웹 |
| google-genai | >=1.0 | 2.23.0 | `agent_gemini.py` | 웹 (AI 상담) |
| anthropic | >=1.5 | 1.5.0 | `agent.py` (Claude 경로) | 웹 (`app.py`가 `agent`를 import하므로 Gemini만 써도 설치 필요) |
| pyproj | >=3.6 | 3.8.0 | `pipeline/build.py` 좌표 변환 | 로컬 배치 전용 |
| mcp | >=1.2 | 2.2.0 | `mcp_server.py` | 로컬 MCP 전용 |

Python 버전은 환경마다 다르다: 로컬 3.13(확인), devcontainer 3.11(`.devcontainer/devcontainer.json`), Streamlit Cloud 3.12(README 근거, 미검증).

### 6-2. 설정값과 비밀값

`app.py`의 `setting()`은 `st.secrets` → 환경변수 → `config.py` 기본값 순서로 읽는다. 값은 이 문서에 기록하지 않는다.

| 이름 | 비밀 여부 | 두는 곳 | 없을 때 동작 |
| --- | --- | --- | --- |
| `GEMINI_API_KEY` | 비밀 | Streamlit Cloud Secrets (운영자 키) | 방문자가 사이드바에 자기 키 입력. 그 키는 브라우저 세션(`st.session_state`)에만 보관 |
| `ANTHROPIC_API_KEY` | 비밀 | Secrets (Claude로 전환할 때만) | 위와 같음 |
| `LLM_PROVIDER` | 설정 | Secrets 또는 환경변수 | `config.py` 기본값 `"gemini"` |
| `MAX_QUESTIONS_PER_SESSION` | 설정 | Secrets | 기본 20. 운영자 키가 있을 때만 적용 |
| `GLOBAL_QUESTIONS_PER_MINUTE` | 설정 | Secrets | 기본 3. 전체 방문자 합산 |
| `GEMINI_MODELS`, `CLAUDE_MODEL` | 설정 | `config.py` (코드) | 429·404 응답 시 `GEMINI_MODELS` 순서대로 다음 모델 시도 |
| `GH_TOKEN` | 비밀 | 각 멘티 PC의 `.env` (이 협업 저장소 전용) | 푸시 시점에 다시 요청 |
| Supabase 접속 키 | 비밀 | 도입 시 Streamlit Cloud Secrets ([구현 설계](IMPLEMENTATION_DESIGN.md)) | 아직 없음 |

데모 저장소는 `.streamlit/secrets.toml`과 `.env`를 Git에서 제외하고, 예시 파일(`secrets.toml.example`)만 커밋한다. 로컬 PC에는 `secrets.toml`이 없어 AI 상담 탭은 방문자 키 입력 상태로 뜬다.

### 6-3. 의존성 위험

| # | 위험 | 근거 | 선택지 |
| --- | --- | --- | --- |
| R6 | 재배포 때마다 최신 버전이 설치될 수 있다 | 모든 패키지가 `>=` 하한만 지정하고 lock 파일이 없음. 로컬에는 이미 pandas 3.0, plotly 7.0 등 메이저 버전이 올라간 상태 | 상한 지정(`<3`) 또는 검증된 버전 고정, 재배포 전 smoke test |
| R7 | 세 환경의 Python 버전이 다르다 | 3.11 / 3.12 / 3.13 | 배포 버전 하나로 맞추고 문서화 |

**R6 결정안 (2026-10-01, 염동권):** 발표 기간의 안정성을 우선해 **검증된 버전을 `==`로 고정**한다. 메이저 상한만 두는 방식은 작은 업데이트가 자동으로 들어와 재현이 보장되지 않기 때문이다.

적용 전 조건 (미완료):
1. 고정할 버전 조합을 정한다. 우선 Streamlit Cloud 배포 로그에서 현재 서비스 중인 버전을 확인하고, 그것이 어려우면 배포 Python 버전(3.12 예정)에서 로컬 조합을 설치해 `tests.test_core_units`·`tests.smoke_test`를 통과시킨다. 로컬 조합(3.13)을 검증 없이 그대로 쓰지 않는다.
2. 데모 저장소 `requirements.txt` 변경은 `main` 푸시 즉시 재배포되므로 1번 확인 후 적용한다.
3. 보안 패치는 자동으로 들어오지 않는다. 발표 이후 등 정해진 시점에 버전을 올리고 같은 테스트로 검증하는 절차를 둔다.

## 7. 배포 상태

### 7-1. 공개 주소 확인 (2026-10-01, 로그인 없이)

[daegulifecycleagent.streamlit.app](https://daegulifecycleagent.streamlit.app) 접속 결과:

| 항목 | 배포 화면 | 로컬 재현 | 일치 |
| --- | --- | --- | --- |
| 앱 상태 | 대기 화면 없이 바로 표시 | — | — |
| 누적 인허가 / 폐업 / 영업 중 | 197,356 / 138,307 / 59,049 | 같음 | ✅ |
| 기준일 · 배치 시각 | 2026-09-23 · 2026-09-29 21:16:54 | 같음 (`meta.json`) | ✅ |
| AI 상담 | "AI 상담 사용 가능 (Google Gemini)", 세션 남은 질문 20회 | 키 없음 → 방문자 키 입력란 | 운영자 키가 Secrets에 설정된 것으로 보임 |

- 배포본의 데이터 스냅샷은 로컬 `data/processed`와 같은 빌드다.
- "남은 질문 20회"는 `MAX_QUESTIONS_PER_SESSION` 기본값 20과 같다. Secrets에서 다른 값을 줬는지는 관리 화면에서 확인한다.
- 운영자 키 할당량을 쓰지 않도록 AI 상담 질문은 보내지 않았다.

### 7-2. 관리 화면 체크리스트 (앱 소유자 계정 필요)

로그인이 필요한 곳이라 소유자(염동권)가 직접 확인한다. **값(키)은 적지 않고 항목 이름과 버전만 기록한다.** 화면 위치는 Streamlit Community Cloud UI 기준이며 메뉴 이름은 바뀌었을 수 있다.

**A. 앱 기본 설정** — share.streamlit.io 로그인 → 내 앱 목록에서 이 앱 → ⋮ 메뉴 → Settings
- [ ] 저장소가 `donggwonY/daegu_lifecycle_agent`인가
- [ ] 배포 브랜치가 `main`인가 (README 근거, 미검증)
- [ ] 메인 파일이 `app.py`인가
- [ ] Python 버전 (README: 3.12) — 설정 화면에 없으면 C의 로그에서 확인

**B. Secrets** — 같은 Settings 화면 → Secrets 탭
- [ ] 들어 있는 **항목 이름**만 기록: `GEMINI_API_KEY`, `LLM_PROVIDER`, `MAX_QUESTIONS_PER_SESSION`, `GLOBAL_QUESTIONS_PER_MINUTE`, `ANTHROPIC_API_KEY` 중 무엇이 있는가
- [ ] `secrets.toml.example`에 없는 항목이 있는가
- [ ] 캡처하면 값을 가린다. 문서·채팅·커밋에 값을 붙여넣지 않는다

**C. 배포 로그** — 앱 페이지를 소유자 계정으로 열고 오른쪽 아래 "Manage app" → 로그 패널 (전체 설치 로그는 Reboot 직후에 보인다)
- [ ] 로그에 표시된 Python 버전
- [ ] 설치된 패키지 버전: pandas, numpy, pyarrow, streamlit, plotly, pydeck, google-genai, anthropic → R6 고정 버전 후보
- [ ] 마지막 배포 시각과 반영된 커밋 (GitHub `main` 최신 커밋 5d3e1cd와 같은가)
- [ ] 오류·경고: 메모리 한도, 패키지 설치 경고, Gemini 429/5xx 기록

**D. 운영 동작**
- [ ] 일정 시간 접속이 없으면 앱이 잠드는가, 깨우는 데 걸리는 시간 (발표 당일 미리 깨우기 필요 여부)
- [ ] `main`에 푸시하면 자동으로 재배포되는가 (README 근거)

### 7-3. 관리 화면 확인 결과 (2026-10-01, 염동권 확인)

| 항목 | 결과 | 비고 |
| --- | --- | --- |
| A. 저장소·브랜치·메인 파일 | `donggwonY/daegu_lifecycle_agent` · `main` · `app.py` | README와 일치 |
| A. Python | 3.12 (로그: Python 3.12.14) | 로컬 3.13과 다름 (R7) |
| B. Secrets 항목 | `LLM_PROVIDER`, `GEMINI_API_KEY` 2개 | `MAX_QUESTIONS_PER_SESSION`·`GLOBAL_QUESTIONS_PER_MINUTE`는 없음 → `config.py` 기본값 20·3 적용. `ANTHROPIC_API_KEY` 없음 |
| C. 설치 방식 | 앱이 시작될 때마다 `uv pip install`로 `requirements.txt`를 새로 해석해 59개 패키지 설치 | R6이 실제로 일어나는 구조임을 확인 |
| C. 플랫폼 개입 | "pyarrow 25.0.1 (known segfault, apache/arrow#50471)"을 감지해 Streamlit Cloud가 **pyarrow 24.0.0으로 교체** | 로컬은 pyarrow 25.0.1 사용 중 (아래 R8) |
| C. 반영 커밋 | 로그에 커밋 해시 없음 | 미확인 |
| C. 오류·경고 | 위 pyarrow 교체 외 오류 없음, 서버 정상 시작 | 확인한 로그는 2026-10-01 01:37 UTC 시작분 |
| D. 슬립 | 접속이 없으면 잠들고 깨우는 데 수 초 | 발표 전 미리 접속해 깨우기 |
| D. 재배포 | `main` 푸시 후 Reboot로 재배포됨 | 푸시만으로 자동 재배포되는지는 미확인 |
| E. Gemini 할당량 | 미확인 | |

배포 환경과 로컬 환경의 주요 패키지 버전:

| 패키지 | Streamlit Cloud (실제 서비스) | 로컬 | 차이 |
| --- | --- | --- | --- |
| pandas | 3.0.6 | 3.0.5 | 패치 |
| numpy | 2.5.3 | 2.3.2 | 마이너 |
| pyarrow | 24.0.0 (플랫폼 교체) | 25.0.1 | 메이저 |
| streamlit | 1.64.0 | 1.63.0 | 마이너 |
| plotly | 7.1.0 | 7.0.0 | 마이너 |
| pydeck | 0.9.3 | 0.9.3 | 같음 |
| google-genai | 2.26.0 | 2.23.0 | 마이너 |
| anthropic | 1.11.0 | 1.5.0 | 마이너 |

**R8 (새 위험):** 로컬은 플랫폼이 "알려진 segfault"로 거르는 pyarrow 25.0.1로 테스트하고 있다. 로컬 테스트 통과가 배포 동작을 보장하지 않는다. 로컬 환경을 배포와 같은 버전(Python 3.12 + 아래 고정 버전)으로 맞추는 것이 R7과 함께 해결책이다.

**R6 고정 버전 후보:** 지금 서비스가 실제로 동작 중인 조합을 그대로 고정한다. 이 조합은 배포 화면에서 정상 동작이 확인됐다(7-1절).

```
pandas==3.0.6
pyarrow==24.0.0
numpy==2.5.3
streamlit==1.64.0
plotly==7.1.0
pydeck==0.9.3
google-genai==2.26.0
anthropic==1.11.0
```

**로컬 검증 (2026-10-01):** Python 3.12.10(python.org, winget 사용자 범위 설치)으로 데모 저장소에 `.venv`를 만들고(Git 제외) 위 8개를 설치해 확인했다.

| 검사 | 결과 |
| --- | --- |
| `tests.test_core_units` | 14개 통과 |
| `tests.smoke_test` | ALL PASSED (`[ERR]` 3건은 잘못된 입력 처리를 보는 의도된 검사) |
| `tests.agent_loop_test`, `tests.gemini_loop_test` | 가짜 클라이언트로 도구 호출 루프 통과. 등록 도구는 **11개** (README의 "Tool 8종" 표기는 옛 수치, R5) |
| `streamlit run app.py` (포트 8502) | 사이드바 기준일·누적 수치, 대시보드 차트 정상 표시, 서버 오류 없음 |

로컬 3.12.10과 배포 3.12.14는 패치 버전만 다르다. 팀 기준 Python은 배포와 같은 **3.12**로 한다 (R7 결정, 2026-10-01).

남은 단계: 데모 저장소 `requirements.txt`를 위 버전으로 바꾸고 `main` 푸시 → Reboot로 배포한다. 배포 변경이므로 소유자(염동권)가 시점을 정한다. 전이 의존성(설치 로그의 나머지 51개)까지 고정할지는 별도 판단한다.

**E. Gemini 할당량 (선택)** — [AI Studio Rate limits](https://aistudio.google.com/rate-limit)
- [ ] 운영자 키 프로젝트의 무료 등급 분당·일일 한도가 `GLOBAL_QUESTIONS_PER_MINUTE` 3회(질문 1개 ≈ 모델 호출 2~4회)를 감당하는가

## 8. 남은 확인 항목

- [x] `streamlit run app.py` 로컬 실행과 대시보드·자리 이력 화면 확인 (2026-10-01)
- [ ] README의 "서빙 메모리 134MB"와 측정값(DataFrame 약 165MB) 차이 확인. 7종 확장 이후 늘어났을 가능성 있음. Streamlit Cloud 무료 메모리 한도와 비교 필요
- [x] 배포 주소 접속: 7-1절 (2026-10-01)
- [x] 관리 화면 체크리스트 A~D: 7-3절 (2026-10-01). E(Gemini 할당량)와 반영 커밋은 미확인
- [x] R6 로컬 검증: Python 3.12 + 고정 버전으로 테스트·앱 실행 통과 (2026-10-01)
- [x] R6 적용: [daegu_lifecycle_agent PR #10](https://github.com/donggwonY/daegu_lifecycle_agent/pull/10) 병합(2026-10-01 03:15 UTC, `main` f553901) → 03:17 UTC Reboot. 배포 로그에서 고정 8개가 모두 지정 버전으로 설치되고 "Detected pyarrow 25.0.1 … Replacing" 메시지가 사라진 것을 확인. 나머지 의존 패키지 51개는 아직 고정하지 않음
- [x] 의존성·비밀값 목록: 6절 (2026-10-01)
- [x] 코드 이전 여부: B(허브로 이전)로 결정, `service/`로 이전 (2026-10-11, 9절)
- [ ] 배포 전환: Streamlit Cloud 앱을 이 저장소 `deploy` 브랜치·`service/app.py`로 새로 만들고 화면·로그 확인 (소유자 작업, 9-1절)

## 9. 코드 이전 여부 (2026-10-11 결정: 허브로 이전)

2026-10-01 확인한 사실:

| 사실 | 내용 |
| --- | --- |
| 데모 저장소 협업자 | donggwonY 1명. 다른 멘티는 데모 코드를 수정·푸시할 수 없음 |
| 허브 저장소 작업 방식 | 멘티 PAT는 허브 저장소 전용, 각자 `main`에 직접 푸시 (PR 없음) |
| 데모 배포 | `main` 푸시 후 Reboot로 공개 앱 갱신 |
| 저장소 | 둘 다 공개, `main` 보호 규칙 없음. 데모는 데이터 이력 포함 약 64MB |

핵심 긴장: 데모를 그대로 두면 팀원이 서비스 코드에 접근할 수 없고, 허브로 옮기면 멘티 3명이 직접 푸시하는 `main`이 공개 서비스 배포 브랜치가 된다.

| | A. 분리 유지 | B. 허브로 전부 이전 | C. 역할 분리 (하이브리드) |
| --- | --- | --- | --- |
| 방식 | 허브=문서, 데모=코드·배포 | 앱·배치·데이터를 허브로 옮기고 재배포 | 허브=분석 코드·실험·문서, 데모=서비스. 검증된 결과만 염동권이 데모에 PR로 반영 |
| 팀원 참여 | 코드 접근 불가 | 같은 곳에서 작업 | 분석은 허브, 서비스 반영은 염동권 경유 |
| 배포 안정성 | 높음 | 직접 푸시 = 배포. 배포 전용 브랜치 필요 | 높음 |
| 이전 비용 | 없음 | 큼: Streamlit 앱 재생성, Secrets 재입력, 주소 변경 가능성, 데이터 이동 | 작음 |
| 단점 | E-03 결과 연결 경로 없음 | 운영 위험, 역할 경계 흐려짐 | 염동권이 반영 병목이 될 수 있음 |

2026-10-01에는 결정을 보류했다(당시 에이전트 의견은 C). **2026-10-11에 B(허브로 이전)로 결정했다**(염동권 전달). B의 약점인 "직접 푸시 = 배포"는 배포 전용 `deploy` 브랜치로 막는다. 결정 내용은 [구현 설계](IMPLEMENTATION_DESIGN.md)와 [작업 흐름](TEAM_WORKFLOW.md)에 반영했다.

### 9-1. 이전 실행 기록 (2026-10-11)

| 항목 | 내용 |
| --- | --- |
| 가져온 것 | 데모 `main` 1932844의 전체 파일을 `service/`에 배치. 과거 커밋 이력은 가져오지 않음(원래 저장소에 남음) |
| 내용 일치 | 가져온 직후 `service/`의 Git 트리 해시가 데모 `main`의 트리 해시와 같음(`e1d3bf4`) |
| 이전 후 고친 것 | `service/README.md`(위치 안내, 배포 저장소·브랜치, MCP 예시 경로), `service/run_batch.ps1`(주석의 경로), `service/.claude/launch.json` 삭제(하위 폴더에서는 동작하지 않음) |
| 분석 스크립트 | D-01·D-02 스크립트 5개의 데이터 경로를 옆 폴더 체크아웃에서 `service/`로 변경. 오프라인 스크립트 9개를 다시 실행해 산출물 비교: 분석 수치와 입력 13개 해시는 동일, 달라진 것은 실행 커밋·Python·pandas 버전 기록뿐이라 기존 산출물을 유지 |
| 테스트 | `service/`에 새로 만든 Python 3.12.10 `.venv`에서 단위 14개·smoke ALL PASSED·MCP 응답·앱 서버 기동 확인. 루트 `tests/`는 20개 중 18개 통과(실패 2개는 이전부터 있던 Windows 파일 권한 검사) |
| 비밀값 검사 | `service/` 파일 44개 검사, 해당 없음 |

배포 전환(미완료): 공개 앱은 아직 원래 저장소 `main`에서 서비스 중이다. 소유자가 Streamlit Cloud에서 새 앱을 만든다 — 저장소 `donggwonY/PublicData_AI_Agent`, 브랜치 `deploy`, 메인 파일 `service/app.py`, Python 3.12, Secrets `LLM_PROVIDER`·`GEMINI_API_KEY`. 확인할 것: ① 로그의 고정 버전 8개 ② 사이드바 기준일 2026-09-23과 누적 197,356 ③ 주황 테마 적용 여부(`.streamlit/config.toml`이 `service/` 안에 있어 하위 폴더 배포에서 읽히는지 미검증) ④ `service/requirements.txt`를 찾는지(미검증). 새 앱 확인 후 기존 앱 처리와 원래 저장소 안내문 추가를 정한다.

미정: `service/.devcontainer`는 저장소 루트에 있어야 동작하므로 지금은 쓰이지 않는다. D-01 보고서 스크립트가 출처로 원래 저장소 주소와 커밋을 적는 부분은 김세은 확인이 필요하다.

## 10. 로컬 재현 절차 (팀원용)

데모 앱을 내 PC에서 띄우고 테스트를 돌리는 순서다. 2026-10-02에 **새 폴더에 처음부터 클론해** Windows 11에서 그대로 실행해 확인했다(`main` 1932844). macOS·Linux 명령은 시험하지 못해 "미검증"으로 표시했다.

**2026-10-11 이전 이후**: 코드가 이 저장소의 `service/`로 옮겨졌다. 이미 이 저장소를 클론했다면 10-2의 `git clone`과 `cd daegu_lifecycle_agent` 대신 **`cd service`** 한 뒤 `py -3.12 -m venv .venv`부터 그대로 따라 한다. 아래 경로의 `data\...`, `.streamlit\...`도 `service\` 안 기준이다. 이 방식으로 2026-10-11에 가상환경 생성·설치·단위/smoke 테스트·앱 기동을 확인했다. 아래 본문은 원래 저장소 기준으로 검증한 기록이라 그대로 둔다.

데모 저장소는 공개 저장소라 권한 없이 클론할 수 있다. 가공된 데이터(`data/processed`)가 저장소에 들어 있어서 **원본 CSV 없이도 앱과 테스트가 돈다.** 원본 CSV가 필요한 것은 배치 재계산(10-5)뿐이다.

### 10-1. 준비물

| 준비물 | 확인 방법 | 없으면 |
| --- | --- | --- |
| Git | `git --version` | [git-scm.com](https://git-scm.com/)에서 설치 |
| Python **3.12** | `py -3.12 --version` → `Python 3.12.x` | `winget install Python.Python.3.12` 또는 [python.org](https://www.python.org/downloads/)에서 3.12 설치. 다른 버전(3.13 등)이 이미 있어도 함께 설치된다 |
| 디스크 여유 | 1GB 이상 권장 | 클론 약 65MB + 가상환경 약 490MB (측정값) |

배포 환경이 Python 3.12라서 3.12로 맞춘다(R7). 3.13 등 다른 버전으로도 실행은 될 수 있지만 결과가 배포와 같다고 보장할 수 없다.

### 10-2. 클론과 가상환경 (최초 1회)

PowerShell에서 실행한다. **경로가 짧은 폴더**에서 한다(예: `C:\work`). 경로가 길면 설치 중 `[WinError 206] 파일 이름이나 확장명이 너무 깁니다` 오류가 난다(확인).

```powershell
cd C:\work                      # 원하는 짧은 경로
git clone https://github.com/donggwonY/daegu_lifecycle_agent.git
cd daegu_lifecycle_agent
py -3.12 -m venv .venv          # 가상환경 생성 (약 10초)
.venv\Scripts\Activate.ps1      # 가상환경 켜기. 프롬프트 앞에 (.venv) 가 붙는다
pip install -r requirements-dev.txt   # 약 2~3분
python --version                # Python 3.12.x 인지 확인
```

- `Activate.ps1`이 "스크립트를 실행할 수 없습니다"로 막히면(미검증: 이 PC에서는 막히지 않았다) 켜지 않고 `.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`처럼 가상환경의 Python을 직접 부른다. 아래 명령도 `python` 자리에 `.venv\Scripts\python.exe`를 쓰면 된다(확인).
- macOS·Linux(미검증): `python3.12 -m venv .venv` → `source .venv/bin/activate` → 이후 명령은 같다.
- 웹 화면만 볼 거면 `requirements.txt`만 설치해도 된다. `requirements-dev.txt`는 배치(pyproj)와 MCP 서버(mcp)를 더한다.

### 10-3. 테스트로 설치 확인

터미널을 새로 열었으면 먼저 `.venv\Scripts\Activate.ps1`로 가상환경을 켠다.

```powershell
python -m unittest tests.test_core_units   # 기대: "Ran 14 tests ... OK"
python -m tests.smoke_test                  # 기대: 마지막 줄 "ALL PASSED 0"
```

`smoke_test` 출력의 `[ERR]` 3줄(삼덕동, 없는구, 없는주소)은 잘못된 입력에 오류를 제대로 돌려주는지 보는 검사라 정상이다. API 키는 필요 없다.

### 10-4. 앱 실행

```powershell
streamlit run app.py
```

브라우저에서 `http://localhost:8501`이 열린다. 끝낼 때는 터미널에서 `Ctrl+C`.

아래 값이 보이면 배포본과 같은 데이터로 뜬 것이다(2026-10-02 기준. 데이터를 갱신하면 달라진다).

| 위치 | 기대값 |
| --- | --- |
| 사이드바 누적 인허가 / 폐업 / 영업 중 | 197,356 / 138,307 / 59,049 |
| 사이드바 아래 | 기준일 2026-09-23 · 배치 2026-09-29 21:16:54 |
| 대시보드 탭, 지역 "대구 전체" | 상권 사이클 "쇠퇴 진입기", 중앙생존기간 5.2년 |
| 자리 이력 조회 탭에 `대구 중구 동성로5길 83` 입력 | "대구광역시 중구 동성로5길 83 1층", 인허가 레코드 6 |

**AI 상담 탭**은 Gemini API 키가 있어야 답한다. 대시보드와 자리 이력 조회는 키 없이 동작한다.

- 키는 [Google AI Studio](https://aistudio.google.com/apikey)에서 본인 계정으로 발급받아 사이드바 입력란에 넣는다. 이 방식은 키가 그 브라우저 세션에만 남는다.
- 매번 입력하기 번거로우면 `.streamlit\secrets.toml.example`을 `.streamlit\secrets.toml`로 복사해 값을 채운다. 이 파일은 Git에서 제외돼 있다.
- 키를 코드, 커밋, 채팅, 이 저장소 문서에 붙여넣지 않는다. 배포 앱의 운영자 키는 공유하지 않는다.

### 10-5. 배치 재계산 (선택, 원본 CSV 필요)

분석이나 화면 확인만 할 때는 필요 없다. 원본 CSV는 용량과 재배포 조건 때문에 Git에 없으므로, 필요하면 염동권에게 파일을 받아 아래 위치에 둔다. 원본 CSV는 커밋하지 않는다(`.gitignore`로 제외됨).

| 폴더 | 파일 |
| --- | --- |
| `data\raw\` (인허가 7종) | `식품_일반음식점_대구광역시.csv`, `식품_휴게음식점_대구광역시.csv`, `식품_제과점영업_대구광역시.csv`, `생활_미용업_대구광역시.csv`, `생활_세탁업_대구광역시.csv`, `문화_노래연습장업_대구광역시.csv`, `기타_담배소매업_대구광역시.csv` |
| `data\external\` (보조 7종) | 상가(상권)정보 대구 2026-06, 주민등록 인구(행정동) 2026-08-31, 대구교통공사 역별 일별 시간별 승하차·월별 승차·월별 하차 2026-07-31, 전국주차장정보표준데이터, 전통시장 |

```powershell
python -m pipeline.build       # 인허가 배치, 약 20초 → data\processed
python -m pipeline.external    # 보조 데이터 배치, 약 5초
```

- 원본 CSV가 없으면 `data\raw 에 인허가 CSV 가 없습니다.`로 끝나고 기존 `data\processed`는 그대로 남는다(확인).
- 배치는 `data\processed`를 **바로 덮어쓴다.** 저장 도중 실패하면 파일이 섞일 수 있다(R1). 실행 후 `git status`로 무엇이 바뀌었는지 보고, 의도하지 않았으면 `git checkout -- data/processed`로 되돌린다.
- 데이터 내용이 같아도 parquet 파일은 Git에 "변경됨"으로 잡힐 수 있다(pyarrow 버전에 따라 파일 바이트가 달라짐).
- `data\processed`를 커밋해 `main`에 올리면 배포 데이터가 바뀐다. 배포 변경은 염동권과 확인한다.

### 10-6. 자주 막히는 곳

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| `[WinError 206] 파일 이름이나 확장명이 너무 깁니다` | 폴더 경로가 김 | `C:\work`처럼 짧은 경로에 다시 클론 (확인) |
| `py -3.12`가 "not found" | Python 3.12 미설치 | 10-1대로 설치 후 새 터미널 |
| `python --version`이 3.12가 아님 | 가상환경이 꺼져 있음 | `.venv\Scripts\Activate.ps1` 다시 실행 |
| 한글이 깨져 보이거나 `UnicodeEncodeError` | 터미널 인코딩 | `$env:PYTHONIOENCODING = "utf-8"` 실행 후 다시 (이 PC에서는 설정 없이도 통과) |
| `data/processed 에 배치 산출물이 없습니다` | `data\processed`가 지워졌거나 비어 있음 | `git checkout -- data/processed` |
| `ModuleNotFoundError: No module named 'tests'` 또는 `'core'` | 저장소 폴더 밖에서 실행 (미검증) | `daegu_lifecycle_agent` 폴더로 이동해 실행 |
| 포트 8501이 이미 사용 중 | 다른 Streamlit이 떠 있음 | `streamlit run app.py --server.port 8502` |

### 10-7. 검증 기록

2026-10-02, Windows 11, 새 폴더 클론(`main` 1932844), Python 3.12.10:

| 단계 | 결과 |
| --- | --- |
| `git clone` | 7초 |
| `py -3.12 -m venv .venv` | 9초 |
| `Activate.ps1` 후 `pip install -r requirements-dev.txt` | 종료 코드 0, 139초 |
| `python -m unittest tests.test_core_units` | OK (14개) |
| `python -m tests.smoke_test` | ALL PASSED (`PYTHONIOENCODING` 설정 유무 모두) |
| `streamlit run app.py` | 서버 상태 확인 응답 `ok`. 화면 값은 같은 버전 조합의 `.venv`로 2026-10-01에 확인(7-3절) |
| `python -m pipeline.build` (원본 CSV 없음) | 안내 메시지와 함께 종료, `data\processed` 변경 없음 |

확인하지 못한 것: PowerShell 실행 정책이 기본값(Restricted)인 PC에서의 `Activate.ps1`, macOS·Linux, 팀원이 받은 원본 CSV로 돌린 배치.
