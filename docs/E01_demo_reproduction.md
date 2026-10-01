# E-01 데모 실행·구조·배포 흐름 재현

담당: 염동권 · 상태: 진행 중 · 대상: [daegu_lifecycle_agent](https://github.com/donggwonY/daegu_lifecycle_agent) `origin/main` (5d3e1cd, 로컬 `feat/service-expansion-ready` 8d86945와 내용 동일)

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
| 배치 재계산 | `python -m pipeline.build`, `python -m pipeline.external` | 미검증 (원본 CSV는 로컬에 있음) |

Windows에서는 `PYTHONIOENCODING=utf-8` 설정이 필요할 수 있다 (`run_batch.ps1`도 설정함).

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
- [ ] 코드 이전 여부: 9절 선택지 정리 완료, 결정은 보류 (2026-10-01)

## 9. 코드 이전 여부 (결정 보류)

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

에이전트 의견은 C(비용이 작고 B로 바꾸는 길도 남음)이나, **염동권 판단으로 결정을 보류**했다. 결정 시 함께 정할 것: 데모 저장소에 다른 멘티 협업자 권한을 줄지 여부. 결정은 관리자 확인 후 [구현 설계](IMPLEMENTATION_DESIGN.md)의 "결정 보류"에 반영한다.
