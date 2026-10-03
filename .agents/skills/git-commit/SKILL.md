---
name: git-commit
description: Git 커밋을 만들 때 사용한다. Conventional Commits 제목, 이유·검증 본문, AI 작성 트레일러, 경로 지정 추가, 비밀값 확인을 한 번에 처리한다. "커밋", "commit", "체크포인트 커밋"에도 사용한다.
metadata:
  version: "v26092601"
  updated: "2026-09-26 19:01 KST"
---
# Git 커밋

1. `git status --short`로 이번 작업의 변경과 기존 변경을 나눈다. 다른 사람·다른 작업의 변경은 넣지 않는다.
2. 파일을 경로로 지정해 추가한다(`git add .` 금지). `git diff --staged`를 읽고 비밀값·대용량 생성물·임시 파일이 없는지 확인한다.
3. 메시지:
   ```text
   <type>(<scope>): <요약, 72자 이내, 명령형>

   <왜 바꿨는지 1~3줄>
   검증: <명령과 결과. 미실행이면 미실행>
   Task: <작업 ID, 있으면>

   Co-Authored-By: <에이전트 이름> <noreply 주소>
   ```
   type: feat fix docs refactor test chore build ci perf style revert. 되돌릴 수 없는 호환성 변경이면 `!`를 붙인다.
4. 작성자 정보가 없으면 사용자에게 묻는다. 추정하거나 전역 설정을 바꾸지 않는다. 필요하면 `git -c user.name=.. -c user.email=.. commit`으로 그 명령에만 지정한다.
5. Git 훅이 거절하면 메시지나 내용을 고친다. `--no-verify`를 쓰지 않는다.
6. 병렬 에이전트 작업은 `agent/<도구>-<작업>` 브랜치와 `git worktree add ../<폴더> -b <브랜치>`로 격리하고, 병합할 때 squash한다.
7. push와 원격 저장소 생성은 사용자가 요청할 때만 한다. 공유 브랜치 강제 push는 하지 않는다.
