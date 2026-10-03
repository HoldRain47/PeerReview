#!/usr/bin/env bash
# harness-kit: hooks/session-start.sh v26092610 | updated 2026-09-27 02:17 KST
# =====================================================================
# 세션 시작 훅(Claude Code SessionStart). 상태 파일의 요약을 맥락으로 넣는다.
# Codex CLI·Gemini CLI의 세션 시작 이벤트 출력 형식은 확인하지 못해 기본 등록하지 않는다.
# 두 도구에서는 AGENTS.md의 "세션 시작" 절과 session-resume 스킬이 같은 일을 한다.
# 출력: stdout에 {"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"..."}}
# 필요 환경: bash, jq(없으면 "{}"만 출력). 부작용 없음.
# =====================================================================
set -uo pipefail
cat >/dev/null
# 프로젝트 루트 찾기(독립 검수 N3): ① 이 스크립트가 <루트>/.agents/hooks/ 에 있으면 그 <루트>
# ② 현재 폴더에서 위로 올라가며 .agents/harness-lock.json 이 있는 폴더 ③ git 최상위 ④ 현재 폴더
find_root() {
  local here d
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
  case "$here" in */.agents/hooks) printf '%s' "${here%/.agents/hooks}"; return ;; esac
  d="$(pwd)"
  while :; do
    [ -f "$d/.agents/harness-lock.json" ] && { printf '%s' "$d"; return; }
    [ "$d" = "/" ] && break
    d="$(dirname "$d")"
  done
  git rev-parse --show-toplevel 2>/dev/null || pwd
}
ROOT="$(find_root)"
cd "$ROOT" || { echo '{}'; exit 0; }
command -v jq >/dev/null 2>&1 || { echo '{}'; exit 0; }

STATE=.agents/state/STATE.json
if [ ! -f "$STATE" ]; then
  MSG="[harness] 상태 파일이 없습니다. 새 프로젝트·여러 단계 작업이면 시작 질문(하네스 수준, Git 사용, 언어·기술 스택)을 먼저 하세요."
elif ! jq -e . "$STATE" >/dev/null 2>&1; then
  MSG="[harness] $STATE 가 올바른 JSON이 아닙니다. 먼저 복구하세요."
else
  MSG="$(jq -r '
    "[harness] kit " + (.kit_version // "?") + " / 상태 갱신 " + (.updated_at // "?") + "\n" +
    "목표: " + (.project.goal // "(미정)") + "\n" +
    (if (.project.decisions.harness_level // "") == "" or (.project.decisions.git == null)
       then "시작 질문 미완료: 하네스 수준·Git 사용·기술 스택을 먼저 물으세요.\n" else "" end) +
    "현재 작업: " + ((.current.task_id // "-") + " " + (.current.title // "") + " [" + (.current.status // "-") + "]") + "\n" +
    "다음 행동: " + (.current.next_action // "(없음)") + "\n" +
    (if ((.current.blockers // []) | length) > 0 then "막힌 점: " + ((.current.blockers) | join("; ")) + "\n" else "" end) +
    "상세는 .agents/state/SESSION_LOG.md 와 git log 로 확인하세요."
  ' "$STATE" 2>/dev/null)"
fi
jq -n --arg m "$MSG" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$m}}'
exit 0
