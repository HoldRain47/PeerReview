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
    args = parser.parse_args(argv)

    # Windows 콘솔 인코딩에서 출력할 수 없는 글자가 있어도 멈추지 않게 한다.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")

    from peerreview.ingest import load, summarize

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
