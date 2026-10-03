from peerreview.model import EvidenceLevel, InvolvementAct, ProcessingStatus


def test_no_value_confirms_non_use():
    # 신호 부재를 AI 미사용 확인으로 바꾸지 않는다 (보고서 3절).
    assert not any("non_use" in v or "human_confirmed" in v for v in EvidenceLevel)


def test_unknown_act_exists():
    assert InvolvementAct("unknown") is InvolvementAct.UNKNOWN


def test_status_and_evidence_are_separate_axes():
    assert not set(EvidenceLevel) & set(ProcessingStatus)
