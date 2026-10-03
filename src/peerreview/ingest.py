"""입력 처리: 논문 파일에서 위치 정보가 붙은 구간 목록과 처리 상태를 만든다.

근거: 개발 보고서 v2.0 4절(원본 보존, 추출 품질 확인, 구간 구분).
원본 파일은 읽기만 한다. 요약(`summarize`)에는 원문을 넣지 않는다.
비공개 원고에도 쓰이므로, 에이전트에게 전달할 출력은 요약뿐이어야 한다.

위치 대응: 구간마다 `loc`을 남긴다. PDF는 `p<쪽>:L<시작>-<끝>`으로, 추출기가 낸 정규화 전
쪽 글자의 줄 번호(0부터)를 가리킨다(`source_text`로 되찾는다). XML은 `body/sec[2]/p[3]` 같은
요소 경로다(`resolve_jats`로 되찾는다).
"""

from __future__ import annotations

import hashlib
import itertools
import logging
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from peerreview.model import ProcessingStatus

# 분량 부족 기준(본문 단어 수). 임시값이며 T003에서 길이별 결과를 보고 정한다(목표 정의서 6절).
MIN_BODY_WORDS = 300
# 영어 판별 임시값: 본문 낱말 중 흔한 영어 기능어 비율의 하한, 라틴 문자가 아닌 낱말 비율의 상한.
# 2026-10-04 보정(두 차례): 처음 값 0.15는 화합물 이름이 많은 영어 논문을 걸렀다. 공개 영어 논문 667편의
# 최솟값이 0.073이라, 다른 언어는 아래 "다른 언어 기능어" 검사로 거르고 이 값은 글자가 거의 없는
# 문서를 막는 안전장치로 0.04에 둔다. 독일어·스페인어 예문 0.000, 프랑스어 예문 0.069.
MIN_ENGLISH_STOPWORD_RATIO = 0.04
# 다른 언어에만 쓰이는 기능어 비율의 상한. 영어 667편 최대 0.025, 이탈리아어 예문 0.147,
# 프랑스어 예문 0.138, 영어 초록 + 이탈리아어 본문 0.115를 보고 0.05로 정했다(2026-10-04).
MAX_FOREIGN_FUNCTION_RATIO = 0.05
# 영어 화학 논문에도 나오는 말(La=란타넘, per, de Gennes 같은 이름)은 넣지 않는다.
_FOREIGN_FUNCTION_WORDS = frozenset(
    {"der", "die", "und", "nicht", "ist", "mit", "von", "sich", "das"}
    | {"les", "des", "une", "est", "sont", "dans", "pour", "avec"}
    | {"che", "della", "sono", "nella", "degli", "delle", "il", "di"}
    | {"los", "las", "del", "una", "para", "como", "por", "que", "el"}
)
MAX_NON_LATIN_RATIO = 0.3
FORMULA_PLACEHOLDER = "[FORMULA]"

_STOPWORDS = frozenset(
    {"the", "of", "and", "to", "in", "a", "is", "that", "for", "with", "as", "by", "on"}
    | {
        "are",
        "this",
        "was",
        "be",
        "from",
        "at",
        "an",
        "or",
        "which",
        "were",
        "it",
        "can",
    }
)
_REFERENCE_HEADING = re.compile(
    r"^\s*(\d+\.?\s*)?(references|bibliography|literature cited|참고\s*문헌)\s*$",
    re.IGNORECASE,
)
_WORD = re.compile(r"[A-Za-z][A-Za-z\-']*")
_LETTERS = re.compile(r"[^\W\d_]+")  # 모든 문자 체계의 낱말


class SegmentKind(StrEnum):
    """구간 종류. 판정 분석은 BODY만 쓰고 나머지는 미평가 영역으로 남긴다."""

    HEADING = "heading"
    BODY = "body"
    FORMULA = "formula"
    TABLE = "table"
    CAPTION = "caption"
    FIGURE_TEXT = "figure_text"  # 그림 안의 축 눈금·범례 등. PDF에서 문단처럼 뽑힌다
    BACK_MATTER = "back_matter"  # 감사의 글, 저자 기여, 이해 상충, 기호표 등
    FRONT_MATTER = "front_matter"  # 초록 앞의 학술지명·제목·저자·소속 등
    REFERENCE = "reference"


@dataclass
class Segment:
    kind: SegmentKind
    text: str  # 분석용으로 정규화한 글자
    order: int  # 문서 안 순서
    section: str = ""  # 소속 절 제목(XML) 또는 빈 값
    page: int | None = None  # 1부터. XML이면 None
    loc: str = ""  # 원문 위치(모듈 설명 참고)


@dataclass
class Document:
    path: Path
    sha256: str
    fmt: str  # "jats" | "pdf"
    engine: str
    segments: list[Segment] = field(default_factory=list)
    pages_total: int | None = None
    pages_failed: list[int] = field(default_factory=list)
    status: ProcessingStatus = ProcessingStatus.COMPLETED
    issues: list[str] = field(default_factory=list)
    # PDF 추출기가 낸 정규화 전 쪽별 줄. 위치 대응용이며 요약·저장에 넣지 않는다.
    raw_lines: list[list[str] | None] = field(default_factory=list, repr=False)

    def text(self, kind: SegmentKind = SegmentKind.BODY) -> str:
        return "\n\n".join(s.text for s in self.segments if s.kind == kind)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def words(text: str) -> list[str]:
    """영어 낱말. 수식 자리표시자는 세지 않는다."""
    return _WORD.findall(text.replace(FORMULA_PLACEHOLDER, " "))


# ---------------------------------------------------------------- JATS XML


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _jats_text(el: ET.Element) -> str:
    """요소의 글자를 모은다. 수식은 자리표시자로 바꾸고, 각주 번호 같은 xref도 그대로 둔다."""
    parts: list[str] = []

    def walk(e: ET.Element) -> None:
        name = _local(e.tag)
        if name in ("inline-formula", "disp-formula", "math"):
            parts.append(f" {FORMULA_PLACEHOLDER} ")
        elif name in ("table-wrap", "fig", "list") and e is not el:
            pass  # 문단 안의 표·그림·목록은 따로 구간으로 만든다
        else:
            if e.text:
                parts.append(e.text)
            for c in e:
                walk(c)
        if e is not el and e.tail:
            parts.append(e.tail)

    walk(el)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _child_paths(parent: ET.Element, parent_path: str) -> list[tuple[ET.Element, str]]:
    """자식마다 `이름[같은 이름 중 순번]` 경로를 붙인다(순번은 1부터)."""
    seen: Counter[str] = Counter()
    out = []
    for c in parent:
        name = _local(c.tag)
        seen[name] += 1
        prefix = f"{parent_path}/" if parent_path else ""
        out.append((c, f"{prefix}{name}[{seen[name]}]"))
    return out


def resolve_jats(xml_path: Path, loc: str) -> ET.Element | None:
    """`loc` 경로가 가리키는 XML 요소를 되찾는다."""
    el: ET.Element | None = ET.parse(xml_path).getroot()
    for step in loc.split("/"):
        m = re.fullmatch(r"([\w-]+)\[(\d+)\]", step)
        if el is None or not m:
            return None
        same = [c for c in el if _local(c.tag) == m.group(1)]
        idx = int(m.group(2)) - 1
        el = same[idx] if idx < len(same) else None
    return el


def load_jats(path: Path) -> Document:
    doc = Document(path=path, sha256=file_sha256(path), fmt="jats", engine="xml")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        doc.issues.append(f"XML을 읽지 못함: 줄 {e.position[0]}")
        doc.status = ProcessingStatus.EXTRACTION_FAILED
        return doc

    def add(kind: SegmentKind, text: str, section: str, loc: str) -> None:
        if text:
            doc.segments.append(
                Segment(kind, text, len(doc.segments), section, loc=loc)
            )

    def add_inner(el: ET.Element, loc: str, section: str) -> None:
        """문단 안에 들어 있는 표·그림·목록을 따로 구간으로 만든다."""
        for c, cpath in _child_paths(el, loc):
            name = _local(c.tag)
            if name == "table-wrap":
                add(SegmentKind.TABLE, _jats_text(c), section, cpath)
            elif name == "fig":
                add(SegmentKind.CAPTION, _jats_text(c), section, cpath)
            elif name == "list":
                for li, lpath in _child_paths(c, cpath):
                    if _local(li.tag) == "list-item":
                        add(SegmentKind.BODY, _jats_text(li), section, lpath)
            else:
                add_inner(c, cpath, section)

    def walk_sec(
        sec: ET.Element, sec_path: str, title: str, back: bool = False
    ) -> None:
        """`back`이면 이 절의 본문을 BACK_MATTER로 둔다(감사의 글, 저자 기여, 기호표 등)."""
        body_kind = SegmentKind.BACK_MATTER if back else SegmentKind.BODY
        for c, cpath in _child_paths(sec, sec_path):
            name = _local(c.tag)
            if name == "title":
                title = _jats_text(c)
                add(SegmentKind.HEADING, title, title, cpath)
                if _is_named_heading(title) and _BACK_MATTER.search(title):
                    body_kind = SegmentKind.BACK_MATTER
            elif name in ("p", "disp-quote"):
                add(body_kind, _jats_text(c), title, cpath)
                add_inner(c, cpath, title)
            elif name in ("list", "def-list"):
                for li, lpath in _child_paths(c, cpath):
                    add(body_kind, _jats_text(li), title, lpath)
            elif name == "disp-formula":
                add(SegmentKind.FORMULA, FORMULA_PLACEHOLDER, title, cpath)
            elif name in ("table-wrap", "table-wrap-group"):
                add(SegmentKind.TABLE, _jats_text(c), title, cpath)
            elif name == "fig":
                add(SegmentKind.CAPTION, _jats_text(c), title, cpath)
            elif name == "ref-list":
                add_refs(c, cpath)
            elif name == "sec":
                is_back = body_kind == SegmentKind.BACK_MATTER
                walk_sec(
                    c, cpath, title, is_back or c.get("sec-type") in _BACK_SEC_TYPES
                )

    def add_refs(ref_list: ET.Element, loc: str) -> None:
        for r, rpath in _child_paths(ref_list, loc):
            if _local(r.tag) == "ref":
                add(SegmentKind.REFERENCE, _jats_text(r), "References", rpath)

    for el, path_ in _child_paths(root, ""):
        if _local(el.tag) == "front":
            for ab in el.iter("abstract"):
                if ab.get("abstract-type") not in (None, "", "abstract"):
                    continue  # 그래픽 초록 등
                for p in ab.iter("p"):
                    add(
                        SegmentKind.BODY,
                        _jats_text(p),
                        "Abstract",
                        _find_path(el, p, path_),
                    )
        elif _local(el.tag) == "body":
            walk_sec(el, path_, "")
        elif _local(el.tag) == "back":
            for c, cpath in _child_paths(el, path_):
                if _local(c.tag) == "ref-list":
                    add_refs(c, cpath)
    return assess(doc)


def _find_path(base: ET.Element, target: ET.Element, base_path: str) -> str:
    """`base` 아래에서 `target`까지의 요소 경로를 찾는다."""
    for c, cpath in _child_paths(base, base_path):
        if c is target:
            return cpath
        found = _find_path(c, target, cpath)
        if found:
            return found
    return ""


# ---------------------------------------------------------------- PDF

PDF_ENGINES = ("pypdf", "pdfplumber")
# pdfplumber가 같은 단어로 묶는 글자 간격(pt). 기본값 3은 양쪽 정렬 문단에서 띄어쓰기를 잃는다.
PDFPLUMBER_X_TOLERANCE = 1.5


def _pdf_pages(path: Path, engine: str) -> list[str | None]:
    """페이지별 글자. 실패한 페이지는 None. 파일 자체를 열지 못하면 예외를 낸다."""
    pages: list[str | None] = []
    if engine == "pypdf":
        from pypdf import PdfReader

        # 글꼴 경고(fontTools 권고 등)는 결과에 영향이 없고 화면만 어지럽힌다
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        reader = PdfReader(path)
        for idx in range(len(reader.pages)):
            try:
                pages.append(reader.pages[idx].extract_text() or "")
            except Exception:  # noqa: BLE001 - 페이지 하나의 실패를 기록하고 계속한다
                pages.append(None)
    elif engine == "pdfplumber":
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                try:
                    pages.append(
                        page.extract_text(x_tolerance=PDFPLUMBER_X_TOLERANCE) or ""
                    )
                except Exception:  # noqa: BLE001
                    pages.append(None)
    else:
        raise ValueError(f"알 수 없는 엔진: {engine}")
    return pages


# 그림·표 설명 시작 줄. "Fig. 1 FTIR …", "Figure 2. Schematic …", "Table 3 (a) …"
# 번호 뒤가 소문자면("Fig. 2 shows") 본문 문장이므로 제외한다.
_CAPTION = re.compile(
    r"^(Fig\.?|Figure|Scheme|Table|FIG\.?|FIGURE|SCHEME|TABLE)\s*(\d+|[IVX]+)[.:]?\s+[A-Z(]"
)
# 번호 붙은 수식 줄: 등호가 있고 "(7)"처럼 끝난다. 뒤에 "where …"가 같은 줄에 붙어 나오기도 한다.
_EQUATION = re.compile(r"=.*\(\d{1,3}[a-z]?\)\s*$")
# 절 제목 줄: "2.1 Materials", "3. Results and Discussion", "II. Methods"
_SECTION_HEADING = re.compile(
    r"^(\d{1,2}(\.\d{1,2}){0,3}\.?|[IVX]{1,4}\.)\s+[A-Z][^.!?]{0,80}$"
)
_NAMED_HEADING = re.compile(
    r"^(abstract|introduction|conclusions?|results(\s+and\s+discussion)?|discussion"
    r"|experimental(\s+section)?|materials\s+and\s+methods|methods|methodology|keywords?)\s*:?\s*$",
    re.IGNORECASE,
)
# 논문 뒷부분 표지. 이 표지 뒤의 본문은 참고문헌 전까지 BACK_MATTER로 둔다.
_BACK_MATTER = re.compile(
    r"^(acknowledge?ments?|author\s+contributions?|credit\s+authorship|funding"
    r"|conflicts?\s+of\s+interests?|declaration\s+of\s+competing\s+interests?"
    r"|competing\s+interests?|data\s+availability(\s+statement)?"
    r"|institutional\s+review\s+board\s+statement|informed\s+consent\s+statement"
    r"|nomenclature|abbreviations|supplementary\s+materials?|supporting\s+information"
    r"|footnotes|(research\s+|animal\s+)?ethics\s+statement|fieldwork\s+statement)\b",
    re.IGNORECASE,
)
# JATS에서 뒷부분으로 보는 절 종류
_BACK_SEC_TYPES = frozenset(
    {
        "glossary",
        "ack",
        "fn-group",
        "associated-data",
        "supplementary-materials",
        "COI-statement",
    }
)
_EQUATION_THEN_TEXT = re.compile(
    r"^(.*=.*?\(\d{1,3}[a-z]?\))\s+((?:where|in which|with|here)\b.*)$"
)
_NUMBER_TOKEN = re.compile(r"^[(\[]?[-−+]?\d[\d.,:/×%−-]*[)\]]?$")
# 출판사 전용 글꼴(예: RSC의 AdvOT 계열)에서 잘못 추출되는 글자. 시험한 PDF에서 확인한 것만 넣는다.
# 깨짐 흔적이 있는 문서에서는 진짜 ¼도 "="로 바뀌는 한계가 있다.
_LIGATURE_REPAIR = {"": "fi", "": "fl", "": "ft"}
_SYMBOL_REPAIR = {"/C0": "−", "/C14": "°", "¼": "="}  # 빼기, 도, 등호
_GLYPH_SIGNATURE = re.compile("[-]|/C0|/C14")


def _repair_glyphs(text: str) -> tuple[str, int]:
    """알려진 글꼴 깨짐을 고친다. 깨짐 흔적이 없는 문서는 건드리지 않는다. 줄 수는 바꾸지 않는다."""
    if not _GLYPH_SIGNATURE.search(text):
        return text, 0
    n = 0
    for bad, good in _LIGATURE_REPAIR.items():
        # 합자 앞뒤에 끼어든 띄어쓰기도 지운다: "con rming" -> "confirming"
        text, k = re.subn(rf"(?<=[A-Za-z]) ?{bad} ?(?=[a-z])", good, text)
        n += k + text.count(bad)
        text = text.replace(bad, good)
    for bad, good in _SYMBOL_REPAIR.items():
        n += text.count(bad)
        text = text.replace(bad, good)
    return text, n


_LINE_NUMBER = re.compile(r"^\s*(\d{1,4})\s+(?=\S)")


def _strip_line_numbers(lines: list[str]) -> tuple[list[str], bool]:
    """심사용 원고의 줄 번호를 지운다.

    쪽의 70% 이상이 숫자로 시작하고, 그 숫자가 대부분(80%) 1씩 늘어날 때만 줄 번호로 본다.
    번호 매긴 참고문헌(여러 줄 항목)이나 숫자 표는 이 조건을 만족하지 않는다.
    """
    filled = [x for x in lines if x.strip()]
    if len(filled) < 10:
        return lines, False
    nums = [int(m.group(1)) for x in filled if (m := _LINE_NUMBER.match(x))]
    if len(nums) < 0.7 * len(filled):
        return lines, False
    steps = sum(b - a == 1 for a, b in itertools.pairwise(nums))
    if steps < 0.8 * (len(nums) - 1):
        return lines, False
    return [_LINE_NUMBER.sub("", x) for x in lines], True


def _norm_line(line: str) -> str:
    """머리글·바닥글 비교용: 숫자와 공백을 지운다."""
    return re.sub(r"\s+", "", re.sub(r"\d", "", line)).lower()


def _edge(lines: list[str]) -> list[int]:
    """쪽의 맨 위·맨 아래 비어 있지 않은 줄 두 개씩의 위치."""
    filled = [j for j, x in enumerate(lines) if x.strip()]
    return sorted(set(filled[:2] + filled[-2:]))


def _running_lines(pages: list[list[str]]) -> set[str]:
    """여러 쪽 가장자리에 반복되는 줄(머리글·바닥글). 숫자만 있는 줄은 여기서 다루지 않는다."""
    if len(pages) < 3:
        return set()
    counts: Counter[str] = Counter()
    for lines in pages:
        counts.update({_norm_line(lines[j]) for j in _edge(lines)} - {""})
    return {k for k, n in counts.items() if n >= max(3, len(pages) // 2)}


def _page_number_offset(pages: list[tuple[int, list[str]]]) -> int | None:
    """가장자리의 숫자만 있는 줄이 '쪽 번호 = 쪽 순서 + 상수'를 3쪽 이상에서 따르면 그 상수."""
    offsets: Counter[int] = Counter()
    for i, lines in pages:
        for j in _edge(lines):
            if re.fullmatch(r"\s*\d{1,4}\s*", lines[j]):
                offsets[int(lines[j]) - i] += 1
    if not offsets:
        return None
    off, n = offsets.most_common(1)[0]
    return off if n >= 3 else None


def _paragraphs(lines: list[tuple[int, str]]) -> list[tuple[str, int, int]]:
    """(줄 위치, 줄) 목록을 문단 (글자, 시작 줄, 끝 줄)로 묶는다.

    빈 줄, 문장 끝 뒤 대문자로 시작하는 줄, 그림·표 설명 시작 줄을 경계로 본다. 줄 끝 하이픈은 잇는다.
    """
    out: list[tuple[str, int, int]] = []
    cur, start, end = "", -1, -1
    expanded: list[tuple[int, str]] = []
    for j, raw in lines:
        if m := _EQUATION_THEN_TEXT.match(raw.strip()):
            expanded += [(j, m.group(1)), (j, m.group(2))]
        else:
            expanded.append((j, raw))
    for idx, (j, raw) in enumerate(expanded):
        line = raw.strip()
        nxt = next((x.strip() for _, x in expanded[idx + 1 :] if x.strip()), "")
        # 절 제목은 다음 줄이 소문자로 이어지지 않을 때만 인정한다.
        # 번호 목록 항목의 첫 줄("4. To increase the …" 다음 줄 "source, …")을 제목으로 떼어 내지 않기 위해서다.
        # 이름 없는 번호 제목은 앞 줄이 문장 끝이거나 문단 시작일 때만 인정한다(남은 줄 번호 오인 방지).
        prev_ok = (
            not cur or bool(re.search(r"[.:?!;]$", cur)) or _is_named_heading(line)
        )
        heading = _is_heading_line(line) and not nxt[:1].islower() and prev_ok
        if _is_equation_line(line) or heading:
            # 수식 줄과 절 제목 줄은 혼자 한 구간이 된다
            if cur:
                out.append((cur, start, end))
            out.append((line, j, j))
            cur = ""
            continue
        if not line:
            if cur:
                out.append((cur, start, end))
            cur = ""
            continue
        sentence_end = re.search(r"[.:?!]$", cur) and re.match(r"[A-Z0-9(\[]", line)
        if cur and (_CAPTION.match(line) or sentence_end):
            out.append((cur, start, end))
            cur, start = line, j
        elif cur.endswith("-") and re.match(r"[a-z]", line):
            cur = cur[:-1] + line
        elif cur:
            cur = f"{cur} {line}"
        else:
            cur, start = line, j
        end = j
    if cur:
        out.append((cur, start, end))
    return out


def _add_paragraphs(
    doc: Document, lines: list[tuple[int, str]], kind: SegmentKind, page: int
) -> None:
    for para, start, end in _paragraphs(lines):
        k = kind
        if kind == SegmentKind.BODY:
            if m := _CAPTION.match(para):
                is_table = m.group(1).upper() == "TABLE"
                k = SegmentKind.TABLE if is_table else SegmentKind.CAPTION
            elif start == end and _is_equation_line(para):
                k = SegmentKind.FORMULA
            elif start == end and _is_heading_line(para):
                k = SegmentKind.HEADING
            elif _is_figure_text(para):
                k = SegmentKind.FIGURE_TEXT
        doc.segments.append(
            Segment(
                k, para, len(doc.segments), page=page, loc=f"p{page}:L{start}-{end}"
            )
        )


# 수식 안에 나올 수 있는 소문자 함수 이름
_MATH_WORDS = frozenset(
    {
        "exp",
        "sin",
        "cos",
        "tan",
        "log",
        "ln",
        "max",
        "min",
        "lim",
        "sinh",
        "cosh",
        "tanh",
    }
)


def _is_equation_line(line: str) -> bool:
    """번호 붙은 수식 줄인지 보수적으로 판정한다.

    등호가 있고 "(번호)"로 끝나며, 소문자가 든 4글자 이상 낱말(수학 함수 이름 제외)이 하나도 없어야 한다.
    "FWHM" 같은 대문자 약어는 낱말로 세지 않는다.
    "Substituting k = 0.12 s−1 into eqn (2)"처럼 낱말이 있는 줄은 본문으로 둔다.
    판단이 애매하면 본문에 남긴다(본문을 잃는 것보다 수식이 섞이는 편이 덜 해롭다).
    """
    if not _EQUATION.search(line):
        return False
    return not any(
        len(w) >= 4 and not w.isupper() and w.lower() not in _MATH_WORDS
        for w in words(line)
    )


_FINITE_VERB = re.compile(
    r"\b(is|are|was|were|has|have|had|be|been|can|could|may|will|would|shows?|showed)\b",
    re.IGNORECASE,
)
_TRAILING_FUNCTION_WORD = re.compile(
    r"\b(the|a|an|of|and|or|to|in|for|with|at|by|on|from)\s*$", re.IGNORECASE
)


def _is_named_heading(line: str) -> bool:
    """이름 있는 절 제목("Introduction", "1. Introduction")이나 뒷부분 표지만 있는 줄."""
    bare = re.sub(r"^(\d{1,2}(\.\d{1,2}){0,3}\.?|[IVX]{1,4}\.)\s+", "", line.strip())
    if _NAMED_HEADING.match(bare):
        return True
    return bool(_BACK_MATTER.fullmatch(bare.rstrip(" :"))) or (
        bool(_BACK_MATTER.match(bare))
        and len(words(bare)) <= 4
        and not re.search(r"[.;,]$", bare)
    )


def _is_heading_line(line: str) -> bool:
    """절 제목 줄인지 판정한다.

    이름 있는 제목은 그대로 인정한다. 번호 붙은 제목은 10단어 이하이고, 동사(were, is 등)가 없고,
    관사·전치사로 끝나지 않고, 번호 뒤에 숫자 토큰이 2개 이상 없어야 한다.
    "3 Results were obtained at 25 °C", 표 행 "2 Ethanol 78 79"를 제목으로 보지 않기 위해서다.
    """
    n = len(words(line))
    if n == 0:
        return False
    if _is_named_heading(line):
        return True
    if n > 10 or not _SECTION_HEADING.match(line):
        return False
    rest = line.split(None, 1)[1] if len(line.split(None, 1)) > 1 else ""
    numbers = sum(bool(_NUMBER_TOKEN.match(t)) for t in rest.split())
    return not (
        _FINITE_VERB.search(rest)
        or _TRAILING_FUNCTION_WORD.search(rest)
        or numbers >= 2
    )


def _mark_back_matter(doc: Document) -> int:
    """뒷부분 표지가 나온 뒤 참고문헌 전까지의 본문을 BACK_MATTER로 바꾼다. 바꾼 수를 돌려준다."""
    in_back, n = False, 0
    for seg in doc.segments:
        if seg.kind == SegmentKind.REFERENCE:
            break
        # 표지로 인정하는 것: 뒷부분 제목 줄("Acknowledgments")이나 "표지:" 형태의 문단("Funding: …").
        # "Funding agencies increasingly require …" 같은 본문 문장은 표지가 아니다.
        labeled = seg.kind == SegmentKind.BODY and bool(
            _BACK_MATTER_LABEL.match(seg.text)
        )
        if (
            seg.kind == SegmentKind.HEADING
            and _is_named_heading(seg.text)
            and _BACK_MATTER.search(seg.text)
        ) or labeled:
            in_back = True
        elif seg.kind == SegmentKind.HEADING:
            in_back = False  # 뒷부분이 아닌 제목이 나오면 본문으로 돌아간다
        if in_back and seg.kind == SegmentKind.BODY:
            seg.kind = SegmentKind.BACK_MATTER
            n += 1
    return n


# 앞부분이 끝나는 표지: 제목 줄 "Abstract"·"1. Introduction", 또는 "Abstract:"로 시작하는 문단
_ABSTRACT_LABEL = re.compile(r"^abstract\s*[:.\u2014\u2013-]", re.IGNORECASE)
# 뒷부분 "표지:" 형태 문단
_BACK_MATTER_LABEL = re.compile(_BACK_MATTER.pattern + r"[^:.]{0,40}:", re.IGNORECASE)


def _mark_front_matter(doc: Document) -> int:
    """초록·서론이 처음 3쪽 안에서 시작하면, 그 앞의 문장이 아닌 조각(제목·저자·소속)을 FRONT_MATTER로 바꾼다.

    초록·서론을 찾았으면 1 이상(바꾼 수 + 1), 못 찾으면 0을 돌려준다.
    """
    first = next(
        (
            k
            for k, seg in enumerate(doc.segments)
            if (seg.page or 0) <= 3
            and (
                (seg.kind == SegmentKind.HEADING and _is_named_heading(seg.text))
                or (seg.kind == SegmentKind.BODY and _ABSTRACT_LABEL.match(seg.text))
            )
        ),
        None,
    )
    if first is None:
        return 0
    n = 0
    for seg in doc.segments[:first]:
        if seg.kind != SegmentKind.BODY:
            continue
        # 표지 없는 초록(RSC처럼 제목·저자와 한 덩어리이거나, 문장별로 쪼개진 경우)을 잃지 않도록
        # 문장으로 보이는 구간(12단어 이상, 기능어 15% 이상, is·was 같은 동사 있음)은 본문에 남긴다.
        alpha = words(seg.text)
        stop = sum(w.lower() in _STOPWORDS for w in alpha) / max(len(alpha), 1)
        if len(alpha) >= 12 and stop >= 0.15 and _FINITE_VERB.search(seg.text):
            continue
        seg.kind = SegmentKind.FRONT_MATTER
        n += 1
    return n + 1


def _is_figure_text(para: str) -> bool:
    """그림 안 글자로 보이는 문단: 6토큰 이상, 문장 부호로 끝나지 않고, 숫자 토큰이 30% 이상이며 영어 기능어가 거의 없다."""
    toks = para.split()
    # 문장 부호로 끝나는 짧은 자료 줄("IR (KBr): 1720, 1650 cm−1.")은 본문으로 둔다
    if len(toks) < 6 or re.search(r"[.;]$", para):
        return False
    numeric = sum(bool(_NUMBER_TOKEN.match(t)) for t in toks) / len(toks)
    # "(a)" 같은 그림 패널 표시는 관사 a로 세지 않는다
    alpha = words(re.sub(r"\([a-z]\)", " ", para))
    stop = sum(w.lower() in _STOPWORDS for w in alpha) / max(len(alpha), 1)
    return numeric >= 0.3 and stop < 0.1


def broken_glyph_count(text: str) -> int:
    """글자로 바뀌지 않은 문자 수: 사용자 정의 영역, 미지정 문자, 대체 문자(�), □(U+25A1), 제어 문자(탭·줄바꿈·쪽 넘김 제외)."""
    n = 0
    for ch in text:
        cat = unicodedata.category(ch)
        if (
            cat in ("Co", "Cn", "Cs")
            or ch in "\ufffd\u25a1"
            or (cat == "Cc" and ch not in "\n\r\t\f")
        ):
            n += 1
    return n


def source_text(doc: Document, seg: Segment) -> str | None:
    """PDF 구간의 정규화 전 원문 줄을 되찾는다."""
    m = re.fullmatch(r"p(\d+):L(\d+)-(\d+)", seg.loc)
    if not m or doc.fmt != "pdf":
        return None
    raw = doc.raw_lines[int(m.group(1)) - 1]
    if raw is None:
        return None
    return "\n".join(raw[int(m.group(2)) : int(m.group(3)) + 1])


def _split_lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def load_pdf(path: Path, engine: str = "pypdf") -> Document:
    doc = Document(path=path, sha256=file_sha256(path), fmt="pdf", engine=engine)
    try:
        raw = _pdf_pages(path, engine)
    except Exception as e:  # noqa: BLE001 - 파일 전체를 열지 못한 경우
        doc.issues.append(f"PDF를 열지 못함: {type(e).__name__}")
        doc.status = ProcessingStatus.EXTRACTION_FAILED
        return doc
    doc.pages_total = len(raw)
    doc.raw_lines = [None if t is None else _split_lines(t) for t in raw]

    # 분석용 사본: 글꼴 깨짐 복구와 NFKC(합자 ﬁ 등 풀기). 줄 수는 그대로 두어 위치 대응을 지킨다.
    page_lines: list[list[str] | None] = []
    repaired = numbered = 0
    for t in raw:
        if t is None:
            page_lines.append(None)
            continue
        fixed, n = _repair_glyphs(t)
        repaired += n
        lines = _split_lines(unicodedata.normalize("NFKC", fixed))
        if len(lines) != len(_split_lines(t)):
            doc.issues.append("정규화 후 줄 수가 달라져 위치 대응이 어긋날 수 있음")
        lines, hit = _strip_line_numbers(lines)
        numbered += hit
        page_lines.append(lines)
    if repaired:
        doc.issues.append(f"글꼴 깨짐 문자 {repaired}곳을 알려진 규칙으로 복구함")
    broken = sum(broken_glyph_count("\n".join(ls)) for ls in page_lines if ls)
    if broken:
        doc.issues.append(
            f"글자로 바뀌지 않은 문자 {broken}개(수식·기호 글꼴일 가능성)"
        )
    if numbered:
        doc.issues.append(f"줄 번호를 {numbered}쪽에서 지움")

    ok_pages = [(i, ls) for i, ls in enumerate(page_lines, start=1) if ls]
    running = _running_lines([ls for _, ls in ok_pages])
    page_offset = _page_number_offset(ok_pages)
    if running or page_offset is not None:
        doc.issues.append(
            f"반복 머리글·바닥글 {len(running)}종과 쪽 번호를 본문에서 제외함"
        )

    in_refs = False
    for i, lines in enumerate(page_lines, start=1):
        if lines is None:
            doc.pages_failed.append(i)
            continue
        edge = set(_edge(lines))
        block: list[tuple[int, str]] = []
        for j, line in enumerate(lines):
            if j in edge and (
                _norm_line(line) in running
                or (page_offset is not None and line.strip() == str(i + page_offset))
            ):
                continue
            if not in_refs and _REFERENCE_HEADING.match(line):
                _add_paragraphs(doc, block, SegmentKind.BODY, i)
                block = []
                doc.segments.append(
                    Segment(
                        SegmentKind.HEADING,
                        line.strip(),
                        len(doc.segments),
                        page=i,
                        loc=f"p{i}:L{j}-{j}",
                    )
                )
                in_refs = True
                continue
            block.append((j, line))
        _add_paragraphs(
            doc, block, SegmentKind.REFERENCE if in_refs else SegmentKind.BODY, i
        )
    if not in_refs:
        doc.issues.append("참고문헌 시작을 찾지 못함: 참고문헌이 본문에 섞였을 수 있음")
    _mark_back_matter(doc)
    if not _mark_front_matter(doc):
        doc.issues.append(
            "초록·서론 시작을 찾지 못함: 제목·저자·소속이 본문에 섞였을 수 있음"
        )
    return assess(doc)


# ---------------------------------------------------------------- 공통


def assess(doc: Document) -> Document:
    """처리 상태를 정한다. 증거 수준과는 별개다."""
    if doc.status == ProcessingStatus.EXTRACTION_FAILED:
        return doc
    body = doc.text().replace(FORMULA_PLACEHOLDER, " ")
    tokens = _LETTERS.findall(body)
    if not tokens:
        doc.status = ProcessingStatus.EXTRACTION_FAILED
        doc.issues.append("본문 글자를 추출하지 못함(스캔 PDF일 수 있음)")
        return doc
    non_latin = sum(not t.isascii() for t in tokens) / len(tokens)
    stop_ratio = sum(t.lower() in _STOPWORDS for t in tokens) / len(tokens)
    foreign = sum(t.lower() in _FOREIGN_FUNCTION_WORDS for t in tokens) / len(tokens)
    if (
        non_latin > MAX_NON_LATIN_RATIO
        or stop_ratio < MIN_ENGLISH_STOPWORD_RATIO
        or foreign > MAX_FOREIGN_FUNCTION_RATIO
    ):
        doc.status = ProcessingStatus.OUT_OF_SCOPE
        doc.issues.append(
            f"영어 본문으로 보기 어려움(영어 기능어 {stop_ratio:.2f}, 다른 언어 기능어 {foreign:.2f},"
            f" 비라틴 낱말 {non_latin:.2f})"
        )
    elif len(words(body)) < MIN_BODY_WORDS:
        doc.status = ProcessingStatus.TOO_SHORT
    elif doc.pages_failed:
        doc.status = ProcessingStatus.PARTIAL
    else:
        doc.status = ProcessingStatus.COMPLETED
    return doc


def load(path: Path, engine: str | None = None) -> Document:
    suffix = path.suffix.lower()
    if suffix == ".xml":
        return load_jats(path)
    if suffix == ".pdf":
        return load_pdf(path, engine or "pypdf")
    doc = Document(path=path, sha256=file_sha256(path), fmt=suffix, engine="")
    doc.status = ProcessingStatus.OUT_OF_SCOPE
    doc.issues.append(f"지원하지 않는 형식: {suffix}")
    return doc


def summarize(doc: Document) -> dict:
    """원문이 없는 집계. 비공개 원고의 결과도 이 요약만 공유한다."""
    kinds = Counter(s.kind.value for s in doc.segments)
    return {
        "file_sha256": doc.sha256[:16],
        "format": doc.fmt,
        "engine": doc.engine,
        "status": doc.status.value,
        "pages_total": doc.pages_total,
        "pages_failed": doc.pages_failed,
        "segments": dict(sorted(kinds.items())),
        "body_words": len(words(doc.text())),
        "formula_placeholders": doc.text().count(FORMULA_PLACEHOLDER),
        "issues": doc.issues,
    }


def inspect(doc: Document) -> dict:
    """추출 품질 점검용 집계. 원문 없이 숫자만 낸다(비공개 원고 확인용)."""
    body = [s.text for s in doc.segments if s.kind == SegmentKind.BODY]
    lengths = sorted(len(words(t)) for t in body)
    bins = {"<10": 0, "10-29": 0, "30-79": 0, "80-199": 0, "200+": 0}
    for n in lengths:
        key = (
            "<10"
            if n < 10
            else "10-29"
            if n < 30
            else "30-79"
            if n < 80
            else "80-199"
            if n < 200
            else "200+"
        )
        bins[key] += 1
    pages_with_body = {s.page for s in doc.segments if s.kind == SegmentKind.BODY}
    eq = re.compile(r"=[^=]*\(\d{1,3}[a-z]?\)")
    return {
        "status": doc.status.value,
        "segments": dict(sorted(Counter(s.kind.value for s in doc.segments).items())),
        "body_paragraph_words": bins,
        "body_paragraph_words_median": lengths[len(lengths) // 2] if lengths else 0,
        "body_not_ending_with_punctuation": sum(
            not re.search(r"[.?!:;)\]\"']$", t) for t in body
        ),
        "body_starting_lowercase": sum(t[:1].islower() for t in body),
        "body_starting_with_digit": sum(t[:1].isdigit() for t in body),
        "body_mostly_numbers": sum(
            sum(bool(_NUMBER_TOKEN.match(x)) for x in t.split())
            >= 0.2 * max(len(t.split()), 1)
            for t in body
        ),
        "broken_glyphs_in_body": sum(broken_glyph_count(t) for t in body),
        # 등호와 "(번호)"가 있는데 본문으로 남은 문단: 수식이 문장과 붙어 있을 가능성
        "body_equation_like": sum(bool(eq.search(t)) for t in body),
        "body_equation_like_with_broken_glyphs": sum(
            bool(eq.search(t)) and broken_glyph_count(t) > 0 for t in body
        ),
        # 그 문단에서 수식으로 떼어 내지 못한 이유: 소문자 4글자 이상 낱말이 함께 있음
        "body_equation_like_with_words": sum(
            bool(eq.search(t)) and not _is_equation_line(t) for t in body
        ),
        "pages_without_body": sorted(
            i for i in range(1, (doc.pages_total or 0) + 1) if i not in pages_with_body
        ),
        "issues": doc.issues,
    }
