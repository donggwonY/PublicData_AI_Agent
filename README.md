# PublicData AI Agent — 멘티 협업 허브

이 저장소는 대구 상권 생애주기 AI 에이전트를 발표 가능한 프로젝트로 발전시키기 위한 **공통 설계·개발 지침과 서비스 코드**를 담습니다. 웹앱·배치·가공 데이터는 [`service/`](service/)에 있습니다. 2026-10-11에 [daegu_lifecycle_agent](https://github.com/donggwonY/daegu_lifecycle_agent) `main`(1932844)의 내용을 그대로 옮겨 왔고, 그 이전 커밋 이력은 원래 저장소에 남아 있습니다.

| 위치 | 내용 |
| --- | --- |
| `service/` | Streamlit 앱(`app.py`), 분석 함수(`core/`), 배치(`pipeline/`), 가공 데이터(`data/processed/`), 앱 테스트(`tests/`). 실행 방법은 [service/README.md](service/README.md) |
| `scripts/`, `tests/` | 멘티용 Git 도구와 분석·검증 스크립트, 그 테스트 |
| `docs/` | 설계, 작업 흐름, 작업판, 작업별 산출물 |

`main`은 작업 브랜치이고 공개 앱은 `deploy` 브랜치에서 배포합니다. `main`에 푸시해도 공개 앱은 바뀌지 않습니다. 절차는 [팀 역할과 작업 흐름](docs/TEAM_WORKFLOW.md)에 있습니다.

- [구현 설계와 결정 사항](docs/IMPLEMENTATION_DESIGN.md)
- [팀 역할과 작업 흐름](docs/TEAM_WORKFLOW.md)
- [멘티 플레이북](docs/MENTEE_PLAYBOOK.md) · [멘티 작업판](docs/WORKBOARD.md)
- [공통 코딩 에이전트 지침](AGENTS.md) · [Claude Code 진입점](CLAUDE.md)

## 멘티 시작하기

1. 이 저장소를 클론하고 저장소 폴더에서 Codex 또는 Claude Code를 시작합니다.
2. Codex에서는 `$mentee-init`, Claude Code에서는 `/mentee-init`을 실행합니다. 두 이름은 각 도구가 지원하는 프로젝트 스킬 형식에 맞춘 것입니다. 기존 `/init` 명령과 충돌하지 않습니다.
3. 에이전트가 띄우는 **ask 창에서 이름을 선택**합니다. 이어서 뜨는 **ask 입력란에 GitHub 커밋 이메일을 입력**합니다. 일반 대화창에 답을 복사할 필요는 없습니다. 토큰 등록 여부도 ask 창에서 선택할 수 있습니다. **터미널 명령을 직접 실행할 필요는 없습니다.** 토큰을 ask 입력란에 넣어도 대화 기록에 남을 수 있지만, 에이전트는 값을 다시 출력하지 않고 로컬 `.env`에 저장합니다. 토큰이 아직 없어도 설정할 수 있습니다.
4. 이후 개발을 시작할 때마다 Codex에서 `$pull`, Claude Code에서 `/pull`을 먼저 실행합니다. 에이전트가 원격 `main`의 새 커밋을 안전하게 반영합니다. 로컬 변경이나 분기된 커밋이 있으면 덮어쓰지 않고 상황을 설명합니다.
5. 작업을 원격 저장소에 반영하려면 Codex에서 `$commit-push`, Claude Code에서 `/commit-push`를 실행합니다. 에이전트가 변경 확인·커밋·최신 `main` 반영·충돌 해결·검증·푸시를 맡습니다. 학생이 Git 명령이나 PR을 직접 다룰 필요는 없습니다.

초기 설정이 끝나면 에이전트가 멘티별 첫 작업과 대안을 제안합니다. 이후에도 "다음에 뭘 할까요?"라고 물으면 [작업판](docs/WORKBOARD.md)의 진행 상황과 실제 산출물을 보고 다음 단계를 함께 고릅니다. 염동권은 엔지니어링, 김세은·김선경은 데이터 분석과 ML 실험을 각각 충분히 수행하도록 [멘티 플레이북](docs/MENTEE_PLAYBOOK.md)에 질문·완료 기준을 적었습니다.

토큰은 본인 계정에서 만든 **fine-grained PAT**를 사용하고 이 저장소만 선택하며 `Contents: Read and write` 권한을 부여합니다. 소유자가 협업 권한을 주지 않았다면 토큰만으로 푸시할 수 없습니다. 토큰을 Git 원격 URL, 커밋, Streamlit Secrets에 넣지 않습니다. `.env`와 `.mentee/profile.json`은 Git에서 제외하며, 설정 과정에서 활성화되는 pre-push 훅이 커밋 기록의 비밀 파일과 토큰 형태 문자열을 검사합니다. 일반 게시 흐름은 강제 푸시 없이 `main`을 갱신합니다. GitHub의 [PAT 안내](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)를 참고하세요.

## 관리자 메모

공통 결정은 `docs/IMPLEMENTATION_DESIGN.md`, 역할과 첫 작업은 `config/mentees.json`, 멘티별 학습·작업 기준은 `docs/MENTEE_PLAYBOOK.md`, 현재 진행 상태는 `docs/WORKBOARD.md`에서 수정합니다. 코딩 에이전트의 공통 지침은 `AGENTS.md`만 수정하세요. `CLAUDE.md`는 `@AGENTS.md`를 가져오는 진입점입니다.

새 스킬은 `.agents/skills/<skill-name>/SKILL.md` 한 곳에 작성하고 `python3 scripts/link_skills.py`를 실행하세요. 이 명령이 `.codex/skills/<skill-name>`과 `.claude/skills/<skill-name>`에 원본 폴더를 가리키는 상대 심볼릭 링크를 만듭니다. 따라서 Codex와 Claude Code가 같은 `SKILL.md`를 읽습니다. 링크와 원본을 함께 커밋하고, 두 경로에 별도 본문을 작성하지 마세요. Windows에서는 심볼릭 링크를 실제 링크로 체크아웃하도록 개발자 모드와 Git의 `core.symlinks` 설정을 확인해야 합니다.

앱 실행·테스트 명령은 `service/README.md`, 배포 책임과 `deploy` 브랜치 절차는 `docs/TEAM_WORKFLOW.md`, 데이터 스키마는 `docs/d01/`에서 관리합니다.
