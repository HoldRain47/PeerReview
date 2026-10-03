"""정답 라벨 기록 형식과 검사 (T002.3).

근거: docs/라벨지침-v26100302.md 1절(필드), 2절(정답 근거 수준), 4절(판정 절차).
라벨은 JSON Lines 파일 한 줄에 문서 하나로 저장한다. 원고 원문은 넣지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

from peerreview.model import TARGET_ACTS, InvolvementAct


class TruthBasis(StrEnum):
    """정답 근거 수준 (라벨 지침 2절)."""

    A = "A"  # 통제된 작성 과정 기록, 진위·연결 확인
    B = "B"  # 기록이 일부 구간·시점만 확인됨
    C = "C"  # 작성자 진술이나 버전 이력 하나뿐
    D = "D"  # AI 도구 보급 이전 공개 자료(사람 작성 기준)


class TargetPresence(StrEnum):
    """1차 목표 행위(생성·재작성)가 논문에 있었는가."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


@dataclass
class Span:
    act: InvolvementAct
    loc: str  # 원문 위치(ingest의 loc 형식이나 절 이름)


@dataclass
class LabelRecord:
    doc_id: str
    bundle_id: str
    truth_basis: TruthBasis
    acts: list[InvolvementAct] = field(default_factory=list)
    spans: list[Span] = field(default_factory=list)
    checked_scope: str = ""
    tools: list[str] = field(default_factory=list)
    notes: str = ""
    target_present: TargetPresence | None = None  # 비우면 derive_target으로 채운다

    def to_json(self) -> str:
        data = asdict(self)
        data["target_present"] = (self.target_present or derive_target(self)).value
        return json.dumps(data, ensure_ascii=False)


def derive_target(rec: LabelRecord) -> TargetPresence:
    """라벨 지침 4절의 4~5번 단계.

    - 관여 행위에 목표 행위가 하나라도 있으면 예.
    - 목표 행위가 없다는 근거가 A 또는 D이고 미상 행위가 없으면 아니오.
    - 그 밖(B, C, 미상 행위 포함)은 미상.

    해석: acts에 unknown이 섞이면 근거가 A여도 아니오로 확정하지 않는다. 모르는 부분에
    목표 행위가 있었을 수 있어서다(라벨 지침 1절 "모르면 unknown", 3절 "편의상 배정하지 않는다").
    """
    acts = set(rec.acts)
    if acts & TARGET_ACTS:
        return TargetPresence.YES
    if InvolvementAct.UNKNOWN in acts:
        return TargetPresence.UNKNOWN
    if rec.truth_basis in (TruthBasis.A, TruthBasis.D):
        return TargetPresence.NO
    return TargetPresence.UNKNOWN


def validate(rec: LabelRecord) -> list[str]:
    """기록의 잘못을 문장 목록으로 돌려준다. 비어 있으면 통과."""
    errors: list[str] = []
    if not rec.doc_id.strip():
        errors.append("doc_id가 비어 있음")
    if not rec.bundle_id.strip():
        errors.append("bundle_id가 비어 있음(학습·시험 분리의 단위라 필수)")
    if len(set(rec.acts)) != len(rec.acts):
        errors.append("acts에 같은 행위가 두 번 있음")
    if rec.truth_basis == TruthBasis.D and rec.acts:
        errors.append("근거 D(AI 보급 이전 자료)인데 관여 행위가 있음")
    for sp in rec.spans:
        if sp.act not in rec.acts:
            errors.append(f"spans의 행위 {sp.act.value}가 acts에 없음")
        if not sp.loc.strip():
            errors.append("spans에 위치(loc)가 빈 항목이 있음")
    derived = derive_target(rec)
    if rec.target_present is not None and rec.target_present != derived:
        errors.append(
            f"target_present가 {rec.target_present.value}인데 판정 절차로는 {derived.value}임"
        )
    return errors


def from_dict(data: dict) -> LabelRecord:
    """JSON 객체를 기록으로 바꾼다. 알 수 없는 값이면 ValueError."""
    if not isinstance(data, dict):
        raise TypeError("JSON 객체가 아님")
    tp = data.get("target_present")
    return LabelRecord(
        doc_id=str(data.get("doc_id", "")),
        bundle_id=str(data.get("bundle_id", "")),
        truth_basis=TruthBasis(data["truth_basis"]),
        acts=[InvolvementAct(a) for a in data.get("acts", [])],
        spans=[
            Span(InvolvementAct(s["act"]), str(s.get("loc", "")))
            for s in data.get("spans", [])
        ],
        checked_scope=str(data.get("checked_scope", "")),
        tools=[str(t) for t in data.get("tools", [])],
        notes=str(data.get("notes", "")),
        target_present=TargetPresence(tp) if tp else None,
    )


def load_labels(path: Path) -> tuple[list[LabelRecord], list[str]]:
    """JSON Lines 라벨 파일을 읽어 (기록, 오류) 를 돌려준다. 오류에는 줄 번호를 붙인다."""
    records: list[LabelRecord] = []
    errors: list[str] = []
    seen: set[str] = set()
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rec = from_dict(json.loads(line))
        except (
            json.JSONDecodeError,
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
        ) as e:
            errors.append(f"{no}줄: 읽을 수 없음({type(e).__name__})")
            continue
        errors += [f"{no}줄: {m}" for m in validate(rec)]
        if rec.doc_id in seen:
            errors.append(f"{no}줄: doc_id {rec.doc_id}가 중복됨")
        seen.add(rec.doc_id)
        records.append(rec)
    return records, errors


def save_labels(path: Path, records: list[LabelRecord]) -> None:
    path.write_text("".join(r.to_json() + "\n" for r in records), encoding="utf-8")
