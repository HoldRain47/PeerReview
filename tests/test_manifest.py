"""자료 목록 시험. 네트워크 없이 가상 파일로만 한다."""

import json

from peerreview import main
from peerreview.ingest import file_sha256
from peerreview.manifest import (
    ManifestEntry,
    allocate_quotas,
    assign_subfields,
    check_manifest,
    load_manifest,
    save_manifest,
    stratified_queues,
)


def _entry(tmp_path, doc_id="PMC1", **kw):
    f = tmp_path / "xml" / f"{doc_id}.xml"
    f.parent.mkdir(exist_ok=True)
    f.write_text("<article><body/></article>", encoding="utf-8")
    base = {
        "doc_id": doc_id,
        "bundle_id": f"b-{doc_id}",
        "source": "europepmc",
        "license": "cc by",
        "pub_year": 2019,
        "journal": "Membranes",
        "path": f"xml/{doc_id}.xml",
        "sha256": file_sha256(f),
    }
    base.update(kw)
    return ManifestEntry(**base)


def test_valid_manifest_round_trip(tmp_path):
    entries = [_entry(tmp_path, "PMC1"), _entry(tmp_path, "PMC2", pub_year=2021)]
    m = tmp_path / "manifest.jsonl"
    save_manifest(m, entries)
    loaded, errors = load_manifest(m)
    assert errors == [] and len(loaded) == 2
    assert check_manifest(loaded, tmp_path) == []


def test_manifest_detects_problems(tmp_path):
    changed = _entry(tmp_path, "PMC3")
    (tmp_path / changed.path).write_text("changed", encoding="utf-8")
    entries = [
        changed,
        _entry(tmp_path, "PMC4", license="cc by-nc"),
        _entry(tmp_path, "PMC5", pub_year=2023),
        _entry(tmp_path, "PMC5"),
        _entry(tmp_path, "PMC6", path="xml/missing.xml"),
    ]
    errors = " / ".join(check_manifest(entries, tmp_path))
    for part in ("해시 불일치", "CC BY가 아님", "범위 밖", "doc_id 중복", "파일 없음"):
        assert part in errors


def test_variant_may_have_other_license_rules(tmp_path):
    # 변형본은 씨앗의 조건을 따르므로 씨앗 규칙(연도·이용 조건)을 다시 적용하지 않는다
    seed = _entry(tmp_path, "PMC7")
    v = _entry(
        tmp_path,
        "PMC7-v1",
        bundle_id="b-PMC7",
        role="variant",
        pub_year=2026,
        truth_basis="A",
    )
    assert check_manifest([seed, v], tmp_path) == []


def test_assign_subfields():
    subs = assign_subfields(
        "Catalytic membrane reactor for esterification",
        "Kinetics and mass transfer were modelled.",
    )
    assert {"catalysis", "separation", "reaction_engineering", "transport"} <= set(subs)
    assert assign_subfields("A history of chemistry", "") == []


def test_check_manifest_cli(tmp_path, capsys):
    m = tmp_path / "manifest.jsonl"
    save_manifest(m, [_entry(tmp_path, "PMC1")])
    assert main(["check-manifest", str(m), "--root", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["entries"] == 1 and out["errors"] == 0


def test_role_and_variant_bundle_rules(tmp_path):
    seed = _entry(tmp_path, "PMC10")
    good_variant = _entry(
        tmp_path, "PMC10-v1", bundle_id="b-PMC10", role="variant", truth_basis="A"
    )
    orphan = _entry(
        tmp_path, "PMC11-v1", bundle_id="b-PMC11", role="variant", truth_basis="A"
    )
    typo = _entry(tmp_path, "PMC12", role="sead")
    nc_analysis = _entry(tmp_path, "PMC13", role="analysis", license="cc by-nc")
    nd_analysis = _entry(tmp_path, "PMC14", role="analysis", license="cc by-nc-nd")
    errors = check_manifest(
        [seed, good_variant, orphan, typo, nc_analysis, nd_analysis], tmp_path
    )
    joined = " / ".join(errors)
    assert "PMC11-v1: 변형본의 bundle_id" in joined
    assert "PMC12: role 값" in joined
    assert "PMC14: 분석용" in joined
    assert not any(e.startswith(("PMC10", "PMC13")) for e in errors)


def test_allocate_quotas_sums_exactly():
    sizes = {
        (j, y): s
        for j, y, s in [
            ("A", 2017, 3),
            ("A", 2018, 50),
            ("B", 2018, 47),
            ("C", 2021, 1),
        ]
    }
    for n in (1, 7, 10, 33, 100, 101, 500):
        q = allocate_quotas(sizes, n)
        assert sum(q.values()) == min(n, 101)
        assert all(q[k] <= sizes[k] for k in sizes)


def test_stratified_queues_ignore_input_order():
    rows = [
        {"pmcid": f"PMC{i}", "journal": "A" if i % 2 else "B", "pub_year": 2019}
        for i in range(20)
    ]
    a = stratified_queues(rows, ("journal", "pub_year"), 7)
    b = stratified_queues(list(reversed(rows)), ("journal", "pub_year"), 7)
    assert a == b
