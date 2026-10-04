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
    # 교정·번역·기계 번역·검색·인용은 본문 단계 행위가 아니다 (목표 정의서 v26100303 3·4절)
    non_body = {
        InvolvementAct.PROOFREADING,
        InvolvementAct.TRANSLATION,
        InvolvementAct.MACHINE_TRANSLATION,
        InvolvementAct.SEARCH_IDEATION,
        InvolvementAct.QUOTED_AI_OUTPUT,
        InvolvementAct.UNKNOWN,
    }
    assert not TARGET_ACTS & non_body
    assert TARGET_ACTS | non_body == set(InvolvementAct)


def test_stages_partition_acts():
    from peerreview.model import NON_STAGE_ACTS, STAGE_ACTS

    groups = list(STAGE_ACTS.values()) + [NON_STAGE_ACTS]
    union = set().union(*groups)
    assert union == set(InvolvementAct)
    assert sum(len(g) for g in groups) == len(union)  # 겹치지 않는다
