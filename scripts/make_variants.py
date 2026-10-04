"""AI 변형본 시범 생성 (T002.5).

공개 CC BY 씨앗 논문만 다룬다(AGENTS.md 4절 예외). 비공개 원고는 다루지 않는다.
API 키는 환경 변수 OPENAI_API_KEY나 저장소 루트의 .env에서 읽고, 화면·파일·기록에 쓰지 않는다.

사용법:
  uv run python scripts/make_variants.py prepare 5          # 씨앗 5편 × 행위 5개 지시 → data/public/variants/tasks.jsonl
  uv run python scripts/make_variants.py models             # 쓸 수 있는 OpenAI 모델 이름만 출력
  uv run python scripts/make_variants.py run-openai MODEL PRICE_IN PRICE_OUT [CAP_USD]
        # PRICE_*: 100만 토큰당 달러. 누적 비용이 CAP_USD(기본 1.0)를 넘기 전에 멈춘다
  uv run python scripts/make_variants.py build              # 변형본 XML·자료 목록·라벨·점검표
"""

import datetime as dt
import json
import os
import random
import sys
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path

from peerreview.ingest import file_sha256
from peerreview.labels import LabelRecord, Span, TruthBasis, save_labels
from peerreview.manifest import ManifestEntry, load_manifest, save_manifest
from peerreview.model import InvolvementAct
from peerreview.variants import (
    Task,
    build_variant_xml,
    check_change,
    final_paragraphs,
    find_target,
    plan_tasks,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
VDIR = DATA / "public" / "variants"
TASKS = VDIR / "tasks.jsonl"
OUT_OPENAI = VDIR / "outputs-openai.jsonl"
OUT_CLAUDE = VDIR / "outputs-claude.jsonl"
MANIFEST = DATA / "manifest.jsonl"
LABELS = DATA / "labels.jsonl"
REPORT = VDIR / "report.json"
SEED = 20261004
FAMILIES = ("claude", "openai")


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [
        json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()
    ]


def _append_jsonl(p: Path, row: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def prepare(n: int) -> None:
    entries, errors = load_manifest(MANIFEST)
    if errors:
        sys.exit("자료 목록 오류: " + "; ".join(errors[:3]))
    # 외부 모델로 보낼 수 있는 것은 이용 조건이 CC BY인 공개 씨앗뿐이다(AGENTS.md 4절 예외 조건)
    seeds = sorted(
        (
            e
            for e in entries
            if e.role == "seed" and e.license == "cc by" and e.source == "europepmc"
        ),
        key=lambda e: e.doc_id,
    )
    random.Random(SEED).shuffle(seeds)
    targets = []
    for e in seeds:
        t = find_target(ROOT / e.path, e.doc_id)
        if t:
            targets.append(t)
        if len(targets) == n:
            break
    tasks = plan_tasks(targets, FAMILIES, SEED)
    VDIR.mkdir(parents=True, exist_ok=True)
    TASKS.write_text(
        "".join(json.dumps(asdict(t), ensure_ascii=False) + "\n" for t in tasks),
        encoding="utf-8",
    )
    print(
        "씨앗",
        [t.seed_id for t in targets],
        "지시",
        len(tasks),
        {f: sum(t.model_family == f for t in tasks) for f in FAMILIES},
    )


def _api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("OPENAI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit("OPENAI_API_KEY가 없습니다(환경 변수 또는 저장소 루트 .env).")
    return key


def _openai(path: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"https://api.openai.com/v1/{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        # 응답 본문에는 키가 없지만, 혹시 몰라 오류 종류와 코드만 낸다
        sys.exit(f"OpenAI 요청 실패: HTTP {e.code}")


def list_models() -> None:
    ids = sorted(m["id"] for m in _openai("models")["data"])
    print("\n".join(i for i in ids if i.startswith(("gpt", "o", "chatgpt"))))


def run_openai(model: str, price_in: float, price_out: float, cap: float) -> None:
    tasks = [Task(**t) for t in _read_jsonl(TASKS) if t["model_family"] == "openai"]
    done = {r["variant_id"] for r in _read_jsonl(OUT_OPENAI)}
    spent = sum(r.get("cost_usd", 0) for r in _read_jsonl(OUT_OPENAI))
    for t in tasks:
        if t.variant_id in done:
            continue
        outputs, usage_in, usage_out, returned = [], 0, 0, model
        prev = ""
        for step in t.steps:
            # 다음 호출 비용을 넉넉히(입력 글자 수/3 토큰 + 출력 2,000 토큰) 어림해 상한을 넘으면 멈춘다
            est = (len(step) / 3 * price_in + 2000 * price_out) / 1e6
            if spent + est > cap:
                print(f"비용 상한 {cap}달러에 닿아 멈춤. 지금까지 {spent:.4f}달러")
                return
            msg = step.replace("{PREVIOUS_OUTPUT}", prev)
            resp = _openai(
                "chat/completions",
                {"model": model, "messages": [{"role": "user", "content": msg}]},
            )
            prev = resp["choices"][0]["message"]["content"]
            outputs.append(prev)
            u = resp.get("usage", {})
            usage_in += u.get("prompt_tokens", 0)
            usage_out += u.get("completion_tokens", 0)
            returned = resp.get("model", model)
            spent += (
                u.get("prompt_tokens", 0) * price_in
                + u.get("completion_tokens", 0) * price_out
            ) / 1e6
        cost = (usage_in * price_in + usage_out * price_out) / 1e6
        _append_jsonl(
            OUT_OPENAI,
            {
                "variant_id": t.variant_id,
                "model": returned,
                "step_outputs": outputs,
                "created_at": _now(),
                "usage": {"input_tokens": usage_in, "output_tokens": usage_out},
                "cost_usd": round(cost, 6),
            },
        )
        print(t.variant_id, f"{cost:.4f}달러, 누적 {spent:.4f}달러")


def build() -> None:
    tasks = {t["variant_id"]: Task(**t) for t in _read_jsonl(TASKS)}
    outputs = {
        r["variant_id"]: r for r in _read_jsonl(OUT_OPENAI) + _read_jsonl(OUT_CLAUDE)
    }
    entries, errors = load_manifest(MANIFEST)
    if errors:
        sys.exit("자료 목록 오류: " + "; ".join(errors[:3]))
    by_id = {e.doc_id: e for e in entries}
    entries = [e for e in entries if e.role != "variant" or e.doc_id not in tasks]
    labels: dict[str, LabelRecord] = {}
    report = []
    for vid, t in sorted(tasks.items()):
        out = outputs.get(vid)
        seed = by_id[t.seed_id]
        labels.setdefault(
            seed.doc_id,
            LabelRecord(
                seed.doc_id,
                seed.bundle_id,
                TruthBasis.D,
                notes="AI 보급 이전 공개 씨앗",
            ),
        )
        if out is None:
            report.append({"variant_id": vid, "status": "출력 없음"})
            continue
        new = final_paragraphs(t, out["step_outputs"][-1])
        if new is None:
            report.append({"variant_id": vid, "status": "문단 수가 맞지 않음"})
            continue
        target = find_target(ROOT / seed.path, seed.doc_id)
        chk = check_change(t, target.paragraphs, new)
        xml = VDIR / "xml" / f"{vid}.xml"
        build_variant_xml(ROOT / seed.path, t.target_locs, new, xml)
        entries.append(
            ManifestEntry(
                doc_id=vid,
                bundle_id=seed.bundle_id,
                source="variant",
                license=seed.license,
                pub_year=seed.pub_year,
                journal=seed.journal,
                path=xml.relative_to(ROOT).as_posix(),
                sha256=file_sha256(xml),
                pmcid=seed.pmcid,
                title=seed.title,
                subfields=seed.subfields,
                role="variant",
                truth_basis="A",
                retrieved_at=out["created_at"],
            )
        )
        act = InvolvementAct(chk.label_act)
        labels[vid] = LabelRecord(
            vid,
            seed.bundle_id,
            TruthBasis.A,
            acts=[act],
            spans=[Span(act, loc) for loc in t.target_locs],
            checked_scope="서론 앞 3문단만 바꿈. 나머지는 씨앗 원문(근거 D)",
            rest_basis=TruthBasis.D,
            tools=[out["model"]],
            notes=f"의도한 행위 {t.act}. {chk.note}".strip(),
        )
        report.append(
            {
                "variant_id": vid,
                "status": "ok",
                "intended": t.act,
                "label": chk.label_act,
                "similarity": chk.similarity,
                "sentence_delta": chk.sentence_delta,
                "model": out["model"],
                "note": chk.note,
            }
        )
    save_manifest(MANIFEST, entries)
    save_labels(LABELS, list(labels.values()))
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    ok = [r for r in report if r["status"] == "ok"]
    print(
        "변형본",
        len(ok),
        "/",
        len(report),
        "라벨 변경",
        sum(r["intended"] != r["label"] for r in ok),
    )


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "prepare":
        prepare(int(sys.argv[2]))
    elif cmd == "models":
        list_models()
    elif cmd == "run-openai":
        cap = float(sys.argv[5]) if len(sys.argv) > 5 else 1.0
        run_openai(sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), cap)
    elif cmd == "build":
        build()
