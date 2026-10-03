<!-- harness-kit: .agents/state/SESSION_LOG.md v26092601 | updated 2026-09-26 19:01 KST -->
# 세션 기록

작업이 끝날 때마다 아래 형식으로 맨 아래에 추가한다. 작성일·작성자·변경 파일은 Git이 가지므로 적지 않는다.

```text
## T001 <작업 제목> [done|partial|failed|blocked]
- 결과: 사용자가 관측할 수 있는 결과 한 줄
- 증거: 실행한 검사와 결과(명령, 통과/실패/미실행), 커밋 해시
- 남은 것: 다음 행동 또는 없음
```

## 오류

오류는 발생한 작업 번호와 함께 남긴다. 재발 방지를 검사(훅·시험)로 옮겼으면 그 위치를 적는다.

```text
### E001 <오류 제목> (T001)
- 원인:
- 결과:
- 재발 방지: <검사 위치 또는 "지침만">
```

## 2026-10-03 T000 프로젝트 세팅
- 결과: HarnessKit v26092612 전체 수준(Claude Code·Codex) 설치, git init, uv 패키지 골격과 판정 어휘(model.py) 작성, 제공 자료를 docs/source/로 이동.
- 증거: `uv run pytest -q` 3 passed, `uv run ruff check .` 통과, verify.py 불일치 없음, stop-check.sh 종료 코드 0.
- 남은 것: T001 목표 정의서. '제공 자료 나' v1.0 docx 미보유. 디스크 여유 9.5GiB.
