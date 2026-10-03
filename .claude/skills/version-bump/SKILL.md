---
name: version-bump
description: 지침(AGENTS.md, CLAUDE.md), 스킬(SKILL.md), 훅, 역할 정의, 확정 문서를 고칠 때 사용한다. 버전 번호와 갱신 시각을 규칙대로 올리고 MANIFEST·lock을 맞춘다. 종료 검사 훅이 "버전이 그대로"라고 알릴 때도 사용한다.
metadata:
  version: "v26092611"
  updated: "2026-09-27 02:49 KST"
---
# 버전 갱신

## 번호 규칙
- 형식 `vYYMMDDNN`: YYMMDD는 수정한 날, NN은 그날 같은 파일의 순번(01부터).
- 같은 작성 과정의 검증 단계에서 찾은 수정은 같은 번호에 넣는다. 사용자에게 전달한 뒤의 수정부터 새 번호를 쓴다.
- 갱신 시각은 `date '+%Y-%m-%d %H:%M %Z'`로 잰 값을 쓴다.

## 파일 종류별 위치
- 확정 문서(보고서·가이드): 파일명 `이름-vYYMMDDNN.md`. 새 파일을 만들고 이전 판을 가리키던 링크를 새 파일로 바꾼다. Git을 쓰면 이전 판 파일을 지우고 커밋 메시지와 CHANGELOG 또는 FILE_INDEX에 이전 판 이름과 복구할 커밋을 한 줄 남긴다(Git으로 복구 가능하므로 묻지 않는다). Git을 쓰지 않으면 이전 판을 `archive/`로 옮긴다.
- 이름이 고정된 Markdown·스크립트·TOML: 첫 15줄 안의 `harness-kit: <경로> vYYMMDDNN | updated YYYY-MM-DD HH:mm KST` 줄을 고친다.
- SKILL.md: frontmatter의 `metadata.version`, `metadata.updated`를 고친다.
- JSON 설정: 파일 안에 적지 않는다. HarnessKit 원본이면 `tools/build_manifest.py`가 MANIFEST.json에 기록한다.
- 계획·상태·세션 기록·README: 파일명 버전을 늘리지 않는다.

## 절차
1. 머리말의 번호와 시각을 올린다.
2. HarnessKit 원본을 고쳤으면 `python3 tools/build_manifest.py`를 실행하고, VERSION과 CHANGELOG.md에 한 줄을 추가한다.
3. 설치된 프로젝트에서 고쳤으면 `python3 "$HARNESS_KIT_HOME/tools/verify.py" --project . --relock`(키트 위치는 harness-start 2절 1번 순서로 찾는다)으로 lock을 새 해시로 맞춘다.
4. Git을 쓰면 `docs(harness): <파일> vYYMMDDNN` 형식으로 커밋한다.
