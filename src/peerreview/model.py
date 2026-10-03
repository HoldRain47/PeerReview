"""판정 기록의 기본 어휘.

근거: 논문_AI관여판단_프로그램개발보고서_v2.0-최종.docx 2~4절.
증거 수준과 처리 상태는 서로 독립된 축으로 기록한다.
"""

from enum import StrEnum


class InvolvementAct(StrEnum):
    """AI 관여 행위 유형 (2절). 확인할 수 없으면 UNKNOWN으로 남긴다."""

    GENERATION = "generation"  # 본문 생성
    REWRITING = "rewriting"  # 재작성
    PROOFREADING = "proofreading"  # 교정
    TRANSLATION = "translation"  # 번역
    MIXED = "mixed"  # 혼합 작성
    HUMAN_EDITED_AI = "human_edited_ai"  # AI 초안을 사람이 수정
    QUOTED_AI_OUTPUT = "quoted_ai_output"  # 연구 대상으로서의 AI 출력 인용
    SEARCH_IDEATION = "search_ideation"  # 검색·아이디어 정리(원고 문장 산출 없음)
    UNKNOWN = "unknown"  # 미상


# 1차 목표 행위 (목표 정의서 v26100302). 혼합 작성과 AI 초안의 사람 수정도
# 생성이 포함되므로 목표 행위가 있는 것으로 보되, 결과는 행위별로 나눠 보고한다.
TARGET_ACTS = frozenset(
    {
        InvolvementAct.GENERATION,
        InvolvementAct.REWRITING,
        InvolvementAct.MIXED,
        InvolvementAct.HUMAN_EDITED_AI,
    }
)


class EvidenceLevel(StrEnum):
    """증거 수준 (3절). AI 미사용 '확인' 값은 두지 않는다."""

    RECORD_CONFIRMED = "record_confirmed"  # 작성 자료로 확인
    TEXT_ESTIMATE = "text_estimate"  # 검증된 방법에 따른 텍스트 기반 추정
    STYLE_SIGNAL = "style_signal"  # 성능 미검증 문체 신호 관찰
    UNVERIFIED_RECORD = "unverified_record"  # 진위·연결 미확인 자료
    WITHHELD = "withheld"  # 판단 유보


class ProcessingStatus(StrEnum):
    """처리 상태 (3절). 증거 수준과 별도로 관리한다."""

    COMPLETED = "completed"  # 분석 완료
    PARTIAL = "partial"  # 일부 처리
    EXTRACTION_FAILED = "extraction_failed"  # 추출 실패
    TOO_SHORT = "too_short"  # 분량 부족
    OUT_OF_SCOPE = "out_of_scope"  # 지원 범위 밖
