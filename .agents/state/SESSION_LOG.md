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

### E001 이력 재작성 후 docs/source 작업 파일 삭제 (공개 저장소 준비)
- 원인: main 이력에서 docs/source를 빼려고 `git filter-branch --index-filter`를 썼다(훅 차단으로 사용자가 직접 실행). 이 명령은 재작성 뒤 새 HEAD를 체크아웃하면서, 이력에서 빠진 추적 파일을 작업 폴더에서도 지운다. 에이전트가 "파일은 남는다"고 잘못 안내했다.
- 결과: 제공 자료 5개가 디스크에서 삭제됐다. 백업 브랜치 backup/pre-public-20261003에서 작업 폴더로 복구했고, git hash-object로 5개 모두 일치함을 확인했다.
- 재발 방지: 지침만. 이력에서 추적 파일을 뺄 때는 실행 전에 작업 폴더 밖으로 사본을 만든다. 또 pre-tool-guard는 명령 인자 안의 문장(커밋 메시지, heredoc)에 들어간 명령 이름에도 반응하므로, 기록에 그 이름을 쓸 때는 파일 편집 도구를 쓴다.

## 2026-10-03 T000 프로젝트 세팅
- 결과: HarnessKit v26092612 전체 수준(Claude Code·Codex) 설치, git init, uv 패키지 골격과 판정 어휘(model.py) 작성, 제공 자료를 docs/source/로 이동.
- 증거: `uv run pytest -q` 3 passed, `uv run ruff check .` 통과, verify.py 불일치 없음, stop-check.sh 종료 코드 0.
- 남은 것: T001 목표 정의서. '제공 자료 나' v1.0 docx 미보유. 디스크 여유 9.5GiB.

## 2026-10-03 T001 목표 정의서와 라벨 지침 [partial]
- 결과: 제공 자료 나(계획검토보고서 v1.0) 커밋, 사용자 결정(영어·공학/CS·생성+재작성·논문 단위)으로 docs/목표정의서-v26100301.md, docs/라벨지침-v26100301.md 작성. model.py에 search_ideation과 TARGET_ACTS 추가.
- 증거: `uv run pytest -q` 4 passed, `uv run ruff check .` 통과. 라벨 일치도 시험 미실행. v2.0의 '제공 자료 나 22쪽'은 docx 메타데이터(Pages=1, 템플릿 값)로 확인 못함.
- 남은 것: 사용자 검토·승인. 미정: 리뷰 출력 언어, too_short 기준 길이, 분야 세부 경계, D 근거 기준일(T002).

## 2026-10-03 T002 계획과 공개 저장소 준비 [partial]
- 결과: 분야를 Chemical Engineering으로 정정(문서 v26100302), T002 계획(tasks/plan.md), AGENTS.md에 공개 논문 외부 API 예외 추가. docs/source를 main 이력에서 빼고 .gitignore에 넣었다(공개 제외 결정). 운영 환경: Windows 10 필수, GUI 우선(CLI 허용), Python 설치형. Windows 10 시험 환경은 사용자가 준비한다.
- 증거: main 이력의 docs/source 0건, 복구한 파일 5개 해시 일치. 오류 E001.
- 남은 것: 사용자가 gh auth login을 하면 public 저장소를 만들어 main만 push, Windows CI 추가, 운영 환경을 AGENTS.md·목표 정의서에 기록.

## 2026-10-03 T001 승인 [done]
- 결과: 목표정의서·라벨지침 v26100302를 사용자가 승인. L07·L13은 지침 그대로 유지.
- 증거: 사용자 응답(대화). 문서 본문의 "초안" 표기는 다음 개정 때 고친다.
- 남은 것: 라벨 일관성은 T002.8에서 확인.
