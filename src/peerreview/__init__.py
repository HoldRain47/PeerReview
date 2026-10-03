import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="peerreview")
    sub = parser.add_subparsers(dest="command", required=True)
    p_ing = sub.add_parser(
        "ingest", help="논문 파일을 구간 목록으로 바꾸고 원문 없는 요약을 출력한다"
    )
    p_ing.add_argument("file", type=Path)
    p_ing.add_argument("--engine", choices=["pypdf", "pdfplumber"], default=None)
    p_ing.add_argument(
        "--out",
        type=Path,
        help="원문이 들어간 전체 구간을 저장할 JSON 경로(로컬 확인용)",
    )
    p_ins = sub.add_parser(
        "inspect", help="추출 품질을 원문 없이 숫자로 점검한다(비공개 원고 확인용)"
    )
    p_ins.add_argument("file", type=Path)
    p_ins.add_argument("--engine", choices=["pypdf", "pdfplumber"], default=None)
    p_lab = sub.add_parser(
        "check-labels", help="라벨 파일(JSON Lines)의 형식과 판정 규칙을 검사한다"
    )
    p_lab.add_argument("file", type=Path)
    p_man = sub.add_parser(
        "check-manifest", help="자료 목록의 파일·해시·이용 조건·연도를 검사한다"
    )
    p_man.add_argument("file", type=Path)
    p_man.add_argument(
        "--root", type=Path, default=Path("."), help="목록의 path가 기준으로 삼는 폴더"
    )
    args = parser.parse_args(argv)

    # Windows 콘솔 인코딩에서 출력할 수 없는 글자가 있어도 멈추지 않게 한다.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")

    if args.command == "check-manifest":
        from collections import Counter

        from peerreview.manifest import check_manifest, load_manifest

        entries, errors = load_manifest(args.file)
        errors += check_manifest(entries, args.root)
        for e in errors:
            print(e)
        summary = {
            "entries": len(entries),
            "errors": len(errors),
            "journals": Counter(e.journal for e in entries),
            "years": dict(sorted(Counter(e.pub_year for e in entries).items())),
            "subfields": Counter(s for e in entries for s in e.subfields),
        }
        print(json.dumps(summary, ensure_ascii=False))
        return 1 if errors else 0

    if args.command == "check-labels":
        from collections import Counter

        from peerreview.labels import derive_target, load_labels

        records, errors = load_labels(args.file)
        for e in errors:
            print(e)
        counts = Counter(derive_target(r).value for r in records)
        print(
            json.dumps(
                {
                    "records": len(records),
                    "errors": len(errors),
                    "target_present": counts,
                }
            )
        )
        return 1 if errors else 0

    from peerreview.ingest import inspect, load, summarize

    if args.command == "inspect":
        print(
            json.dumps(
                inspect(load(args.file, args.engine)), ensure_ascii=False, indent=1
            )
        )
        return 0

    if args.out and args.out.resolve() == args.file.resolve():
        print(
            "오류: --out이 입력 파일과 같습니다. 원본을 덮어쓰지 않습니다.",
            file=sys.stderr,
        )
        return 2

    doc = load(args.file, args.engine)
    if args.out:
        data = [asdict(s) for s in doc.segments]
        args.out.write_text(
            json.dumps(data, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8",
        )
    print(json.dumps(summarize(doc), ensure_ascii=False, indent=1))
    return 0
