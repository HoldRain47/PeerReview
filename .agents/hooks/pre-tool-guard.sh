#!/usr/bin/env bash
# harness-kit: hooks/pre-tool-guard.sh v26092611 | updated 2026-09-27 02:49 KST
# =====================================================================
# 도구 실행 전 훅. 셸 명령이 실행되기 전에 되돌릴 수 없는 명령을 막는다.
#   Claude Code: PreToolUse(matcher Bash)  Codex CLI: PreToolUse(matcher Bash)
#   Gemini CLI: BeforeTool(matcher run_shell_command)
# 입력: stdin JSON의 .tool_input.command (세 도구 공통. Gemini는 첫 적용 때 확인)
# 차단: 종료 코드 2 + stderr에 이유 / 통과: stdout "{}" + 종료 코드 0
# 한계: 정규식 검사라 모든 우회를 막지 못하고, 막으면 오탐이 생기는 경계가 남는다. 흔한 실수를 한 번 멈추는 보조 장치다.
#   막지 않는 것(알려진 한계): 변수·스크립트 파일로 실행, heredoc 안 명령(여러 줄 본문의 줄 머리는 오탐도 남)
#   timeout·nice·doas 같은 접두어, /bin/rm 같은 절대 경로, 브랜치를 생략한 push --force-with-lease, find . -delete.
#   확실한 보호는 도구 샌드박스, 원격 저장소의 브랜치 보호, Git 이력·백업에 맡긴다.
# 설정: .agents/hooks/guard.conf 가 있으면 한 줄에 하나씩 추가 차단 패턴(확장 정규식)을 읽는다.
# 필요 환경: bash, jq 또는 python3(둘 다 없으면 검사를 건너뛰고 stderr에 알린다). 부작용 없음.
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

if command -v jq >/dev/null 2>&1; then
  CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // .tool_input.cmd // empty' 2>/dev/null)"
elif command -v python3 >/dev/null 2>&1; then
  # jq 가 없으면 python3 로 같은 필드를 읽는다.
  CMD="$(printf '%s' "$INPUT" | python3 -c 'import json,sys
try:
    t=json.load(sys.stdin).get("tool_input") or {}
    print(t.get("command") or t.get("cmd") or "")
except Exception:
    pass' 2>/dev/null)"
else
  echo "pre-tool-guard: jq와 python3가 모두 없어 검사를 건너뜁니다. jq를 설치하세요." >&2
  echo '{}'; exit 0
fi
[ -z "$CMD" ] && { echo '{}'; exit 0; }

# 검사용 사본 두 개를 만든다. 실행되는 명령은 바꾸지 않는다(독립 검수 N4·N5).
#   STRICT: 따옴표만 벗긴 사본. 명령 이름이 명령 위치(줄 시작, ; & | ( 뒤, sudo·env·xargs·eval·sh -c 뒤)에 올 때만 본다.
#           따라서 grep "rm -rf /" 처럼 인자 속 문자열은 막지 않고, rm -rf "/" 는 막는다.
#   SAFE:   따옴표 안 내용을 Q로 바꾼 사본. 옵션 검사(--no-verify, commit -n 등)에 쓴다. 커밋 메시지 속 낱말은 막지 않는다.
#   공통 정규화: ${HOME}→$HOME, $'..'→'..', git 전역 옵션 제거(-C·-c·-P·--git-dir·--work-tree 등), --recursive→-r, --force→-f, 단독 -- 제거
norm() {
  sed -E \
    -e 's/[$][{]HOME[}]/$HOME/g' \
    -e "s/[\$]'/'/g" \
    -e 's/(^|[;&|(`[:space:]])git(([[:space:]]+(-C|-c|--git-dir|--work-tree|--namespace)[[:space:]]+[^[:space:]]+)|([[:space:]]+--(git-dir|work-tree|namespace|exec-path)=[^[:space:]]+)|([[:space:]]+(-P|--paginate|--no-pager|--bare|--literal-pathspecs|--no-replace-objects)))+/\1git/g' \
    -e 's/--recursive/-r/g' \
    -e 's/--force([[:space:]]|$)/-f\1/g' \
    -e 's/[[:space:]]--([[:space:]]|$)/ /g'
}
STRICT="$(printf '%s' "$CMD" | sed -E -e "s/[\$]'/'/g" -e "s/[\"']//g" | norm)"
SAFE="$(printf '%s' "$CMD" | sed -E -e 's/"[^"]*"/Q/g' -e "s/'[^']*'/Q/g" | norm)"
RAWSTRICT="$(printf '%s' "$CMD" | sed -E "s/[\"']//g")"   # git -c 값을 봐야 하는 검사용(정규화 전)

S='[[:space:]]'
# 명령 위치: 줄 시작 또는 ; & | ( { ` $( 뒤, 그리고 앞에 붙는 sudo·env·command·exec·nohup·time·xargs·eval·sh -c·\ 와 VAR=값
A="(^|[;&|({\`]|[\$][(])${S}*((sudo|env|command|exec|nohup|time|xargs|eval|builtin)${S}+|((ba|z|da)?sh)${S}+-c${S}+|[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*${S}+)*\\\\?"
T_ROOT="(/|/[?*[{][^[:space:]]*|~|~/|~/\\.?[?*[{][^[:space:]]*|\\\$HOME|\\\$HOME/|\\\$HOME/\\.?[?*[{][^[:space:]]*|\\\$PWD/?|\\\$[(]pwd[)]|\`pwd\`|(\\./)?\\.git/?|\\*|\\.|\\./|\\./\\*|\\.\\.(/\\.\\.)*/?|\\.\\./\\*|/(home|Users|root)(/[^/[:space:]]+)?/?)"
E="(${S}|;|&|\\||\\)|$)"

STRICT_PATTERNS=(
  # 루트·홈·현재·상위 폴더 전체 삭제(--no-preserve-root 등 긴 옵션 포함)
  "폴더 전체 삭제(rm -r):::${A}rm${S}+(-[a-zA-Z-]*${S}+)*-[a-zA-Z]*[rR][a-zA-Z]*${S}+(-[a-zA-Z-]*${S}+)*${T_ROOT}${E}"
  "루트·홈 대상 find 삭제:::${A}find${S}+(/|~|\\\$HOME)${E}(.*${S})?-(delete|exec${S}+rm)"
  # 강제 push·원격 브랜치 삭제·미러 push(--force-with-lease 는 아래에서 main/master 대상만 막는다)
  "강제 push·원격 브랜치 삭제:::${A}git${S}+push(${S}+[^[:space:]]+)*${S}+(-[a-zA-Z]*f[a-zA-Z]*|--mirror|--delete|-d|\\+[^[:space:]]+|:[^[:space:]]+)${E}"
  # 작업 트리·이력 파괴
  "git reset --hard:::${A}git${S}+reset${S}+(.*${S})?--hard"
  "git clean -f:::${A}git${S}+clean${S}+(-[a-zA-Z]*${S}+)*-[a-zA-Z]*f"
  "git checkout -f:::${A}git${S}+checkout${S}+(.*${S})?-f${E}"
  "작업 트리 되돌리기(git checkout .):::${A}git${S}+checkout(${S}+[^-[:space:]][^[:space:]]*)?${S}+\\.${E}"
  # --staged 만 준 restore 는 스테이징만 풀므로 막지 않는다
  "작업 트리 되돌리기(git restore .):::${A}git${S}+restore${S}+((--worktree|-W|--source=[^[:space:]]+|-s${S}+[^[:space:]]+)${S}+)*\\.${E}"
  "git switch -f:::${A}git${S}+switch${S}+(.*${S})?(-f|--discard-changes)${E}"
  "stash 삭제:::${A}git${S}+stash${S}+(drop|clear)${E}"
  "브랜치 강제 삭제(branch -D):::${A}git${S}+branch${S}+(.*${S})?-D${E}"
  "reflog 만료:::${A}git${S}+reflog${S}+expire"
  "gc --prune=now:::${A}git${S}+gc${S}+(.*${S})?--prune=now"
  "ref 삭제(update-ref -d):::${A}git${S}+update-ref${S}+-d"
  "이력 재작성(filter-branch):::${A}git${S}+filter-(branch|repo)"
  # 값 읽기(--get)는 막지 않고, 설정·해제만 막는다
  "Git 훅 경로 변경(core.hooksPath):::${A}git${S}+config${S}+(--(local|global|system|worktree)${S}+)*(--unset(-all)?${S}+core\\.hooksPath|core\\.hooksPath${S}+[^[:space:]])"
  # 원격 스크립트를 바로 실행
  # 받은 내용을 스크립트로 실행할 때만 막는다(| python3 -m json.tool 처럼 데이터로 읽는 것은 허용)
  "원격 스크립트 실행(curl | sh):::${A}(curl|wget)${S}[^|]*\\|${S}*(sudo${S}+)?((ba|z|da)?sh|python3?|perl|ruby|node)(${S}+-[s-]*(${S}.*)?)?${S}*($|[;&|)])"
  "원격 스크립트 실행(sh -c 안의 curl):::${A}((ba|z|da)?sh)${S}+-c${S}+.*[\$][(]${S}*(curl|wget)${S}"
  "원격 스크립트 실행(sh 에 curl 결과 연결):::${A}((ba|z)?sh|source|\\.)${S}+<${S}*\\(${S}*(curl|wget)"
  # 권한 전체 개방
  "권한 전체 개방(chmod 777):::${A}chmod${S}+(-R${S}+)?(0?777|a\\+rwx|ugo\\+rwx)${E}"
)
SAFE_PATTERNS=(
  # 검사 우회(git 명령의 옵션만 본다. 커밋 메시지·검색어 속 낱말은 막지 않는다)
  "검사 건너뛰기(--no-verify):::${A}git${S}+(commit|push|merge|am|rebase|cherry-pick|revert|pull)${S}(.*${S})?--no-verify"
  "검사 건너뛰기(git commit -n):::${A}git${S}+commit${S}(.*${S})?-[a-zA-Z]*n[a-zA-Z]*${E}"
  "권한 확인 끄기(--dangerously):::${A}([^[:space:]]*/)?(claude|codex|gemini)${S}(.*${S})?--dangerously"
)
RAW_PATTERNS=(
  # git -c core.hooksPath=... 로 Git 훅을 끄는 우회(전역 옵션 정규화 전에 본다)
  "Git 훅 끄기(git -c core.hooksPath):::(^|[;&|(]|${S})git${S}+(.*${S})?-c${S}*core\\.hooksPath"
)

if [ -f "$ROOT/.agents/hooks/guard.conf" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    STRICT_PATTERNS+=("guard.conf 규칙:::$line")
  done < "$ROOT/.agents/hooks/guard.conf"
fi

block() { echo "차단됨(pre-tool-guard): $1. 우회하지 말고, 꼭 필요하면 이유를 설명해 사용자가 직접 실행하게 하세요." >&2; exit 2; }

SHELLC=0
printf '%s' "$CMD" | grep -Eq -- "((ba|z|da)?sh${S}+-c|eval)${S}" && SHELLC=1
# 항목 형식: "짧은 이름:::정규식". 차단 이유는 짧은 이름만 보여 준다(정규식을 보여 주면 에이전트가 해석하려 들어 응답이 길어진다).
for e in "${STRICT_PATTERNS[@]}"; do
  printf '%s' "$STRICT" | grep -Eq -- "${e#*:::}" && block "${e%%:::*}"
done
for e in "${SAFE_PATTERNS[@]}"; do
  printf '%s' "$SAFE" | grep -Eq -- "${e#*:::}" && block "${e%%:::*}"
  # sh -c·eval 의 따옴표 안 명령도 검사한다
  [ "$SHELLC" = 1 ] && printf '%s' "$STRICT" | grep -Eq -- "${e#*:::}" && block "${e%%:::*}"
done
for e in "${RAW_PATTERNS[@]}"; do
  printf '%s' "$RAWSTRICT" | grep -Eq -- "${e#*:::}" && block "${e%%:::*}"
done

if printf '%s' "$STRICT" | grep -Eq -- "${A}git${S}+push${S}.*--force-with-lease" \
   && printf '%s' "$STRICT" | grep -Eq -- "(${S}|:)(main|master)(${S}|$)"; then
  block "main/master 브랜치에 대한 강제 push"
fi

echo '{}'
exit 0
