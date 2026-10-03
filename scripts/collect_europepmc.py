"""Europe PMC에서 사람 작성 기준 자료(D) 후보를 모으고 표본을 내려받는다 (T002.4).

공개 논문 전용이다. 요청에 사용자 식별 정보(이메일 등)를 넣지 않는다.
사용법:
  uv run python scripts/collect_europepmc.py candidates   # 후보 메타데이터 수집 → data/public/candidates.jsonl
  uv run python scripts/collect_europepmc.py sample 300   # 층화 표본 내려받기 → data/public/xml/, data/manifest.jsonl
"""

import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from peerreview.ingest import file_sha256
from peerreview.manifest import (
    D_YEAR_MAX,
    D_YEAR_MIN,
    ManifestEntry,
    allocate_quotas,
    assign_subfields,
    load_manifest,
    save_manifest,
    stratified_queues,
)

API = "https://www.ebi.ac.uk/europepmc/webservices/rest"
JOURNALS = ("RSC Advances", "Membranes", "ACS Omega")
KEYWORDS = [
    "reactor",
    "distillation",
    "adsorption",
    "membrane",
    "separation",
    "kinetics",
    "crystallization",
    "extraction",
    "catalyst",
    "catalytic",
    "electrochemical",
    "fermentation",
    "bioprocess",
    "synthesis",
]
PHRASES = (
    "process simulation",
    "process design",
    "mass transfer",
    "heat transfer",
    "scale-up",
    "techno-economic",
)
# 연구 논문이 아닌 출판 공지. 제목 앞머리나 논문 종류에 나온다.
NOTICE = re.compile(
    r"^\s*(expression of concern|retraction|retracted|correction|corrigendum|erratum|withdrawn)",
    re.IGNORECASE,
)
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CANDIDATES = DATA / "public" / "candidates.jsonl"
MANIFEST = DATA / "manifest.jsonl"
SEED = 20261004  # 표본 추출 난수 시드(재현용)


def _get(url: str) -> bytes:
    """GET 요청. 서버 오류·연결 오류는 4번까지 다시 시도하고, 4xx(없는 문서 등)는 바로 예외를 낸다."""
    req = urllib.request.Request(url, headers={"User-Agent": "PeerReview-research/0.1"})
    last: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code < 500:
                raise
            last = e
        except OSError as e:
            last = e
        time.sleep(2**attempt)
    raise RuntimeError(f"요청 실패({type(last).__name__}): {url[:80]}")


def query_for(journal: str) -> str:
    kw = " OR ".join([f'TITLE_ABS:"{k}"' for k in (*KEYWORDS, *PHRASES)])
    return (
        f'JOURNAL:"{journal}" AND PUB_YEAR:[{D_YEAR_MIN} TO {D_YEAR_MAX}] AND IN_PMC:y'
        f' AND LICENSE:"cc by" AND NOT PUB_TYPE:"review" AND ({kw})'
    )


def collect_candidates() -> None:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for journal in JOURNALS:
        cursor = "*"
        while True:
            params = {
                "query": query_for(journal),
                "format": "json",
                "pageSize": "500",
                "resultType": "core",
                "cursorMark": cursor,
            }
            data = json.loads(_get(f"{API}/search?{urllib.parse.urlencode(params)}"))
            results = data["resultList"]["result"]
            for r in results:
                pub_types = r.get("pubTypeList", {}).get("pubType", [])
                if any(NOTICE.search(t) for t in pub_types) or NOTICE.match(
                    r.get("title", "")
                ):
                    continue  # 연구 논문이 아닌 공지(정정·철회·우려 표명 등)
                rows.append(
                    {
                        "pmcid": r.get("pmcid", ""),
                        "doi": r.get("doi", ""),
                        "journal": journal,
                        "pub_year": int(r.get("pubYear", 0)),
                        "license": (r.get("license") or "").lower(),
                        "title": r.get("title", ""),
                        "subfields": assign_subfields(
                            r.get("title", ""), r.get("abstractText", "")
                        ),
                    }
                )
            nxt = data.get("nextCursorMark")
            # 마지막 페이지면 nextCursorMark가 없거나 그대로다
            if not results or not nxt or nxt == cursor:
                break
            cursor = nxt
            time.sleep(0.3)
        print(journal, sum(1 for x in rows if x["journal"] == journal))
    rows = [r for r in rows if r["pmcid"] and r["license"] == "cc by"]
    CANDIDATES.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    print("후보", len(rows), "→", CANDIDATES.relative_to(ROOT))


def download_sample(n: int) -> None:
    """학술지×연도 층에 비례 배분해 n편을 맞춘다. 이미 목록에 있는 문서는 그 층의 몫으로 센다.

    본문이 없거나 내려받지 못한 문서는 건너뛰고 같은 층의 다음 후보로 채운다.
    """
    rows = [
        json.loads(x)
        for x in CANDIDATES.read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    existing: list[ManifestEntry] = []
    if MANIFEST.exists():
        existing, errors = load_manifest(MANIFEST)
        if errors:
            # 다시 저장하면 읽지 못한 줄이 사라지므로 멈춘다
            sys.exit(
                "자료 목록에 읽을 수 없는 줄이 있어 멈춤: " + "; ".join(errors[:3])
            )
    keys = ("journal", "pub_year")
    queues = stratified_queues(rows, keys, SEED)
    quotas = allocate_quotas({k: len(v) for k, v in queues.items()}, n)
    have = {e.doc_id for e in existing}
    count = {
        k: sum(1 for e in existing if (e.journal, e.pub_year) == k) for k in queues
    }
    xml_dir = DATA / "public" / "xml"
    xml_dir.mkdir(parents=True, exist_ok=True)
    entries = list(existing)
    skipped = 0
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    try:
        for key in sorted(queues):
            for r in queues[key]:
                if count[key] >= quotas[key]:
                    break
                if r["pmcid"] in have:
                    continue
                f = xml_dir / f"{r['pmcid']}.xml"
                if not f.exists():
                    try:
                        body = _get(f"{API}/{r['pmcid']}/fullTextXML")
                    except (urllib.error.HTTPError, RuntimeError) as e:
                        print("내려받기 실패, 건너뜀:", r["pmcid"], type(e).__name__)
                        skipped += 1
                        continue
                    if b"<body" not in body:
                        print("본문 없음, 건너뜀:", r["pmcid"])
                        skipped += 1
                        continue
                    f.write_bytes(body)
                    time.sleep(0.3)
                entries.append(
                    ManifestEntry(
                        doc_id=r["pmcid"],
                        bundle_id=f"b-{r['pmcid']}",
                        source="europepmc",
                        license=r["license"],
                        pub_year=r["pub_year"],
                        journal=r["journal"],
                        path=f.relative_to(ROOT).as_posix(),  # Windows에서도 '/'로 저장
                        sha256=file_sha256(f),
                        doi=r["doi"],
                        pmcid=r["pmcid"],
                        title=r["title"],
                        subfields=r["subfields"],
                        retrieved_at=now,
                    )
                )
                have.add(r["pmcid"])
                count[key] += 1
    finally:
        save_manifest(MANIFEST, entries)  # 중간에 멈춰도 받은 만큼은 남긴다
    short = {k: quotas[k] - count[k] for k in queues if count[k] < quotas[k]}
    print("목록", len(entries), "건너뜀", skipped, "모자란 층", short or "없음")


if __name__ == "__main__":
    if sys.argv[1] == "candidates":
        collect_candidates()
    elif sys.argv[1] == "sample":
        download_sample(int(sys.argv[2]))
