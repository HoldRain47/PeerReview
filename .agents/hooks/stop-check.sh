#!/usr/bin/env bash
# harness-kit: hooks/stop-check.sh v26092612 | updated 2026-09-27 03:07 KST
# =====================================================================
# 응답 종료 훅. 에이전트가 턴을 끝내기 전에 하네스 규칙을 검사하고, 문제가 있으면
# 이유를 돌려주어 한 번 더 작업하게 한다.
#   Claude Code: Stop   Codex CLI: Stop   Gemini CLI: AfterAgent
# 재작업 요청: 종료 코드 2 + stderr / 통과: stdout "{}" + 종료 코드 0
# 반복 방지: 입력의 stop_hook_active 가 true 면 검사하지 않고 통과한다.
#   같은 세션에서 같은 내용의 문제는 한 번만 알린다(세션 ID와 내용의 해시를 .git/harness-kit-stop-ack 또는 임시 폴더에 둔다). 매 턴 같은 경고로
#   응답이 한 번 더 생기는 것을 막는다(실사용 확인 2026-09-27). 내용이 바뀌면 다시 알린다.
# 검사 항목:
#   ① .agents/state/STATE.json 형식(필수 키)
#   ② 설치 기록(lock)에 있는 하네스 파일의 버전 머리말 존재(사용자가 만든 지침·Git 훅은 보지 않음)
#   ③ 설치 당시(.agents/harness-lock.json)와 내용이 달라졌는데 버전이 그대로인 하네스 파일
#   ④ 지침 파일(AGENTS.md·CLAUDE.md·GEMINI.md)에 남은 {{자리표시자}}
#   ⑤ .agents/hooks/stop-check.conf 의 CHECK_COMMAND (프로젝트 품질 검사)
#   ⑥ 중복 사본 의심: 미추적 파일 중 원본 옆에 생긴 '이름-1.확장자'·'이름 (1).확장자'·'이름 copy.확장자',
#      그리고 내보내기 폴더(EXPORT_DIRS, 기본 'Claude outputs'). 같은 목록은 한 번만 알린다
#      (알린 목록의 해시를 .git/harness-kit-dup-ack 에 둔다). 파일을 지우지 않는다.
# 필요 환경: bash, jq(없으면 ①을 건너뜀), jq 또는 python3(둘 다 없으면 ③을 건너뜀),
#   git(없으면 ②③④를 설치 기록(.agents/harness-lock.json)의 파일과 루트 지침 파일에만 수행, ⑥은 건너뜀)
# 제외: node_modules·vendor·.venv·venv·dist·build·target·third_party 아래 파일은 검사하지 않는다.
# 부작용: CHECK_COMMAND 의 부작용. 읽기 전용 명령만 넣는다.
# =====================================================================
set -uo pipefail

INPUT="$(cat)"
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
HAS_JQ=0; command -v jq >/dev/null 2>&1 && HAS_JQ=1
HAS_PY=0; command -v python3 >/dev/null 2>&1 && HAS_PY=1
# JSON 읽기: jq가 없으면 python3로 같은 값을 읽는다(독립 검수 N2).
#   jget <파일> <점 경로>  예) jget STATE.json schema / 잠금 파일의 files 항목은 lockget 사용
lockget() {  # lockget <상대경로> <sha256|version>
  if [ "$HAS_JQ" = 1 ]; then jq -r --arg p "$1" --arg k "$2" '.files[$p][$k] // empty' .agents/harness-lock.json 2>/dev/null
  elif [ "$HAS_PY" = 1 ]; then python3 -c 'import json,sys
try: print(json.load(open(".agents/harness-lock.json",encoding="utf-8")).get("files",{}).get(sys.argv[1],{}).get(sys.argv[2],""))
except Exception: pass' "$1" "$2"; fi
}
locklist() {  # 설치 기록에 있는 파일 목록
  if [ "$HAS_JQ" = 1 ]; then jq -r '.files // {} | keys[]' .agents/harness-lock.json 2>/dev/null
  elif [ "$HAS_PY" = 1 ]; then python3 -c 'import json
try: print("\n".join(json.load(open(".agents/harness-lock.json",encoding="utf-8")).get("files",{})))
except Exception: pass'; fi
}
# 한글 등 비ASCII 파일명을 인용 부호 없이 받는다(core.quotePath=off). 그렇지 않으면 이름 비교가 실패한다.
GQ='git -c core.quotePath=off'

# 반복 방지(독립 검수 N2): jq → python3 → 문자열 검사 순서로 stop_hook_active 를 읽는다.
if [ "$HAS_JQ" = 1 ]; then
  ACTIVE="$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)"
elif [ "$HAS_PY" = 1 ]; then
  ACTIVE="$(printf '%s' "$INPUT" | python3 -c 'import json,sys
try: print("true" if json.load(sys.stdin).get("stop_hook_active") is True else "false")
except Exception: print("unknown")' 2>/dev/null)"
else
  ACTIVE=unknown
fi
if [ "$ACTIVE" != "true" ] && [ "$ACTIVE" != "false" ]; then
  printf '%s' "$INPUT" | grep -Eq '"stop_hook_active"[[:space:]]*:[[:space:]]*true' && ACTIVE=true
fi
[ "$ACTIVE" = "true" ] && { echo '{}'; exit 0; }

CHECK_COMMAND=''
EXPORT_DIRS=('Claude outputs')   # stop-check.conf 에서 바꿀 수 있다
[ -f .agents/hooks/stop-check.conf ] && . ./.agents/hooks/stop-check.conf

ISSUES=""
add() { ISSUES+="- $1"$'\n'; }

# ① 상태 파일
STATE=.agents/state/STATE.json
if [ -f "$STATE" ] && [ "$HAS_JQ" = 1 ]; then
  if ! jq -e . "$STATE" >/dev/null 2>&1; then
    add "$STATE 가 올바른 JSON이 아닙니다."
  else
    for k in schema project current tasks updated_at; do
      jq -e "has(\"$k\")" "$STATE" >/dev/null 2>&1 || add "$STATE 에 필수 키 '$k' 가 없습니다."
    done
  fi
fi

# 검사 대상: 하네스 파일 중 이번에 바뀐 것(git) 또는 전부(git 없음)
is_excluded() {
  case "/$1" in
    */node_modules/*|*/vendor/*|*/.venv/*|*/venv/*|*/dist/*|*/build/*|*/target/*|*/third_party/*|*/.git/*) return 0 ;;
  esac
  return 1
}
is_instruction_file() {
  case "$1" in AGENTS.md|CLAUDE.md|GEMINI.md|*/AGENTS.md|*/CLAUDE.md|*/GEMINI.md) return 0 ;; esac
  return 1
}
is_harness_file() {
  is_excluded "$1" && return 1
  case "$1" in
    AGENTS.md|CLAUDE.md|GEMINI.md|*/AGENTS.md|*/CLAUDE.md|*/GEMINI.md) return 0 ;;
    .agents/skills/*/SKILL.md|.claude/skills/*/SKILL.md|.gemini/skills/*/SKILL.md) return 0 ;;
    .agents/hooks/*.sh|.githooks/*) return 0 ;;
    .claude/agents/*.md|.gemini/agents/*.md|.codex/agents/*.toml) return 0 ;;
  esac
  return 1
}
# third_party 사본(원문 그대로 보관)은 머리말 검사에서 제외한다.
is_vendored() {
  [ -f .agents/harness-lock.json ] || return 1
  if [ "$HAS_JQ" = 1 ]; then jq -e --arg p "$1" '.vendored // [] | index($p)' .agents/harness-lock.json >/dev/null 2>&1
  elif [ "$HAS_PY" = 1 ]; then python3 -c 'import json,sys
sys.exit(0 if sys.argv[1] in json.load(open(".agents/harness-lock.json",encoding="utf-8")).get("vendored",[]) else 1)' "$1" 2>/dev/null
  else return 1; fi
}

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # --relative: 상위 저장소의 하위 폴더에 설치한 경우에도 이 프로젝트 기준 경로로 받는다(독립 검수 N3)
  CHANGED="$( { $GQ diff --relative --name-only HEAD 2>/dev/null || $GQ diff --relative --name-only; $GQ ls-files --others --exclude-standard; } | sort -u)"
else
  # Git이 없으면 바뀐 파일을 알 수 없으므로 설치 기록의 파일과 루트 지침 파일만 본다(독립 검수 N1).
  CHANGED="$( { [ -f .agents/harness-lock.json ] && locklist; for x in AGENTS.md CLAUDE.md GEMINI.md; do [ -f "$x" ] && echo "$x"; done; } | sort -u)"
fi

while IFS= read -r f; do
  [ -z "$f" ] && continue
  [ -f "$f" ] || continue
  is_harness_file "$f" || continue
  is_vendored "$f" && continue
  # 설치 기록에 있는 파일만 ②③을 본다. 루트·하위 지침 파일은 ④만 본다(독립 재검수 R6).
  IN_LOCK=0; [ -f .agents/harness-lock.json ] && [ -n "$(lockget "$f" sha256)" ] && IN_LOCK=1
  if [ "$IN_LOCK" = 0 ]; then
    is_instruction_file "$f" && grep -Eq '\{\{[^}]+\}\}' "$f" && add "$f: 채우지 않은 {{자리표시자}}가 남아 있습니다."
    continue
  fi
  # ② 머리말: 첫 15줄 안의 "harness-kit: ... vYYMMDDNN" 또는 SKILL.md frontmatter 의 metadata.version
  if ! head -n 15 "$f" | grep -Eq 'harness-kit: .* v[0-9]{8}' \
     && ! sed -n '1,/^---$/p' "$f" | sed -n '2,40p' | grep -Eq '^[[:space:]]+version:[[:space:]]*"?v[0-9]{8}'; then
    add "$f: 버전 머리말이 없습니다. 첫머리에 'harness-kit: $f vYYMMDDNN | updated YYYY-MM-DD HH:mm KST'를 넣으세요(SKILL.md는 metadata.version)."
  fi
  # ③ 내용 변경 대비 버전 유지
  if [ -f .agents/harness-lock.json ]; then
    LOCK_SHA="$(lockget "$f" sha256)"
    LOCK_VER="$(lockget "$f" version)"
    if [ -n "$LOCK_SHA" ] && [ -n "$LOCK_VER" ]; then
      NOW_SHA="$( (sha256sum "$f" 2>/dev/null || shasum -a 256 "$f" 2>/dev/null) | awk '{print $1}')"
      if [ -n "$NOW_SHA" ] && [ "$NOW_SHA" != "$LOCK_SHA" ] && grep -q -- "$LOCK_VER" <(head -n 40 "$f"); then
        add "$f: 설치본($LOCK_VER)과 내용이 다른데 버전이 그대로입니다. 버전 번호와 갱신 시각을 올리세요(version-bump 스킬)."
      fi
    fi
  fi
  # ④ 자리표시자
  if is_instruction_file "$f" && grep -Eq '\{\{[^}]+\}\}' "$f"; then
    add "$f: 채우지 않은 {{자리표시자}}가 남아 있습니다."
  fi
done <<< "$CHANGED"

# ⑥ 중복 사본 의심(한 번만 알린다)
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  DUPS=""
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    is_excluded "$f" && continue
    # 이름을 NFC로 맞춘다(macOS NFD 이름 대비, 독립 검수 L-a)
    # 사본 모양의 이름만 python3로 NFC 변환한다(파일마다 python3를 띄우지 않게, 독립 재검수 R5)
    case "$f" in *-[0-9].*|*-[0-9][0-9].*|*\ \(*\).*|*\ copy.*) ;; *) continue ;; esac
    [ "$HAS_PY" = 1 ] && f="$(python3 -c 'import sys,unicodedata;print(unicodedata.normalize("NFC",sys.argv[1]))' "$f")"
    d="$(dirname "$f")"; b="$(basename "$f")"; orig=""
    # 번호 사본은 1~2자리만 본다: report-2024.md 같은 연도 이름을 잡지 않게 한다(독립 검수 L-b)
    if [[ "$b" =~ ^(.+)-[0-9]{1,2}(\.[^./]+)$ ]] || [[ "$b" =~ ^(.+)\ \([0-9]+\)(\.[^./]+)$ ]] || [[ "$b" =~ ^(.+)\ copy(\.[^./]+)$ ]]; then
      orig="${BASH_REMATCH[1]}${BASH_REMATCH[2]}"
      [ "$d" != "." ] && orig="$d/$orig"
      { [ -f "$orig" ] || [ -f "$(python3 -c 'import sys,unicodedata;print(unicodedata.normalize("NFD",sys.argv[1]))' "$orig" 2>/dev/null)" ]; } && DUPS+="  $f (원본: $orig)"$'\n'
    fi
  done <<< "$($GQ ls-files --others --exclude-standard)"
  for x in ${EXPORT_DIRS[@]+"${EXPORT_DIRS[@]}"}; do  # bash 3.2 에서 빈 배열과 set -u 가 함께 쓰여도 오류가 나지 않게 한다
    [ -n "$x" ] && [ -d "$x" ] && [ -z "$($GQ ls-files -- "$x" | head -n 1)" ] && DUPS+="  $x/ (도구가 내보낸 폴더로 보임)"$'\n'
  done
  if [ -n "$DUPS" ]; then
    ACK_FILE="$(git rev-parse --git-dir)/harness-kit-dup-ack"
    HASH="$(printf '%s' "$DUPS" | (sha256sum 2>/dev/null || shasum -a 256) | awk '{print $1}')"
    if [ "$(cat "$ACK_FILE" 2>/dev/null)" != "$HASH" ]; then
      printf '%s' "$HASH" > "$ACK_FILE" 2>/dev/null || true
      add "중복 사본으로 보이는 미추적 파일이 있습니다. 이번 세션의 작업(수정 시각·파일명·내용)과 대조해 출처를 확인하고 사용자에게 보고하세요. 사용자 확인 없이 지우지 마세요:"$'\n'"$DUPS"
    fi
  fi
fi

# ⑤ 프로젝트 품질 검사
if [ -n "$CHECK_COMMAND" ]; then
  if ! OUT="$(bash -c "$CHECK_COMMAND" 2>&1)"; then
    add "품질 검사 실패: $CHECK_COMMAND"$'\n'"$(printf '%s' "$OUT" | tail -n 20)"
  fi
fi

STOP_ACK="$(git rev-parse --git-dir 2>/dev/null)/harness-kit-stop-ack"
git rev-parse --git-dir >/dev/null 2>&1 || STOP_ACK="${TMPDIR:-/tmp}/harness-kit-stop-ack-$(printf '%s' "$ROOT" | cksum | awk '{print $1}')"
if [ -z "$ISSUES" ]; then
  rm -f "$STOP_ACK" 2>/dev/null
else
  # 세션 ID를 함께 넣어 새 세션에서는 다시 알린다(배포 전 검증 V1). 세션 ID가 없으면 내용만 본다.
  SID=""
  if [ "$HAS_JQ" = 1 ]; then SID="$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)"
  elif [ "$HAS_PY" = 1 ]; then SID="$(printf '%s' "$INPUT" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("session_id") or "")
except Exception: pass' 2>/dev/null)"
  else SID="$(printf '%s' "$INPUT" | grep -Eo '"session_id"[[:space:]]*:[[:space:]]*"[^"]*"' | head -n 1)"; fi
  SUM="$(printf '%s\n%s' "$SID" "$ISSUES" | cksum | awk '{print $1 "-" $2}')"
  [ "$(cat "$STOP_ACK" 2>/dev/null)" = "$SUM" ] && { echo '{}'; exit 0; }
  printf '%s' "$SUM" > "$STOP_ACK" 2>/dev/null || true
fi
if [ -n "$ISSUES" ]; then
  { echo "종료 전 검사(stop-check)에서 문제를 찾았습니다. 고친 뒤 마무리하세요. 고칠 수 없으면 이유를 사용자에게 한 번 보고하세요(같은 내용은 다시 알리지 않습니다):"; printf '%s' "$ISSUES"; } >&2
  exit 2
fi

echo '{}'
exit 0
