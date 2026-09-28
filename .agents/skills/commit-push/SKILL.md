---
name: commit-push
description: 멘티가 작업을 원격 main에 반영해 달라고 할 때 변경 검사, 커밋, 최신 main 동기화, 충돌 해결, 검증과 푸시를 대신 수행한다.
---

학생에게 Git 명령을 실행하라고 하지 않습니다. 이 스킬 호출은 검증된 변경을 `main`에 커밋·푸시하라는 요청입니다. 먼저 `.mentee/profile.json`, `git status`, 변경 내용을 확인하고 작업에 맞는 검증을 수행합니다. 커밋 메시지는 변경 내용으로 작성합니다. PAT가 없으면 학생에게 묻고 `mentee-init` 설정 방식으로 로컬 `.env`에 저장합니다. 토큰 값을 다시 출력하지 않습니다. 현재 브랜치가 `main`이 아니면 작업과 고유 커밋을 먼저 확인하고 잃지 않도록 `main`에 통합합니다. 학생에게 브랜치 전환을 맡기지 않습니다.

저장소 루트에서 `python3 scripts/commit_push.py prepare --message "변경 요약"`, 이어서 `python3 scripts/commit_push.py sync`를 에이전트가 실행합니다. 원격 변경이 로컬보다 앞서면 fast-forward하고, 양쪽에 커밋이 있으면 로컬 커밋을 최신 `origin/main` 위에 rebase합니다. 충돌이 나면 양쪽 변경과 맥락을 읽어 직접 통합하고, 충돌 파일만 `git add`한 뒤 `GIT_EDITOR=true git rebase --continue`를 반복합니다. 한쪽을 일괄 선택하거나 원격 변경을 버리지 않습니다. 의미를 판단할 수 없는 충돌만 구체적인 선택지를 학생에게 묻습니다.

동기화 또는 충돌 해결 후 관련 검증을 다시 수행하고 `python3 scripts/commit_push.py push`를 실행합니다. 그 사이 원격이 갱신되어 푸시가 거부되면 동기화·검증·푸시를 최대 세 번 다시 시도합니다. 그래도 실패하거나 권한·브랜치 규칙이 막으면 현 상태를 보존하고 원인을 설명합니다. `--force`, `reset --hard`, 훅 우회, PR 생성은 사용하지 않습니다. 끝나면 반영된 커밋과 검증 결과만 간단히 알려줍니다.
