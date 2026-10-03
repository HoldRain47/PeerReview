"""변형본 만들기 시험. 모델 호출 없이 가상 XML과 가상 출력만 쓴다."""

from pathlib import Path

from peerreview.ingest import _jats_text, load, resolve_jats
from peerreview.model import InvolvementAct as Act
from peerreview.variants import (
    PILOT_ACTS,
    Task,
    build_steps,
    build_variant_xml,
    check_change,
    final_paragraphs,
    find_target,
    plan_tasks,
    split_output,
)

PARA = (
    "Membrane distillation is a thermally driven separation process. "
    "It uses a hydrophobic porous membrane to separate vapour from liquid water. "
    "The driving force is the vapour pressure difference across the membrane. "
    "Many studies have examined flux decline caused by fouling and wetting [1]. "
    "However, the role of feed temperature on long term stability remains unclear. "
    "This study therefore measures flux and rejection over three hundred hours of operation."
)


def _seed(tmp_path: Path, n_paras: int = 3) -> Path:
    paras = "".join(f"<p>{PARA} Paragraph {i}.</p>" for i in range(n_paras))
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><article><front><article-meta>'
        "<title-group><article-title>Long term membrane distillation</article-title></title-group>"
        "<abstract><p>We studied membrane distillation for three hundred hours.</p></abstract>"
        "</article-meta></front><body>"
        f"<sec><title>1. Introduction</title>{paras}</sec>"
        f"<sec><title>2. Methods</title><p>{PARA}</p></sec></body></article>"
    )
    p = tmp_path / "seed.xml"
    p.write_text(xml, encoding="utf-8")
    return p


def test_find_target_and_short_intro(tmp_path):
    t = find_target(_seed(tmp_path), "S1")
    assert t is not None and t.title == "Long term membrane distillation"
    assert t.locs == [
        "body[1]/sec[1]/p[1]",
        "body[1]/sec[1]/p[2]",
        "body[1]/sec[1]/p[3]",
    ]
    assert "three hundred hours" in t.abstract
    assert (
        find_target(_seed(tmp_path, n_paras=2), "S2") is None
    )  # 문단이 모자라면 고르지 않는다


def test_steps_per_act(tmp_path):
    t = find_target(_seed(tmp_path), "S1")
    gen, _ = build_steps(Act.GENERATION, t)
    assert PARA not in gen[0] and t.title in gen[0]  # 생성은 원문을 주지 않는다
    tr, _ = build_steps(Act.TRANSLATION, t)
    assert len(tr) == 2 and "{PREVIOUS_OUTPUT}" in tr[1] and PARA not in tr[1]
    mixed, kept = build_steps(Act.MIXED, t)
    assert len(kept) == 3 and all(k.startswith("Membrane distillation") for k in kept)
    assert "However, the role" not in mixed[0]  # 문단 뒷부분은 주지 않는다


def test_plan_tasks_covers_acts_and_alternates(tmp_path):
    t = find_target(_seed(tmp_path), "S1")
    tasks = plan_tasks([t, t], ("claude", "openai"), 1)
    assert len(tasks) == 2 * len(PILOT_ACTS)
    assert {x.act for x in tasks} == {a.value for a in PILOT_ACTS}
    assert {x.model_family for x in tasks} == {"claude", "openai"}


def test_split_and_mixed_assembly():
    assert split_output("a\n\nb\n\n\nc\n", 3) == ["a", "b", "c"]
    assert split_output("a\n\nb", 3) is None
    task = Task(
        "v",
        "S",
        Act.MIXED.value,
        "claude",
        [],
        ["l1", "l2"],
        kept_prefix=["K1.", "K2."],
    )
    assert final_paragraphs(task, "C1.\n\nC2.") == ["K1. C1.", "K2. C2."]


def test_build_variant_replaces_only_targets(tmp_path):
    seed = _seed(tmp_path)
    before = seed.read_bytes()
    t = find_target(seed, "S1")
    out = tmp_path / "variants" / "v.xml"
    build_variant_xml(seed, t.locs, ["NEW ONE.", "NEW TWO.", "NEW THREE."], out)
    assert seed.read_bytes() == before  # 씨앗 원본은 그대로
    assert _jats_text(resolve_jats(out, t.locs[1])) == "NEW TWO."
    doc = load(out)
    assert "NEW ONE." in doc.text() and PARA in doc.text()  # 방법 절 원문은 남는다


def test_check_change_relabels_by_guideline():
    orig = [PARA]
    proof = Task("v", "S", Act.PROOFREADING.value, "openai", [], ["l"])
    same = check_change(proof, orig, [PARA])
    assert same.label_act == Act.PROOFREADING.value and "바뀐 곳이 없음" in same.note
    rewritten = "Thermally driven membrane distillation separates vapour using porous hydrophobic membranes."
    changed = check_change(proof, orig, [rewritten])
    assert (
        changed.label_act == Act.REWRITING.value
    )  # 라벨 지침 5절: 구조·표현이 바뀌면 재작성
    rew = Task("v", "S", Act.REWRITING.value, "openai", [], ["l"])
    assert check_change(rew, orig, [PARA]).label_act == Act.PROOFREADING.value
