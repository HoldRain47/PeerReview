"""AI가 화학식 첨자를 어떤 표기로 내놓는지 확인한다 (T002.5b).

공개 CC BY 씨앗 논문만 쓴다. 서식(첨자 표기)에 대한 지시는 넣지 않는다.
사용법:
  uv run python scripts/subscript_probe.py prepare 5
  uv run python scripts/subscript_probe.py run-openai MODEL PRICE_IN PRICE_OUT [CAP_USD]
  (Claude 출력은 하위 에이전트가 data/public/variants/subscript/outputs-claude.jsonl에 쓴다)
  uv run python scripts/subscript_probe.py report
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_variants as mv

from peerreview.ingest import format_traces
from peerreview.manifest import load_manifest
from peerreview.variants import find_target

DIR = mv.DATA / "public" / "variants" / "subscript"
TASKS = DIR / "tasks.jsonl"
OUT_OPENAI = DIR / "outputs-openai.jsonl"
OUT_CLAUDE = DIR / "outputs-claude.jsonl"
# 서식 없는 글자로 쓴 화학식: 원소 기호 다음 숫자(CO2, Fe3O4, H2O)
PLAIN_FORMULA = re.compile(r"\b(?:[A-Z][a-z]?\d+)+(?:[A-Z][a-z]?\d*)*\b")


def _sub_count(xml_path: Path) -> int:
    root = ET.parse(xml_path).getroot()
    return sum(1 for ab in root.iter("abstract") for _ in ab.iter("sub"))


def prepare(n: int) -> None:
    entries, _ = load_manifest(mv.MANIFEST)
    seeds = [e for e in entries if e.role == "seed" and e.license == "cc by"]
    scored = []
    for e in seeds:
        t = find_target(mv.ROOT / e.path, e.doc_id)
        if not t:
            continue
        intro_formulas = sum(len(PLAIN_FORMULA.findall(p)) for p in t.paragraphs)
        scored.append(
            (min(_sub_count(mv.ROOT / e.path), 10) + intro_formulas, e.doc_id, t)
        )
    scored.sort(key=lambda x: (-x[0], x[1]))
    tasks = []
    for _, doc_id, t in scored[:n]:
        joined = "\n\n".join(t.paragraphs)
        prompts = {
            "generation": (
                f'I am writing a research article titled "{t.title}".\n\nAbstract:\n{t.abstract}\n\n'
                "Write the first 3 paragraphs of the Introduction."
            ),
            "rewriting": (
                "Rewrite the following paragraphs from my paper to improve clarity and academic style."
                f"\n\n{joined}"
            ),
        }
        for cond, prompt in prompts.items():
            for fam in mv.FAMILIES:
                tasks.append(
                    {
                        "variant_id": f"{doc_id}-{cond}-{fam}",
                        "seed_id": doc_id,
                        "condition": cond,
                        "model_family": fam,
                        "steps": [prompt],
                        "input_traces": format_traces(prompt),
                        "input_plain_formulas": len(PLAIN_FORMULA.findall(prompt)),
                    }
                )
    DIR.mkdir(parents=True, exist_ok=True)
    TASKS.write_text(
        "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in tasks),
        encoding="utf-8",
    )
    print("씨앗", [s[1] for s in scored[:n]], "지시", len(tasks))


def run_openai(model: str, price_in: float, price_out: float, cap: float) -> None:
    done = {r["variant_id"] for r in mv._read_jsonl(OUT_OPENAI)}
    spent = sum(r.get("cost_usd", 0) for r in mv._read_jsonl(OUT_OPENAI))
    for t in mv._read_jsonl(TASKS):
        if t["model_family"] != "openai" or t["variant_id"] in done:
            continue
        est = (len(t["steps"][0]) / 3 * price_in + 2000 * price_out) / 1e6
        if spent + est > cap:
            print(f"비용 상한 {cap}달러에 닿아 멈춤. 지금까지 {spent:.4f}달러")
            return
        resp = mv._openai(
            "chat/completions",
            {"model": model, "messages": [{"role": "user", "content": t["steps"][0]}]},
        )
        u = resp.get("usage", {})
        cost = (
            u.get("prompt_tokens", 0) * price_in
            + u.get("completion_tokens", 0) * price_out
        ) / 1e6
        spent += cost
        mv._append_jsonl(
            OUT_OPENAI,
            {
                "variant_id": t["variant_id"],
                "model": resp.get("model", model),
                "step_outputs": [resp["choices"][0]["message"]["content"]],
                "created_at": mv._now(),
                "usage": {
                    "input_tokens": u.get("prompt_tokens", 0),
                    "output_tokens": u.get("completion_tokens", 0),
                },
                "cost_usd": round(cost, 6),
            },
        )
        print(t["variant_id"], f"{cost:.4f}달러, 누적 {spent:.4f}달러")


def report() -> None:
    tasks = {t["variant_id"]: t for t in mv._read_jsonl(TASKS)}
    rows = []
    for o in mv._read_jsonl(OUT_OPENAI) + mv._read_jsonl(OUT_CLAUDE):
        t = tasks[o["variant_id"]]
        text = o["step_outputs"][-1]
        tr = format_traces(text)
        rows.append(
            {
                "variant_id": o["variant_id"],
                "condition": t["condition"],
                "family": t["model_family"],
                "model": o["model"],
                "input_traces": t["input_traces"],
                "output_traces": tr,
                "plain_formulas": len(PLAIN_FORMULA.findall(text)),
                "markdown_bold": text.count("**"),
            }
        )
    (DIR / "report.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    for r in sorted(rows, key=lambda r: (r["condition"], r["family"], r["variant_id"])):
        print(
            r["condition"],
            r["family"],
            r["model"],
            "흔적",
            r["output_traces"] or "-",
            "평문 화학식",
            r["plain_formulas"],
            "굵게",
            r["markdown_bold"],
            "입력흔적",
            r["input_traces"] or "-",
        )


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "prepare":
        prepare(int(sys.argv[2]))
    elif cmd == "run-openai":
        run_openai(
            sys.argv[2],
            float(sys.argv[3]),
            float(sys.argv[4]),
            float(sys.argv[5]) if len(sys.argv) > 5 else 1.0,
        )
    elif cmd == "report":
        report()
