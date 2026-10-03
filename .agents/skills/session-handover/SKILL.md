---
name: session-handover
description: 작업 하나를 마쳤을 때, 세션을 끝낼 때, 맥락이 70% 이상 찼을 때 사용한다. STATE.json과 SESSION_LOG.md를 갱신해 다음 세션이나 반복 실행이 파일만 읽고 재개할 수 있게 한다. "마무리", "인계", "handover", "checkpoint"에도 사용한다.
metadata:
  version: "v26092601"
  updated: "2026-09-26 19:01 KST"
---
# 세션 인계

1. STATE.json 갱신(시각은 `date '+%Y-%m-%d %H:%M %Z'`로 잰 값만 쓴다):
   - `tasks[]`에서 해당 작업의 `status`(todo|running|done|partial|failed|blocked), `evidence`(실행한 검사와 결과), `commits`(해시)
   - `current`: 다음 작업의 `task_id`, `title`, `status`, `done_when`, `next_action`, `blockers`
   - `updated_at`
2. SESSION_LOG.md 맨 아래에 3줄 블록을 추가한다(결과 / 증거 / 남은 것). 오류가 있었으면 `## 오류` 절에 원인·결과·재발 방지를 추가한다. 같은 실수가 두 번째면 재발 방지를 훅·시험으로 옮기자고 제안한다.
3. 검증 상태를 섞지 않는다. 미실행은 미실행으로 쓴다.
4. Git을 쓰면 상태 파일과 작업 결과를 함께 커밋한다(git-commit 스킬).
5. `jq . .agents/state/STATE.json`으로 형식을 확인한다. 종료 검사 훅도 같은 항목을 검사한다.
