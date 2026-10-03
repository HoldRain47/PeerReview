"""평가 자료 목록 (T002.4).

자료 목록은 JSON Lines 파일 한 줄에 문서 하나다. 원문은 넣지 않고, 원문 파일의 경로와 해시만 둔다.
근거: tasks/plan.md T002.4, 목표 정의서 2절(영어, Chemical Engineering, 연구 논문),
자료출처조사 2절(변형본 씨앗은 CC BY만).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from peerreview.ingest import file_sha256

# 사람 작성 기준 자료(D)의 공개 연도 범위 (2026-10-04 사용자 결정)
D_YEAR_MIN, D_YEAR_MAX = 2017, 2021
ALLOWED_LICENSES = frozenset({"cc by"})
# 분석용(변형본을 만들지 않는 사람 작성 자료)은 비상업 조건도 허용한다(자료출처조사 2절).
ANALYSIS_LICENSES = frozenset({"cc by", "cc by-nc"})
# seed: 변형본의 씨앗이 되는 사람 작성 원본, variant: 씨앗에서 만든 변형본, analysis: 분석에만 쓰는 사람 작성 자료
ROLES = frozenset({"seed", "variant", "analysis"})

# 세부 분야 분류용 주제어(제목·초록). 넓은 범위(2026-10-04 사용자 결정): 공정·반응·분리 외에
# 촉매·재료 합성·전기화학·생물공정을 포함한다. 한 문서가 여러 분야에 들 수 있다.
SUBFIELD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "reaction_engineering": (
        "reactor",
        "kinetic",
        "reaction rate",
        "conversion",
        "residence time",
    ),
    "separation": (
        "distillation",
        "adsorption",
        "adsorbent",
        "membrane",
        "separation",
        "extraction",
        "absorption",
        "crystallization",
        "filtration",
    ),
    "process_systems": (
        "process simulation",
        "process design",
        "optimization",
        "techno-economic",
        "scale-up",
        "aspen",
        "life cycle",
    ),
    "transport": ("mass transfer", "heat transfer", "diffusion", "fluid", "flow"),
    "catalysis": ("catalyst", "catalytic", "catalysis"),
    "materials_synthesis": (
        "synthesis",
        "synthesized",
        "fabrication",
        "nanoparticle",
        "composite",
    ),
    "electrochemistry": (
        "electrochemical",
        "electrode",
        "battery",
        "electrolysis",
        "fuel cell",
    ),
    "bioprocess": (
        "fermentation",
        "bioprocess",
        "enzyme",
        "bioreactor",
        "microbial",
        "biomass",
    ),
}


@dataclass
class ManifestEntry:
    doc_id: str
    bundle_id: str
    source: str  # 예: "europepmc"
    license: str  # 예: "cc by"
    pub_year: int
    journal: str
    path: str  # 저장소 기준 상대 경로 또는 data/ 아래 경로
    sha256: str
    doi: str = ""
    pmcid: str = ""
    title: str = ""  # 공개 논문의 제목(공개 메타데이터)
    subfields: list[str] = field(default_factory=list)
    role: str = "seed"  # ROLES 참고
    truth_basis: str = "D"
    retrieved_at: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def assign_subfields(title: str, abstract: str) -> list[str]:
    text = f"{title} {abstract}".lower()
    return [
        name
        for name, kws in SUBFIELD_KEYWORDS.items()
        if any(re.search(rf"\b{re.escape(k)}", text) for k in kws)
    ]


def load_manifest(path: Path) -> tuple[list[ManifestEntry], list[str]]:
    entries: list[ManifestEntry] = []
    errors: list[str] = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                raise TypeError("JSON 객체가 아님")
            entries.append(ManifestEntry(**data))
        except (json.JSONDecodeError, TypeError) as e:
            errors.append(f"{no}줄: 읽을 수 없음({type(e).__name__})")
    return entries, errors


def save_manifest(path: Path, entries: list[ManifestEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(e.to_json() + "\n" for e in entries), encoding="utf-8")


def check_manifest(entries: list[ManifestEntry], root: Path) -> list[str]:
    """파일 존재·해시 일치·이용 조건·연도·중복을 검사한다. 오류 문장 목록을 돌려준다."""
    errors: list[str] = []
    seen: set[str] = set()
    seed_bundles = {e.bundle_id for e in entries if e.role == "seed"}
    for e in entries:
        tag = e.doc_id or "(doc_id 없음)"
        if not e.doc_id or not e.bundle_id:
            errors.append(f"{tag}: doc_id 또는 bundle_id가 비어 있음")
        if e.doc_id in seen:
            errors.append(f"{tag}: doc_id 중복")
        seen.add(e.doc_id)
        if e.role not in ROLES:
            errors.append(f"{tag}: role 값 {e.role!r}이 {sorted(ROLES)}에 없음")
        if e.role == "seed" and e.license.lower() not in ALLOWED_LICENSES:
            errors.append(f"{tag}: 씨앗 자료의 이용 조건이 CC BY가 아님({e.license})")
        if e.role == "analysis" and e.license.lower() not in ANALYSIS_LICENSES:
            errors.append(f"{tag}: 분석용 자료의 이용 조건이 허용 범위 밖({e.license})")
        in_d = e.role in ("seed", "analysis") and e.truth_basis == "D"
        if in_d and not D_YEAR_MIN <= e.pub_year <= D_YEAR_MAX:
            errors.append(f"{tag}: 근거 D인데 공개 연도 {e.pub_year}가 범위 밖")
        if e.role == "variant" and e.bundle_id not in seed_bundles:
            errors.append(f"{tag}: 변형본의 bundle_id가 목록의 어떤 씨앗과도 맞지 않음")
        f = root / e.path
        if not f.is_file():
            errors.append(f"{tag}: 파일 없음")
        elif file_sha256(f) != e.sha256:
            errors.append(f"{tag}: 해시 불일치(파일이 바뀜)")
    return errors


def allocate_quotas(sizes: dict, n: int) -> dict:
    """층별 크기에 비례해 합이 정확히 n이 되게 배분한다(최대 나머지 방식). 층 크기를 넘지 않는다."""
    total = sum(sizes.values())
    n = min(n, total)
    if n <= 0:
        return {k: 0 for k in sizes}
    exact = {k: n * v / total for k, v in sizes.items()}
    quota = {k: min(int(x), sizes[k]) for k, x in exact.items()}
    # 나머지가 큰 층부터 하나씩 더한다. 같으면 층 이름 순서로 정해 재현 가능하게 한다.
    order = sorted(sizes, key=lambda k: (-(exact[k] - int(exact[k])), str(k)))
    i = 0
    while sum(quota.values()) < n:
        k = order[i % len(order)]
        if quota[k] < sizes[k]:
            quota[k] += 1
        i += 1
    return quota


def stratified_queues(rows: list[dict], keys: tuple[str, ...], seed: int) -> dict:
    """층마다 문서 순서를 정한다. API가 준 순서와 무관하게, doc 식별자로 정렬한 뒤 시드로 섞는다."""
    import random

    rng = random.Random(seed)
    queues: dict = {}
    for r in sorted(rows, key=lambda r: r["pmcid"]):
        queues.setdefault(tuple(r[k] for k in keys), []).append(r)
    for key in sorted(queues):
        rng.shuffle(queues[key])
    return queues
