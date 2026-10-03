<!-- harness-kit: CLAUDE.md v26092601 | updated 2026-09-26 19:01 KST -->
@AGENTS.md

## Claude Code 전용
- 스킬 원본은 `.agents/skills/`이며 `.claude/skills/`는 사본이다. 수정은 원본에서 하고 `python3 "$HARNESS_KIT_HOME/tools/install.py" --target . --sync-skills`로 사본을 맞춘다.
- 하위 에이전트: `.claude/agents/verifier.md`. 단순·반복 작업은 가벼운 모델(sonnet 등)로 위임한다.
- 훅 등록: `.claude/settings.json`. 바꾼 뒤에는 세션을 다시 시작하고 `/hooks`로 확인한다.
