from peerreview.model import (
    TARGET_ACTS,
    EvidenceLevel,
    InvolvementAct,
    ProcessingStatus,
)


def test_no_value_confirms_non_use():
    # 신호 부재를 AI 미사용 확인으로 바꾸지 않는다 (보고서 3절).
    assert not any("non_use" in v or "human_confirmed" in v for v in EvidenceLevel)


def test_unknown_act_exists():
    assert InvolvementAct("unknown") is InvolvementAct.UNKNOWN


def test_status_and_evidence_are_separate_axes():
    assert not set(EvidenceLevel) & set(ProcessingStatus)


def test_non_target_acts():
    # 교정·번역·검색·인용은 목표 행위로 표시하면 오탐이다 (보고서 6절, 목표 정의서 3절).
    non_target = {
        InvolvementAct.PROOFREADING,
        InvolvementAct.TRANSLATION,
        InvolvementAct.SEARCH_IDEATION,
        InvolvementAct.QUOTED_AI_OUTPUT,
        InvolvementAct.UNKNOWN,
    }
    assert not TARGET_ACTS & non_target
    assert TARGET_ACTS | non_target == set(InvolvementAct)
