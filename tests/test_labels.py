"""라벨 기록 시험. 라벨 지침 v26100303 6절의 사례 L01~L24가 지침 표와 같은 결과를 내는지 본다."""

import json

import pytest

from peerreview import main
from peerreview.labels import (
    LabelRecord,
    Span,
    TargetPresence,
    TruthBasis,
    derive_target,
    load_labels,
    save_labels,
    validate,
)
from peerreview.model import InvolvementAct as Act

YES, NO, UNK = TargetPresence.YES, TargetPresence.NO, TargetPresence.UNKNOWN

# (사례, 관여 행위, 정답 근거, 지침 표의 target_present)
CASES = [
    ("L01 문법 오류만 고침", [Act.PROOFREADING], "A", NO),
    ("L02 Rewrite 기능이지만 결과는 교정", [Act.PROOFREADING], "A", NO),
    ("L03 문장 합치기·평가어 추가", [Act.REWRITING], "A", YES),
    ("L04 한국어 초안 전체 번역", [Act.TRANSLATION], "A", NO),
    ("L05 번역 뒤 재작성", [Act.TRANSLATION, Act.REWRITING], "A", YES),
    ("L06 개요를 문단으로 풀어 씀", [Act.GENERATION], "A", YES),
    ("L07 AI 초안을 사람이 대부분 다시 씀", [Act.HUMAN_EDITED_AI], "A", YES),
    ("L08 한 문단 안 사람·AI 혼합", [Act.MIXED], "A", YES),
    ("L09 검색·개념 설명만", [Act.SEARCH_IDEATION], "A", NO),
    ("L10 연구 대상으로 AI 응답 인용", [Act.QUOTED_AI_OUTPUT], "A", NO),
    ("L11 상투 표현 많은 사람 글(현재 자료)", [], "A", NO),
    ("L11 상투 표현 많은 사람 글(보급 이전 자료)", [], "D", NO),
    ("L12 사람 전문 교열", [], "A", NO),
    ("L13 자동 완성 단어 몇 개", [Act.PROOFREADING], "A", NO),
    ("L14 표절 회피 목적 바꿔 쓰기", [Act.REWRITING], "A", YES),
    ("L15 초록만 AI 생성", [Act.GENERATION], "A", YES),
    ("L16 진술만 있고 기록 없음", [Act.UNKNOWN], "C", UNK),
    ("L17 기록과 원고 연결 미확인", [Act.UNKNOWN], "C", UNK),
    ("L18 chatgpt 링크만 있음", [Act.UNKNOWN], "C", UNK),
]


@pytest.mark.parametrize(
    ("case", "acts", "basis", "expected"), CASES, ids=[c[0][:3] for c in CASES]
)
def test_guideline_cases(case, acts, basis, expected):
    rec = LabelRecord(
        doc_id=case, bundle_id="b1", truth_basis=TruthBasis(basis), acts=acts
    )
    assert derive_target(rec) == expected
    assert validate(rec) == []


def test_no_from_weak_basis_is_unknown():
    # 근거 B·C로는 "목표 행위 없음"을 확정하지 않는다(라벨 지침 2·4절)
    for basis in ("B", "C"):
        rec = LabelRecord("d", "b", TruthBasis(basis), acts=[Act.PROOFREADING])
        assert derive_target(rec) == UNK
        rec.target_present = NO
        assert any("판정 절차로는 unknown" in e for e in validate(rec))


def test_target_from_weak_basis_is_yes():
    # 근거가 약해도 기록이 보여 주는 목표 행위는 예로 둔다(불확실 집단으로 따로 분석)
    rec = LabelRecord("d", "b", TruthBasis.B, acts=[Act.GENERATION])
    assert derive_target(rec) == YES


def test_validation_errors():
    rec = LabelRecord(
        doc_id="",
        bundle_id=" ",
        truth_basis=TruthBasis.D,
        acts=[Act.GENERATION, Act.GENERATION],
        spans=[Span(Act.TRANSLATION, "")],
    )
    errors = " / ".join(validate(rec))
    for part in ("doc_id", "bundle_id", "두 번", "근거 D", "acts에 없음", "loc"):
        assert part in errors


def test_jsonl_round_trip_and_line_errors(tmp_path):
    p = tmp_path / "labels.jsonl"
    recs = [
        LabelRecord(
            "d1", "b1", TruthBasis.A, [Act.REWRITING], [Span(Act.REWRITING, "p3:L0-9")]
        ),
        LabelRecord("d2", "b1", TruthBasis.D),
    ]
    save_labels(p, recs)
    loaded, errors = load_labels(p)
    assert errors == []
    assert [derive_target(r) for r in loaded] == [YES, NO]
    assert (
        json.loads(p.read_text(encoding="utf-8").splitlines()[0])["target_present"]
        == "yes"
    )

    p.write_text(
        p.read_text(encoding="utf-8")
        + '{"doc_id": "d1", "bundle_id": "b2", "truth_basis": "A"}\n'
        + '{"doc_id": "d3", "bundle_id": "b3", "truth_basis": "Z"}\n'
        + "not json\n",
        encoding="utf-8",
    )
    _, errors = load_labels(p)
    assert any(e.startswith("3줄") and "중복" in e for e in errors)
    assert any(e.startswith("4줄") for e in errors)
    assert any(e.startswith("5줄") for e in errors)


def test_check_labels_cli(tmp_path, capsys):
    p = tmp_path / "labels.jsonl"
    save_labels(p, [LabelRecord("d1", "b1", TruthBasis.A, [Act.GENERATION])])
    assert main(["check-labels", str(p)]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["records"] == 1 and out["errors"] == 0
    assert out["stages"]["body"] == {"yes": 1} and out["stages"]["ai_translation"] == {
        "no": 1
    }
    p.write_text(
        '{"doc_id": "x", "bundle_id": "", "truth_basis": "A"}\n', encoding="utf-8"
    )
    assert main(["check-labels", str(p)]) == 1


def test_unknown_act_blocks_no_and_weak_empty_is_unknown():
    # 미상 행위가 섞이면 근거 A여도 "아니오"로 확정하지 않는다
    rec = LabelRecord("d", "b", TruthBasis.A, acts=[Act.PROOFREADING, Act.UNKNOWN])
    assert derive_target(rec) == UNK
    # 행위 기록이 없어도 근거 B면 "아니오"가 아니라 미상
    assert derive_target(LabelRecord("d", "b", TruthBasis.B)) == UNK


def test_non_object_line_is_reported_not_crash(tmp_path):
    p = tmp_path / "labels.jsonl"
    p.write_text("[1]\n", encoding="utf-8")
    records, errors = load_labels(p)
    assert records == [] and errors and errors[0].startswith("1줄")


# (사례, 관여 행위, 정답 근거, 예인 단계) — 라벨 지침 v26100303 6절의 번역 경로 사례
STAGE_CASES = [
    ("L04 한국어 초안을 ChatGPT로 번역", [Act.TRANSLATION], "A", {"ai_translation"}),
    (
        "L05 AI 번역 뒤 재작성",
        [Act.TRANSLATION, Act.REWRITING],
        "A",
        {"ai_translation", "body"},
    ),
    ("L13 자동 완성 단어", [Act.PROOFREADING], "A", {"ai_polishing"}),
    ("L19 사람 번역 기관", [], "A", set()),
    ("L20 Papago 번역", [Act.MACHINE_TRANSLATION], "A", {"machine_translation"}),
    (
        "L21 Papago 뒤 문법만 AI 교정",
        [Act.MACHINE_TRANSLATION, Act.PROOFREADING],
        "A",
        {"machine_translation", "ai_polishing"},
    ),
    ("L22 한국어 AI 초안 뒤 사람 번역", [Act.GENERATION], "A", {"body"}),
    (
        "L23 기관의 기계 번역 초벌",
        [Act.MACHINE_TRANSLATION],
        "A",
        {"machine_translation"},
    ),
    ("L24 영어 직접 작성 뒤 AI 문법 검사", [Act.PROOFREADING], "A", {"ai_polishing"}),
]


@pytest.mark.parametrize(
    ("case", "acts", "basis", "yes"), STAGE_CASES, ids=[c[0][:3] for c in STAGE_CASES]
)
def test_stage_cases(case, acts, basis, yes):
    from peerreview.labels import derive_stages

    rec = LabelRecord(
        doc_id=case, bundle_id="b", truth_basis=TruthBasis(basis), acts=acts
    )
    stages = {k.value: v for k, v in derive_stages(rec).items()}
    assert {k for k, v in stages.items() if v == YES} == yes
    assert all(
        v == NO for k, v in stages.items() if k not in yes
    )  # 근거 A이면 나머지는 아니오


def test_basis_d_does_not_rule_out_machine_translation():
    from peerreview.labels import derive_stages
    from peerreview.model import Stage

    st = derive_stages(LabelRecord("d", "b", TruthBasis.D))
    assert st[Stage.MACHINE_TRANSLATION] == UNK
    assert st[Stage.BODY] == st[Stage.AI_TRANSLATION] == st[Stage.AI_POLISHING] == NO


def test_korean_draft_span_and_stored_stage_mismatch(tmp_path):
    rec = LabelRecord(
        "d", "b", TruthBasis.A, [Act.GENERATION], [Span(Act.GENERATION, "draft", "ko")]
    )
    assert validate(rec) == []
    assert validate(
        LabelRecord(
            "d", "b", TruthBasis.A, [Act.GENERATION], [Span(Act.GENERATION, "x", "jp")]
        )
    )
    p = tmp_path / "l.jsonl"
    save_labels(p, [rec])
    row = json.loads(p.read_text(encoding="utf-8"))
    assert row["stages"]["body"] == "yes" and row["spans"][0]["lang"] == "ko"
    row["stages"]["ai_translation"] = "yes"
    p.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    _, errors = load_labels(p)
    assert any("stages.ai_translation" in e for e in errors)


def test_variant_rest_basis_keeps_machine_translation_unknown():
    from peerreview.labels import derive_stages
    from peerreview.model import Stage

    v = LabelRecord("v", "b", TruthBasis.A, [Act.REWRITING], rest_basis=TruthBasis.D)
    st = derive_stages(v)
    assert st[Stage.BODY] == YES
    assert (
        st[Stage.AI_TRANSLATION] == NO
    )  # 바꾼 부분(A)과 원문(D) 모두 생성형 AI 번역을 배제한다
    assert st[Stage.MACHINE_TRANSLATION] == UNK  # 원문(D) 부분의 기계 번역은 모른다


def test_save_refuses_inconsistent_and_d_allows_machine_translation(tmp_path):
    bad = LabelRecord("d", "b", TruthBasis.A, [Act.GENERATION], target_present=NO)
    with pytest.raises(ValueError):
        save_labels(tmp_path / "x.jsonl", [bad])
    assert not (tmp_path / "x.jsonl").exists()
    mt_old = LabelRecord("d", "b", TruthBasis.D, [Act.MACHINE_TRANSLATION])
    assert validate(mt_old) == []
    assert validate(LabelRecord("d", "b", TruthBasis.D, [Act.GENERATION]))


def test_non_object_stages_reported(tmp_path):
    p = tmp_path / "l.jsonl"
    p.write_text(
        '{"doc_id": "d", "bundle_id": "b", "truth_basis": "A", "stages": ["body"]}\n',
        encoding="utf-8",
    )
    _, errors = load_labels(p)
    assert any("stages가 객체가 아님" in e for e in errors)
