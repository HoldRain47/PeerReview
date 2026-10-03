"""AI 변형본 만들기 (T002.5).

사람 작성 씨앗 논문(JATS XML)의 서론 앞 문단 몇 개를 AI로 바꾼 변형본을 만든다.
짝 설계: 원본과 변형본은 같은 묶음(bundle_id)이다. 바꾼 문단 위치가 곧 구간 정답이다.
근거: tasks/plan.md 2절(짝 설계)·T002.5, docs/라벨지침-v26100302.md 3·5절, docs/변형본생성규칙.md.

이 모듈은 네트워크를 쓰지 않는다. 모델 호출은 scripts/make_variants.py가 한다.
"""

from __future__ import annotations

import random
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from peerreview.ingest import (
    FORMULA_PLACEHOLDER,
    _child_paths,
    _jats_text,
    _local,
    words,
)
from peerreview.model import InvolvementAct

# 시범에서 만드는 행위. AI 초안을 사람이 수정한 경우(human_edited_ai)는 사람 편집이 필요해 뺀다.
PILOT_ACTS = (
    InvolvementAct.GENERATION,
    InvolvementAct.REWRITING,
    InvolvementAct.PROOFREADING,
    InvolvementAct.TRANSLATION,
    InvolvementAct.MIXED,
)
TARGET_PARAGRAPHS = 3  # 서론 앞에서 바꿀 문단 수
MIN_PARAGRAPH_WORDS = 60
_INTRO = re.compile(r"^\s*(\d+\.?\s*)?introduction\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[(])")


@dataclass
class Target:
    seed_id: str
    title: str
    abstract: str
    locs: list[str]  # 바꿀 문단의 JATS 요소 경로
    paragraphs: list[str]  # 원래 문단 글자


@dataclass
class Task:
    """모델에 줄 지시. steps는 차례로 보내는 사용자 메시지다(번역은 2단계)."""

    variant_id: str
    seed_id: str
    act: str
    model_family: str  # "claude" | "openai"
    steps: list[str]
    target_locs: list[str]
    kept_prefix: list[str] = field(
        default_factory=list
    )  # 혼합: 문단마다 남기는 원문 앞부분


def find_target(xml_path: Path, seed_id: str) -> Target | None:
    """서론 절의 앞 문단 TARGET_PARAGRAPHS개를 고른다. 짧거나 수식이 든 문단이면 None."""
    root = ET.parse(xml_path).getroot()
    title_el = root.find(".//article-title")
    title = _jats_text(title_el) if title_el is not None else ""
    abstract = " ".join(
        _jats_text(p)
        for ab in root.iter("abstract")
        if ab.get("abstract-type") in (None, "", "abstract")
        for p in ab.iter("p")
    )
    body = root.find("body")
    if body is None:
        return None
    for sec, spath in _child_paths(body, "body[1]"):
        if _local(sec.tag) != "sec":
            continue
        t = sec.find("title")
        if t is None or not _INTRO.match(_jats_text(t)):
            continue
        paras = [(c, p) for c, p in _child_paths(sec, spath) if _local(c.tag) == "p"]
        picked = paras[:TARGET_PARAGRAPHS]
        texts = [_jats_text(c) for c, _ in picked]
        if len(picked) < TARGET_PARAGRAPHS:
            return None
        if any(
            len(words(x)) < MIN_PARAGRAPH_WORDS or FORMULA_PLACEHOLDER in x
            for x in texts
        ):
            return None
        return Target(seed_id, title, abstract, [p for _, p in picked], texts)
    return None


# 문장 끝으로 보지 않는 약어. 시범 작업 지시(2026-10-04)는 이 규칙 전에 만들어져 "et al." 뒤에서 잘린 것이 있다.
_ABBREV = re.compile(
    r"(?:\bet al|\be\.g|\bi\.e|\bFigs?|\bEqs?|\bRefs?|\bvs|\bca|\bapprox|\bNo)\.$",
    re.IGNORECASE,
)


def split_sentences(paragraph: str) -> list[str]:
    """문장으로 나눈다. "et al.", "e.g.", "Fig." 같은 약어 뒤에서는 나누지 않는다."""
    out: list[str] = []
    for piece in _SENTENCE_END.split(paragraph.strip()):
        if out and _ABBREV.search(out[-1]):
            out[-1] = f"{out[-1]} {piece}"
        elif piece:
            out.append(piece)
    return out


def build_steps(act: InvolvementAct, t: Target) -> tuple[list[str], list[str]]:
    """행위별 지시문을 만든다. (steps, 혼합용 남길 앞부분)을 돌려준다.

    지시문은 실제 저자가 채팅 도구에 넣을 법한 짧은 영어 요청으로 쓴다.
    """
    k = len(t.paragraphs)
    joined = "\n\n".join(t.paragraphs)
    fmt = f"Return exactly {k} paragraphs separated by a blank line, with no title or commentary."
    if act == InvolvementAct.GENERATION:
        return [
            (
                f'I am writing a research article titled "{t.title}".\n\nAbstract:\n{t.abstract}\n\n'
                f"Write the first {k} paragraphs of the Introduction (about {len(words(joined))} words in "
                f"total). {fmt}"
            )
        ], []
    if act == InvolvementAct.REWRITING:
        return [
            (
                "Rewrite the following paragraphs from my paper to improve clarity, flow and academic "
                f"style. Keep the meaning and keep citation markers such as [1] as they are. {fmt}\n\n{joined}"
            )
        ], []
    if act == InvolvementAct.PROOFREADING:
        return [
            (
                "Proofread the following paragraphs. Correct only spelling, grammar and punctuation "
                "errors. Do not rephrase, reorder or change word choice. If there is no error, return "
                f"the text unchanged. {fmt}\n\n{joined}"
            )
        ], []
    if act == InvolvementAct.TRANSLATION:
        # 대용 방식: 사람이 쓴 한국어 원문이 없어 영어→한국어→영어로 만든다(docs/변형본생성규칙.md 한계).
        return [
            f"Translate the following paragraphs into Korean. {fmt}\n\n{joined}",
            (
                "Translate the following Korean paragraphs into English for a chemical engineering "
                f"research article. {fmt}\n\n{{PREVIOUS_OUTPUT}}"
            ),
        ], []
    if act == InvolvementAct.MIXED:
        kept = []
        prompts = []
        for p in t.paragraphs:
            sents = split_sentences(p)
            keep = sents[: max(1, (len(sents) + 1) // 2)]
            kept.append(" ".join(keep))
            prompts.append((" ".join(keep), max(1, len(sents) - len(keep))))
        listing = "\n\n".join(
            f"Paragraph {i + 1} (continue with about {n} sentences):\n{text}"
            for i, (text, n) in enumerate(prompts)
        )
        return [
            (
                f'My paper is titled "{t.title}". Each paragraph below is unfinished. Write only the '
                "continuation sentences for each paragraph, consistent with the topic. Return exactly "
                f"{k} continuations separated by a blank line, in order, with no labels.\n\n{listing}"
            )
        ], kept
    raise ValueError(f"시범에서 다루지 않는 행위: {act}")


def plan_tasks(
    targets: list[Target], families: tuple[str, ...], seed: int
) -> list[Task]:
    """씨앗마다 시범 행위 전부를 만들고, 모델 계열은 (씨앗, 행위)마다 번갈아 배정한다."""
    rng = random.Random(seed)
    tasks = []
    for i, t in enumerate(targets):
        offset = rng.randrange(len(families))
        for j, act in enumerate(PILOT_ACTS):
            fam = families[(i + j + offset) % len(families)]
            steps, kept = build_steps(act, t)
            tasks.append(
                Task(
                    variant_id=f"{t.seed_id}-{act.value}-{fam}",
                    seed_id=t.seed_id,
                    act=act.value,
                    model_family=fam,
                    steps=steps,
                    target_locs=t.locs,
                    kept_prefix=kept,
                )
            )
    return tasks


def split_output(text: str, k: int) -> list[str] | None:
    """모델 출력을 문단 k개로 나눈다. 개수가 맞지 않으면 None."""
    parts = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text.strip())]
    parts = [p for p in parts if p]
    return parts if len(parts) == k else None


def final_paragraphs(task: Task, output: str) -> list[str] | None:
    """마지막 단계 출력에서 최종 문단을 만든다. 혼합은 남긴 원문 앞부분 뒤에 이어 붙인다."""
    parts = split_output(output, len(task.target_locs))
    if parts is None:
        return None
    if task.act == InvolvementAct.MIXED.value:
        return [
            f"{keep} {cont}" for keep, cont in zip(task.kept_prefix, parts, strict=True)
        ]
    return parts


def build_variant_xml(
    seed_xml: Path, locs: list[str], paragraphs: list[str], out: Path
) -> None:
    """씨앗 XML을 읽어 locs의 문단 글자만 바꾼 사본을 out에 저장한다. 원본 파일은 건드리지 않는다."""
    if out.resolve() == seed_xml.resolve():
        raise ValueError("변형본 경로가 씨앗 파일과 같음")
    tree = ET.parse(seed_xml)
    root = tree.getroot()
    for loc, text in zip(locs, paragraphs, strict=True):
        el = _find(root, loc)
        if el is None:
            raise ValueError(f"위치를 찾지 못함: {loc}")
        attrib = dict(el.attrib)
        el.clear()  # 문단 안의 인용 표시·각주 태그도 지우고 글자만 남긴다
        el.attrib.update(attrib)
        el.text = text
    out.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out, encoding="utf-8", xml_declaration=True)


def _find(root: ET.Element, loc: str) -> ET.Element | None:
    el: ET.Element | None = root
    for step in loc.split("/"):
        m = re.fullmatch(r"([\w-]+)\[(\d+)\]", step)
        if el is None or not m:
            return None
        same = [c for c in el if _local(c.tag) == m.group(1)]
        i = int(m.group(2)) - 1
        el = same[i] if i < len(same) else None
    return el


@dataclass
class ChangeCheck:
    similarity: float  # 원문과 새 글의 낱말 순서 유사도(0~1), 문단 평균
    sentence_delta: int  # 문장 수 변화 합
    label_act: str  # 라벨 지침 5절에 비추어 붙일 행위
    note: str


def check_change(task: Task, original: list[str], new: list[str]) -> ChangeCheck:
    """의도한 행위가 실제로 일어났는지 대략 확인하고, 라벨로 쓸 행위를 정한다.

    교정을 의도했는데 문장 수가 바뀌거나 유사도가 0.9 미만이면 라벨 지침 5절에 따라 재작성으로 본다.
    재작성인데 거의 바뀌지 않았으면(0.97 이상) 교정으로 본다. 생성·번역·혼합은 의도대로 둔다.
    """
    sims, delta = [], 0
    for o, n in zip(original, new, strict=True):
        ow, nw = [w.lower() for w in words(o)], [w.lower() for w in words(n)]
        sims.append(SequenceMatcher(None, ow, nw, autojunk=False).ratio())
        delta += len(split_sentences(n)) - len(split_sentences(o))
    sim = sum(sims) / len(sims)
    act, note = task.act, ""
    if task.act == InvolvementAct.PROOFREADING.value and (sim < 0.9 or delta != 0):
        act, note = (
            InvolvementAct.REWRITING.value,
            "교정 의도였으나 구조·표현이 바뀌어 재작성으로 라벨",
        )
    elif task.act == InvolvementAct.REWRITING.value and sim >= 0.97:
        act, note = (
            InvolvementAct.PROOFREADING.value,
            "재작성 의도였으나 거의 바뀌지 않아 교정으로 라벨",
        )
    elif task.act == InvolvementAct.PROOFREADING.value and sim >= 0.999:
        note = "바뀐 곳이 없음(오류 없는 원문)"
    return ChangeCheck(round(sim, 3), delta, act, note)
