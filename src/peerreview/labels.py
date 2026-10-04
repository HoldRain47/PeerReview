"""정답 라벨 기록 형식과 검사 (T002.3).

근거: docs/라벨지침-v26100303.md 1절(필드), 2절(정답 근거 수준), 4절(단계별 판정 절차).
라벨은 JSON Lines 파일 한 줄에 문서 하나로 저장한다. 원고 원문은 넣지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

from peerreview.model import STAGE_ACTS, InvolvementAct, Stage


class TruthBasis(StrEnum):
    """정답 근거 수준 (라벨 지침 2절)."""

    A = "A"  # 통제된 작성 과정 기록, 진위·연결 확인
    B = "B"  # 기록이 일부 구간·시점만 확인됨
    C = "C"  # 작성자 진술이나 버전 이력 하나뿐
    D = "D"  # AI 도구 보급 이전 공개 자료(사람 작성 기준)


class TargetPresence(StrEnum):
    """한 판정 단계의 행위가 논문에 있었는가."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


@dataclass
class Span:
    act: InvolvementAct
    loc: str  # 원문 위치(ingest의 loc 형식이나 절 이름)
    lang: str = "en"  # 행위가 일어난 글의 언어. 한국어 초안 단계면 "ko"


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
    # 기록이 일부 구간만 다룰 때(변형본), 나머지 구간의 근거. 예: 씨앗 원문 부분은 D
    rest_basis: TruthBasis | None = None
    # 본문 단계의 판정(이전 판과 호환). 비우면 계산한다. 기록에 있으면 계산값과 대조한다.
    target_present: TargetPresence | None = None

    def to_json(self) -> str:
        data = asdict(self)
        # 저장하는 판정은 언제나 계산값이다. 어긋난 값은 save_labels가 막는다.
        data["target_present"] = derive_target(self).value
        data["stages"] = {k.value: v.value for k, v in derive_stages(self).items()}
        return json.dumps(data, ensure_ascii=False)


def derive_stage(rec: LabelRecord, stage: Stage) -> TargetPresence:
    """라벨 지침 4절 5~6번. 한 단계의 판정.

    - 그 단계의 행위가 acts에 있으면 예.
    - 없고 unknown 행위도 없으며 근거가 A이면 아니오. 근거 D는 기계 번역 단계를 뺀 단계에서만 아니오.
    - 그 밖(B, C, unknown 포함, D의 기계 번역 단계)은 미상.

    해석: acts에 unknown이 섞이면 근거가 A여도 아니오로 확정하지 않는다. 모르는 부분에
    그 행위가 있었을 수 있어서다. D(2017~2021년 공개)는 생성형 AI가 없었다는 근거일 뿐, 그때도 널리
    쓰인 기계 번역이 없었다는 근거는 아니다.
    """
    acts = set(rec.acts)
    if acts & STAGE_ACTS[stage]:
        return TargetPresence.YES
    if InvolvementAct.UNKNOWN in acts:
        return TargetPresence.UNKNOWN
    bases = [rec.truth_basis] + ([rec.rest_basis] if rec.rest_basis else [])
    # 모든 구간의 근거가 "아니오"를 뒷받침해야 아니오다(변형본의 나머지 원문 부분 포함)
    if all(_rules_out(b, stage) for b in bases):
        return TargetPresence.NO
    return TargetPresence.UNKNOWN


def _rules_out(basis: TruthBasis, stage: Stage) -> bool:
    if basis == TruthBasis.A:
        return True
    return basis == TruthBasis.D and stage != Stage.MACHINE_TRANSLATION


def derive_stages(rec: LabelRecord) -> dict[Stage, TargetPresence]:
    return {stage: derive_stage(rec, stage) for stage in Stage}


def derive_target(rec: LabelRecord) -> TargetPresence:
    """본문 생성·재작성 단계의 판정(이전 판의 target_present)."""
    return derive_stage(rec, Stage.BODY)


def validate(rec: LabelRecord) -> list[str]:
    """기록의 잘못을 문장 목록으로 돌려준다. 비어 있으면 통과."""
    errors: list[str] = []
    if not rec.doc_id.strip():
        errors.append("doc_id가 비어 있음")
    if not rec.bundle_id.strip():
        errors.append("bundle_id가 비어 있음(학습·시험 분리의 단위라 필수)")
    if len(set(rec.acts)) != len(rec.acts):
        errors.append("acts에 같은 행위가 두 번 있음")
    # 근거 D(2017~2021 공개)는 생성형 AI 행위를 가질 수 없다. 기계 번역은 그때도 있었으므로 허용한다.
    if rec.truth_basis == TruthBasis.D and set(rec.acts) - {
        InvolvementAct.MACHINE_TRANSLATION
    }:
        errors.append("근거 D(AI 보급 이전 자료)인데 기계 번역이 아닌 관여 행위가 있음")
    for sp in rec.spans:
        if sp.act not in rec.acts:
            errors.append(f"spans의 행위 {sp.act.value}가 acts에 없음")
        if not sp.loc.strip():
            errors.append("spans에 위치(loc)가 빈 항목이 있음")
        if sp.lang not in ("en", "ko"):
            errors.append(f"spans의 언어 {sp.lang!r}가 en·ko가 아님")
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
            Span(
                InvolvementAct(s["act"]),
                str(s.get("loc", "")),
                str(s.get("lang", "en")),
            )
            for s in data.get("spans", [])
        ],
        checked_scope=str(data.get("checked_scope", "")),
        tools=[str(t) for t in data.get("tools", [])],
        notes=str(data.get("notes", "")),
        rest_basis=TruthBasis(data["rest_basis"]) if data.get("rest_basis") else None,
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
            data = json.loads(line)
            rec = from_dict(data)
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
        stored = data.get("stages") or {}
        if not isinstance(stored, dict):
            errors.append(f"{no}줄: stages가 객체가 아님")
            stored = {}
        derived = {k.value: v.value for k, v in derive_stages(rec).items()}
        for stage, value in stored.items():
            if derived.get(stage) != value:
                errors.append(
                    f"{no}줄: stages.{stage}가 {value}인데 판정 절차로는 {derived.get(stage)}임"
                )
        if rec.doc_id in seen:
            errors.append(f"{no}줄: doc_id {rec.doc_id}가 중복됨")
        seen.add(rec.doc_id)
        records.append(rec)
    return records, errors


def save_labels(path: Path, records: list[LabelRecord]) -> None:
    """검사를 통과한 기록만 저장한다. 하나라도 잘못되면 아무것도 쓰지 않고 ValueError를 낸다."""
    errors = [f"{r.doc_id}: {m}" for r in records for m in validate(r)]
    if errors:
        raise ValueError("라벨 저장 거부: " + "; ".join(errors[:5]))
    path.write_text("".join(r.to_json() + "\n" for r in records), encoding="utf-8")
