"""입력 처리 시험. 실제 원고 대신 시험 안에서 만든 가상 문서만 쓴다."""

import json

from peerreview import ingest, main
from peerreview.ingest import (
    FORMULA_PLACEHOLDER,
    SegmentKind,
    _is_equation_line,
    _is_figure_text,
    _paragraphs,
    _repair_glyphs,
    _running_lines,
    _strip_line_numbers,
    inspect,
    load,
    resolve_jats,
    source_text,
    summarize,
)
from peerreview.model import ProcessingStatus

FILLER = "The membrane was tested in a reactor and the flux of water was measured at each step. "

JATS = f"""<?xml version="1.0" encoding="UTF-8"?>
<article xmlns:mml="http://www.w3.org/1998/Math/MathML">
<front><article-meta>
<abstract abstract-type="graphical"><p>Graphical abstract text.</p></abstract>
<abstract><p>We report a membrane process for CO<sub>2</sub> capture.</p></abstract>
</article-meta></front>
<body>
<sec><title>1. Introduction</title>
<p>{FILLER * 30}The rate is <inline-formula><mml:math><mml:mi>k</mml:mi></mml:math></inline-formula> here.</p>
<disp-formula id="e1"><mml:math><mml:mi>J</mml:mi></mml:math></disp-formula>
<table-wrap><caption><p>Table 1 Data</p></caption><table><tr><td>1.0</td></tr></table></table-wrap>
<fig><caption><p>Fig. 1 Scheme of the setup.</p></caption></fig>
</sec>
</body>
<back><ref-list><ref>Smith J. Membranes 2020.</ref></ref-list></back>
</article>
"""


def _write_pdf(path, pages):
    """글자만 있는 최소 PDF를 만든다(Helvetica, 쪽마다 여러 줄)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None]
    kids = []
    for lines in pages:
        stream = (
            "BT /F1 10 Tf 50 750 Td 12 TL "
            + " ".join(
                "(" + ln.replace("(", r"\(").replace(")", r"\)") + ") '" for ln in lines
            )
            + " ET"
        )
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        content_id = len(objs)
        objs.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R /Resources << /Font << /F1 FONT 0 R >> >> >>"
        )
        kids.append(len(objs))
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_id = len(objs)
    objs[1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    )
    objs = [o.replace("FONT", str(font_id)) for o in objs]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)


def test_jats_kinds_and_exclusions(tmp_path):
    p = tmp_path / "paper.xml"
    p.write_text(JATS, encoding="utf-8")
    doc = load(p)
    kinds = {s.kind for s in doc.segments}
    assert {SegmentKind.BODY, SegmentKind.HEADING, SegmentKind.FORMULA} <= kinds
    assert {SegmentKind.TABLE, SegmentKind.CAPTION, SegmentKind.REFERENCE} <= kinds
    body = doc.text()
    assert "Graphical abstract" not in body  # 그래픽 초록 제외
    assert "CO2 capture" in body  # 아래첨자는 글자로 이어 붙인다
    assert FORMULA_PLACEHOLDER in body  # 문단 안 수식은 자리표시자
    assert (
        "Smith" not in body and "Fig. 1" not in body
    )  # 참고문헌·그림 설명은 본문이 아님
    assert doc.status == ProcessingStatus.COMPLETED


def test_pdf_korean_filename_headers_and_references(tmp_path):
    header = "Membranes 2021, 11, 175"
    pages = [
        [
            header,
            *(f"Page {n} line {k}: {FILLER.strip()}" for k in range(8)),
            f"{n} of 4",
        ]
        for n in range(1, 4)
    ] + [[header, "References", "1. Smith J. Membranes 2020.", "4 of 4"]]
    p = tmp_path / "한글 논문.pdf"
    _write_pdf(p, pages)
    doc = load(p, "pypdf")
    assert doc.pages_total == 4
    assert header not in doc.text()  # 반복 머리글 제외
    assert "Smith" not in doc.text()
    assert "Smith" in doc.text(SegmentKind.REFERENCE)
    assert doc.status == ProcessingStatus.COMPLETED


def test_status_too_short_out_of_scope_failed(tmp_path):
    short = tmp_path / "short.xml"
    short.write_text(JATS.replace(FILLER * 30, ""), encoding="utf-8")
    assert load(short).status == ProcessingStatus.TOO_SHORT

    # 한국어 본문에 영어 단어(참고문헌 등)가 섞여도 범위 밖으로 걸러야 한다
    korean = tmp_path / "ko.xml"
    korean.write_text(
        JATS.replace(
            FILLER * 30, "막을 반응기에서 시험했고 물의 투과량을 측정했다. " * 200
        ),
        encoding="utf-8",
    )
    assert load(korean).status == ProcessingStatus.OUT_OF_SCOPE

    bad_xml = tmp_path / "bad.xml"
    bad_xml.write_text("<article><body>", encoding="utf-8")
    assert load(bad_xml).status == ProcessingStatus.EXTRACTION_FAILED

    empty = tmp_path / "empty.pdf"
    _write_pdf(empty, [[""]])
    assert load(empty, "pypdf").status == ProcessingStatus.EXTRACTION_FAILED

    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    assert load(broken, "pypdf").status == ProcessingStatus.EXTRACTION_FAILED

    other = tmp_path / "paper.docx"
    other.write_bytes(b"PK")
    assert load(other).status == ProcessingStatus.OUT_OF_SCOPE


def _fake_pages(monkeypatch, pages):
    monkeypatch.setattr(ingest, "_pdf_pages", lambda path, engine: pages)


def test_partial_when_a_page_fails(tmp_path, monkeypatch):
    good = "\n".join(f"Line {k}: {FILLER.strip()}" for k in range(20))
    _fake_pages(monkeypatch, [good, None, good])
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.4")
    doc = load(p)
    assert doc.status == ProcessingStatus.PARTIAL
    assert doc.pages_failed == [2]


def test_pdf_location_maps_back_to_raw_lines(tmp_path, monkeypatch):
    fi = chr(0xE103)  # RSC 글꼴에서 fi가 이 문자로 나온다
    page = "\n".join(
        [f"The modi {fi}cation of the surface was con {fi}rmed by FTIR."]
        + [f"Line {k}: {FILLER.strip()}" for k in range(30)]
    )
    _fake_pages(monkeypatch, [page])
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.4")
    doc = load(p)
    seg = next(s for s in doc.segments if "modification" in s.text)
    assert "confirmed" in seg.text  # 분석용 사본은 복구됨
    raw = source_text(doc, seg)
    assert raw is not None and fi in raw  # 원문 위치로 돌아가면 깨진 글자 그대로
    assert seg.loc.startswith("p1:L0-")


def test_jats_location_resolves(tmp_path):
    p = tmp_path / "paper.xml"
    p.write_text(JATS, encoding="utf-8")
    doc = load(p)
    for seg in doc.segments:
        el = resolve_jats(p, seg.loc)
        assert el is not None, seg.loc
    first_body = next(
        s
        for s in doc.segments
        if s.section == "1. Introduction" and s.kind == SegmentKind.BODY
    )
    assert first_body.loc == "body[1]/sec[1]/p[1]"


def test_paragraphs_hyphen_caption_and_sentence_breaks():
    lines = [
        "The adsorp-",
        "tion was fast.",
        "Fig. 2 shows the flux.",
        "Fig. 3 SEM images of the membrane.",
        "Next sentence",
        "continues here.",
    ]
    paras = _paragraphs(list(enumerate(lines)))
    assert paras[0] == ("The adsorption was fast.", 0, 1)
    assert paras[1][0] == "Fig. 2 shows the flux."  # 본문 문장(소문자 동사)
    assert paras[2][0].startswith("Fig. 3 SEM")
    assert paras[3] == ("Next sentence continues here.", 4, 5)


def test_repair_glyphs_only_when_signature_present():
    fi = chr(0xE103)
    text, n = _repair_glyphs(f"con {fi}rming at 3440 cm /C0 1")
    assert text == "confirming at 3440 cm \u2212 1" and n == 2
    clean = "A normal sentence with \u00bc cup."
    assert _repair_glyphs(clean) == (clean, 0)


def test_repeated_body_line_is_kept(tmp_path):
    # 쪽 가운데에 같은 문장이 반복돼도 머리글로 보고 지우지 않는다
    same = "The same sentence appears in the middle of every page here."
    pages = [["Head", f"Intro {n}.", same, same, f"End {n}.", "Foot"] for n in range(4)]
    p = tmp_path / "rep.pdf"
    _write_pdf(p, pages)
    assert load(p, "pypdf").text().count(same) >= 4


def test_review_manuscript_line_numbers_removed(tmp_path):
    pages = [
        [f"{n * 20 + k + 1} Line {k} of page {n}: {FILLER.strip()}" for k in range(20)]
        for n in range(3)
    ]
    p = tmp_path / "manuscript.pdf"
    _write_pdf(p, pages)
    doc = load(p, "pypdf")
    assert "줄 번호" in " ".join(doc.issues)
    assert not any(s.text[:1].isdigit() for s in doc.segments)
    assert doc.status == ProcessingStatus.COMPLETED


def test_numbered_references_and_tables_are_not_line_numbers():
    refs = []
    for k in range(1, 8):
        refs += [f"{k} A. Author, B. Author, J. Membr. Sci., 2019,", "512, 100-110."]
    assert _strip_line_numbers(refs) == (refs, False)
    table = [
        f"{v} 0.{v} 1.{v}" for v in (25, 50, 75, 100, 150, 200, 250, 300, 350, 400)
    ]
    assert _strip_line_numbers(table) == (table, False)


def test_page_numbers_removed_but_numeric_rows_kept(tmp_path):
    pages = [
        [
            f"Body text on page {n} about the reactor design and flux.",
            "Results were stable.",
            "42",
            str(n + 1),
        ]
        for n in range(4)
    ]
    p = tmp_path / "pn.pdf"
    _write_pdf(p, pages)
    doc = load(p, "pypdf")
    body = doc.text()
    assert "42" in body  # 쪽 번호 규칙(쪽 순서 + 상수)에 맞지 않는 숫자 줄은 남긴다
    assert not any(s.text == "2" for s in doc.segments)


def test_running_lines_need_repetition():
    pages = [
        ["Journal 2021, 11, 1", "text a", "1 of 3"],
        ["Journal 2021, 11, 2", "text b", "2 of 3"],
    ]
    assert _running_lines(pages) == set()  # 3쪽 미만이면 판단하지 않는다


def test_summary_and_cli_never_print_text(tmp_path, capsys):
    p = tmp_path / "paper.xml"
    p.write_text(JATS, encoding="utf-8")
    doc = load(p)
    dumped = json.dumps(summarize(doc), ensure_ascii=False)
    for s in doc.segments:
        if len(s.text) > 20:
            assert s.text not in dumped
    out_path = tmp_path / "segments.json"
    assert main(["ingest", str(p), "--out", str(out_path)]) == 0
    printed = capsys.readouterr().out
    assert "membrane process" not in printed
    assert "membrane process" in out_path.read_text(encoding="utf-8")


def test_cli_refuses_to_overwrite_input(tmp_path):
    p = tmp_path / "paper.xml"
    p.write_text(JATS, encoding="utf-8")
    assert main(["ingest", str(p), "--out", str(p)]) == 2
    assert p.read_text(encoding="utf-8") == JATS


def test_figure_text_equations_and_broken_glyphs(tmp_path, monkeypatch):
    box = chr(0xF061)  # 수식 글꼴에서 글자로 바뀌지 않은 문자
    page = "\n".join(
        [f"Line {k}: {FILLER.strip()}" for k in range(25)]
        + [
            "",
            "2.6 2.8 3.0 3.2 3.4 2.3298 2.3320 Photon Energy (eV) (a) E0= 2.32 eV",
            "",
            f"FWHM (T) = G0 + {box}T + b (7) where G0 represents the broadening at 0 K.",
            "TABLE 2. Fitted parameters of the model",
            "",
            "Results agree with the model in the whole range of temperature.",
        ]
    )
    _fake_pages(monkeypatch, [page])
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.4")
    doc = load(p)
    kinds = {s.text[:12]: s.kind for s in doc.segments}
    assert kinds["2.6 2.8 3.0 "] == SegmentKind.FIGURE_TEXT
    assert kinds["FWHM (T) = G"] == SegmentKind.FORMULA
    assert kinds["where G0 rep"] == SegmentKind.BODY  # 수식 뒤 설명은 본문으로 남긴다
    assert kinds["TABLE 2. Fit"] == SegmentKind.TABLE  # 대문자 표 제목
    assert any("글자로 바뀌지 않은 문자 1개" in i for i in doc.issues)


def test_body_lines_with_equals_or_numbers_stay_body():
    # 검증에서 지적된 회귀 사례: 등호·식 번호·숫자가 있어도 문장이면 본문이다
    lines = [
        "The rate constant was then obtained from the fitted slope of the line.",
        "Substituting k = 0.12 s\u22121 into eqn (2)",
        "gives the half-life, consistent with values (Tg = 105 \u00b0C, Tm = 230 \u00b0C) reported earlier (12)",
        "for similar polymers.",
    ]
    paras = _paragraphs(list(enumerate(lines)))
    assert len(paras) == 2 and paras[1][0].startswith("Substituting")
    assert not any(_is_equation_line(x) for x in lines)
    assert _is_equation_line("FWHM (T) = G0 + aT + b exp(c/kT) (7)")
    assert not _is_figure_text("IR (KBr): 1720, 1650, 1600 cm\u22121.")
    assert not _is_figure_text(
        "The yields were 85, 90 and 92% at 300, 350 and 400 K, respectively."
    )
    assert _is_figure_text("2.6 2.8 3.0 3.2 3.4 Photon Energy (eV) (a) E0= 2.32 eV")


def test_inspect_reports_numbers_only(tmp_path, capsys):
    p = tmp_path / "paper.xml"
    p.write_text(JATS, encoding="utf-8")
    assert main(["inspect", str(p)]) == 0
    printed = capsys.readouterr().out
    data = json.loads(printed)
    assert data["status"] == "completed"
    assert set(data["body_paragraph_words"]) == {
        "<10",
        "10-29",
        "30-79",
        "80-199",
        "200+",
    }
    assert "membrane" not in printed.lower()


def test_headings_front_and_back_matter(tmp_path, monkeypatch):
    body = [
        f"Sentence {k} explains how the membrane was tested in the reactor."
        for k in range(30)
    ]
    page1 = "\n".join(
        [
            "Journal of Membranes Article",
            "University of Testing, Department of Chemical Engineering",
            "Keywords: membrane; distillation; lithium",
            "1. Introduction",
            *body[:15],
            "",
            "2.1 Materials",
            *body[15:],
            "",
            "4. To increase the attractiveness of the brines as an alternative",
            "source, the process must be cheaper.",
            "",
            "Acknowledgments",
            "We thank the laboratory staff for their help with the experiments.",
            "Conflicts of Interest: The authors declare no conflict of interest.",
            "References",
            "1. Smith J. Membranes 2020.",
        ]
    )
    _fake_pages(monkeypatch, [page1])
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.4")
    doc = load(p)
    by_start = {s.text[:20]: s.kind for s in doc.segments}
    assert by_start["1. Introduction"] == SegmentKind.HEADING
    assert by_start["2.1 Materials"] == SegmentKind.HEADING
    assert by_start["Journal of Membranes"] == SegmentKind.FRONT_MATTER
    # 번호 목록 항목 첫 줄은 다음 줄이 소문자로 이어지므로 제목이 아니다
    assert by_start["4. To increase the a"] == SegmentKind.BODY
    assert by_start["We thank the laborat"] == SegmentKind.BACK_MATTER
    assert by_start["Conflicts of Interes"] == SegmentKind.BACK_MATTER
    assert "laboratory staff" not in doc.text()


def test_jats_back_matter_sections(tmp_path):
    xml = JATS.replace(
        "</body>",
        "<sec><title>Author Contributions</title><p>A.B. wrote the paper.</p></sec>"
        '<sec sec-type="glossary"><title>Symbols</title><p>J flux of water</p></sec></body>',
    )
    p = tmp_path / "paper.xml"
    p.write_text(xml, encoding="utf-8")
    doc = load(p)
    assert "wrote the paper" in doc.text(SegmentKind.BACK_MATTER)
    assert "flux of water" in doc.text(SegmentKind.BACK_MATTER)
    assert "wrote the paper" not in doc.text()


def test_inspect_equation_diagnostics(tmp_path, monkeypatch):
    lines = [f"Line {k}: {FILLER.strip()}" for k in range(25)]
    lines += ["", "The flux follows J = k (C1 - C2) as written in eqn (3)", ""]
    _fake_pages(monkeypatch, ["\n".join(lines)])
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.4")
    data = inspect(load(p))
    assert data["body_equation_like"] == 1
    assert data["body_equation_like_with_words"] == 1
    assert data["body_equation_like_with_broken_glyphs"] == 0


def test_body_sentences_are_not_markers(tmp_path, monkeypatch):
    # 검증에서 지적된 경우: 표지처럼 시작하는 본문 문장, 숫자로 시작하는 본문 줄, 표 행
    body = [
        f"Sentence {k} explains how the membrane was tested in the reactor."
        for k in range(20)
    ]
    page = "\n".join(
        [
            "Introduction of a catalyst increased the conversion of the feed in all runs.",
            *body[:10],
            "Funding agencies increasingly require that the data are shared openly.",
            "3 Results were obtained at 25 \u00b0C for all samples.",
            "2 Ethanol 78 79",
            *body[10:],
            "References",
            "1. Smith J. Membranes 2020.",
        ]
    )
    _fake_pages(monkeypatch, [page])
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.4")
    doc = load(p)
    text = doc.text()
    assert "Introduction of a catalyst" in text  # 서론 표지로 오인해 앞을 자르지 않는다
    assert "Funding agencies" in text  # 뒷부분 표지로 오인하지 않는다
    assert "Sentence 19" in text  # 그 뒤 본문도 남는다
    assert not any(
        s.kind == SegmentKind.HEADING and s.text.startswith(("3 Results", "2 Ethanol"))
        for s in doc.segments
    )
    assert not doc.text(SegmentKind.BACK_MATTER)


def test_other_latin_languages_out_of_scope(tmp_path):
    fr = "La membrane a été testée dans le réacteur et le flux d'eau a été mesuré à chaque étape. "
    p = tmp_path / "fr.xml"
    p.write_text(JATS.replace(FILLER * 30, fr * 60), encoding="utf-8")
    assert load(p).status == ProcessingStatus.OUT_OF_SCOPE


def test_low_accent_language_and_mixed_document_out_of_scope(tmp_path):
    it = (
        "La membrana è stata provata nel reattore e il flusso di acqua è stato misurato in ogni passo. "
        "I risultati mostrano che la selettività aumenta con la temperatura e con il tempo di contatto. "
    )
    en = "The membrane was tested in the reactor and the water flux was measured at each step. "
    de = "Die Membran wurde im Reaktor getestet und der Fluss des Wassers wurde gemessen. "
    for name, body in (("it", it * 40), ("de", de * 60), ("mixed", en * 30 + it * 50)):
        p = tmp_path / f"{name}.xml"
        p.write_text(JATS.replace(FILLER * 30, body), encoding="utf-8")
        assert load(p).status == ProcessingStatus.OUT_OF_SCOPE, name


def test_format_traces_patterns():
    from peerreview.ingest import format_traces

    assert format_traces("CO₂ uptake of 3 mmol g⁻¹ at 25 °C") == {"unicode_subsup": 3}
    assert format_traces("The flux of $CO_2$ and H_{2}O with \\mathrm{K}") == {
        "latex": 3
    }
    assert format_traces("H<sub>2</sub>O and CO~2~") == {"markup": 3}
    # 사람이 쓴 평문, 달러 금액, 서식 없는 화학식은 흔적이 아니다
    assert (
        format_traces("The plant cost $5 million and emitted CO2 at 2.5 t per day.")
        == {}
    )


def test_traces_survive_pdf_normalization_and_count_once(tmp_path, monkeypatch):
    page = "\n".join(
        [f"Line {k}: {FILLER.strip()}" for k in range(25)]
        + ["", "The CO₂ capture capacity reached 4.2 mmol g⁻¹ in the test.", ""]
        + ["FWHM (T) = G0 + aT (7) where the CO₂ term dominates at high T."]
    )
    _fake_pages(monkeypatch, [page])
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.4")
    doc = load(p)
    seg = next(s for s in doc.segments if "capture capacity" in s.text)
    assert "CO2" in seg.text  # 분석용 글자는 NFKC로 정규화된다
    assert seg.traces == {
        "unicode_subsup": 3
    }  # 흔적은 정규화 전 글자에서 센다(₂, ⁻, ¹)
    total = summarize(doc)["format_traces"]
    assert total == {"unicode_subsup": 4}  # 수식·설명으로 나뉜 줄의 ₂는 한 번만 센다


def test_jats_traces_and_inspect_counts(tmp_path):
    xml = JATS.replace("capture.</p>", "capture with CO₂ at 2 bar.</p>")
    p = tmp_path / "paper.xml"
    p.write_text(xml, encoding="utf-8")
    data = inspect(load(p))
    assert data["format_traces_body"] == {"unicode_subsup": 1}
    assert data["body_paragraphs_with_traces"] == 1
