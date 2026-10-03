---
name: session-resume
description: 세션을 시작하거나 이전 작업을 이어받을 때 사용한다. 상태 파일과 최근 커밋만 읽고 다음 행동을 확인한다. "이어서", "재개", "resume", "어디까지 했지"에도 사용한다.
metadata:
  version: "v26092601"
  updated: "2026-09-26 19:01 KST"
---
# 세션 재개

1. `.agents/state/STATE.json`을 읽는다. 없으면 harness-start 스킬로 간다.
2. `git status --short`와 `git log --oneline -5`로 상태 파일 이후의 변경을 확인한다. 상태 파일의 `updated_at`보다 새 커밋이나 미커밋 변경이 있으면 그 차이를 먼저 보고한다.
3. `current.next_action`과 `current.blockers`를 확인한다. 막힌 점이 사용자 입력이면 그 질문만 한다.
4. `SESSION_LOG.md`는 마지막 작업 블록과 `## 오류` 절만 읽는다. 전체 대화나 과거 기록을 다시 읽지 않는다.
5. 사용자에게 3줄로 알린다: 현재 작업과 상태 / 다음 행동 / 확인한 차이. 그다음 승인 범위 안에서 바로 이어서 진행한다.
