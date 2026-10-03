---
name: harness-start
description: 새 프로젝트를 시작하거나 여러 단계 작업을 처음 받을 때 사용한다. 하네스 적용 수준·Git 사용·언어와 기술 스택을 묻고, 답에 따라 HarnessKit을 프로젝트에 설치하고 AGENTS.md와 상태 파일을 채운다. "하네스 적용", "프로젝트 시작", "harness init"에도 사용한다.
metadata:
  version: "v26092611"
  updated: "2026-09-27 02:49 KST"
---
# 하네스 시작

## 1. 묻기 (한 번에)
`.agents/state/STATE.json`의 `project.decisions`가 채워져 있으면 묻지 않고 3절로 간다. 비어 있으면 다음을 한 번에 묻는다. 기본안을 표시한다.

1. 하네스 수준
   - 없음: 단순·일회성 작업. 파일을 만들지 않고 바로 작업한다.
   - 경량(기본): AGENTS.md(+CLAUDE.md), 상태 파일, 기본 스킬, 위험 명령 차단 훅. Git을 쓰면 Git 훅(`--git-hooks`)도 설치한다.
   - 전체: 경량 + 외부 스킬, 검증 역할(verifier), 종료 검사·세션 시작 훅.
2. Git 버전 관리: 사용(기본) / 사용 안 함. 사용하면 `git rev-parse --show-toplevel`로 기존 저장소 경계를 확인한다. 상위 저장소가 있으면 중첩 저장소를 만들지 않는다. 상위 저장소의 하위 폴더에 설치하면 훅은 `.agents/hooks` 위치로 프로젝트 루트를 찾지만, git 명령·Git 훅·커밋은 상위 저장소에 적용된다는 점을 사용자에게 알린다(설치 도구도 경고한다).
3. 새 프로젝트면 개발 언어와 기술 스택(런타임, 프레임워크, 패키지 관리자, 시험 도구). 모르면 요구에 맞는 추천안 1개와 대안 1개를 이유와 함께 낸다.
4. 사용할 에이전트 도구: Claude Code / Codex CLI / Gemini CLI (여러 개 가능). 현재 실행 중인 도구를 기본값으로 한다.

답을 받기 전에는 읽기 전용 확인만 한다.

## 2. 설치
1. HarnessKit 위치를 찾는다: 환경 변수 `HARNESS_KIT_HOME` → `.agents/harness-lock.json`의 `kit_home_hint`(`~`는 홈 폴더) → `~/.agents/harness-kit` → 사용자에게 묻기. 찾은 위치를 이후 명령의 `$HARNESS_KIT_HOME` 자리에 쓴다.
2. Git을 쓰기로 했는데 저장소가 없으면 먼저 `git init`을 실행한다(설치가 `core.hooksPath`를 설정하려면 저장소가 있어야 한다). 작성자 정보가 없으면 사용자에게 묻는다.
3. 미리보기: `python3 "$HARNESS_KIT_HOME/tools/install.py" --target . --tools <도구들> --level <light|full> --dry-run`
4. 기존 파일은 덮어쓰지 않는다. 미리보기에서 `SKIP(exists)`로 나온 파일은 차이를 사용자에게 보여 주고 병합 여부를 묻는다. 이미 설치된 프로젝트를 새 키트로 올릴 때는 `--upgrade`를 붙인다(손대지 않은 파일만 바뀐다).
5. 승인 후 `--dry-run` 없이 실행한다. Git을 쓰면 `--git-hooks`를 붙인다(저장소 로컬 `core.hooksPath` 설정).

## 3. 채우기
1. AGENTS.md의 `{{...}}`를 조사 결과와 사용자 답으로 채운다. 모르는 값은 지어내지 말고 `확인 필요:`로 남긴 뒤 묻는다. 종료 검사 훅이 남은 자리표시자를 잡는다. 자리표시자만 채우고, 규칙이나 절을 새로 넣으려면 먼저 사용자에게 묻는다.
2. STATE.json의 `project.goal`, `project.decisions`(harness_level, git, language, stack, asked_at), `current`(첫 작업의 done_when, next_action), `updated_at`을 채운다.
3. 시험 명령이 있으면 `.agents/hooks/stop-check.conf`의 CHECK_COMMAND에 넣는다.
4. 확인: `python3 "$HARNESS_KIT_HOME/tools/verify.py" --project .`

## 4. 보고
설치한 파일 목록, 건너뛴 파일과 이유, 사용자가 해야 할 일(Codex `/hooks`에서 신뢰 승인, Gemini 훅 신뢰, Claude 세션 재시작)을 나눠 쓴다. Git을 쓰면 `chore(harness): HarnessKit <설치한 키트 버전> 적용`(버전은 `.agents/harness-lock.json`의 kit_version)으로 커밋한다.
