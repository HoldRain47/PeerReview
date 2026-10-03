"""PDF 추출 엔진 비교 (T002.2).

같은 논문의 JATS XML 본문을 기준으로, PDF 엔진이 뽑은 본문이 얼마나 같은지 잰다.
공개 논문 전용이다. 사용법: uv run python scripts/compare_extraction.py <pdf폴더> <xml폴더>
결과는 표로 출력한다. 원문은 출력하지 않는다.
"""

import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

from peerreview.ingest import (
    FORMULA_PLACEHOLDER,
    PDF_ENGINES,
    SegmentKind,
    load_jats,
    load_pdf,
)

_TOKEN = re.compile(r"[A-Za-z0-9]+")
# 화학식 비슷한 토큰: 대문자로 시작하고 숫자를 포함 (CO2, Fe3O4, H2O)
_CHEM = re.compile(r"^[A-Z][A-Za-z]*\d[A-Za-z0-9]*$")
_LIGATURE = re.compile("[ﬀ-ﬆ]")


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text.replace(FORMULA_PLACEHOLDER, " "))]


def compare(xml_path: Path, pdf_path: Path, engine: str) -> dict:
    ref = load_jats(xml_path)
    t0 = time.perf_counter()
    doc = load_pdf(pdf_path, engine)
    elapsed = time.perf_counter() - t0

    ref_tokens = tokens(ref.text(SegmentKind.BODY))
    body = doc.text(SegmentKind.BODY)
    pdf_tokens = tokens(body)
    sm = SequenceMatcher(None, ref_tokens, pdf_tokens, autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    # 순서대로 이어진 긴 덩어리(20토큰 이상)로 맞은 비율: 읽기 순서가 맞는지 본다
    long_matched = sum(b.size for b in sm.get_matching_blocks() if b.size >= 20)

    ref_chem = {t for t in _TOKEN.findall(ref.text()) if _CHEM.match(t)}
    pdf_all = set(_TOKEN.findall(doc.text() + doc.text(SegmentKind.REFERENCE)))
    ref_refs = ref.text(SegmentKind.REFERENCE)
    ref_tail = tokens(ref_refs)
    # PDF 본문에 참고문헌이 섞였는지: 기준 참고문헌 토큰이 본문으로 들어간 비율
    leak = 0.0
    if ref_tail:
        sm2 = SequenceMatcher(None, ref_tail, pdf_tokens, autojunk=False)
        leak = sum(b.size for b in sm2.get_matching_blocks() if b.size >= 8) / len(
            ref_tail
        )

    return {
        "engine": engine,
        "status": doc.status.value,
        "recall": matched / max(len(ref_tokens), 1),
        "precision": matched / max(len(pdf_tokens), 1),
        "order": long_matched / max(len(ref_tokens), 1),
        "chem": len(ref_chem & pdf_all) / max(len(ref_chem), 1),
        "ref_leak": leak,
        "ligatures": len(_LIGATURE.findall(body)),
        "seconds": elapsed,
        "issues": len(doc.issues),
    }


def main() -> None:
    pdf_dir, xml_dir = Path(sys.argv[1]), Path(sys.argv[2])
    cols = ["recall", "precision", "order", "chem", "ref_leak"]
    print("| 논문 | 엔진 | 상태 | " + " | ".join(cols) + " | 합자 | 초 |")
    print("|---" * (len(cols) + 5) + "|")
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        xml = xml_dir / f"{pdf.stem}.xml"
        for engine in PDF_ENGINES:
            r = compare(xml, pdf, engine)
            vals = " | ".join(f"{r[c]:.3f}" for c in cols)
            print(
                f"| {pdf.stem} | {engine} | {r['status']} | {vals}"
                f" | {r['ligatures']} | {r['seconds']:.1f} |"
            )


if __name__ == "__main__":
    main()
