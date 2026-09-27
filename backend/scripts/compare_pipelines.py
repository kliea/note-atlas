"""Compare variants of the Files pipeline on a folder's questions (Files F7).

From backend/:

    .venv/bin/python scripts/compare_pipelines.py ../lab/eval_questions.yaml
    .venv/bin/python scripts/compare_pipelines.py ../lab/eval_questions.yaml --variants baseline,hybrid
    .venv/bin/python scripts/compare_pipelines.py questions.yaml --folder Lectures --rebuild

Needs `ollama serve` with phi3 and nomic-embed-text (plus qwen3:4b for that variant). Writes a
CSV and a Markdown table to data/eval/. Your real index and Chat History are not touched.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.files import compare  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("questions", type=Path, help="YAML question file (see lab/eval_questions.yaml)")
    parser.add_argument("--folder", help="Files folder name or id (overrides `folder:` in the file)")
    parser.add_argument(
        "--variants",
        help="comma-separated variant names to run (default: those in the file, else "
        + ", ".join(v.name for v in compare.DEFAULT_VARIANTS)
        + ")",
    )
    parser.add_argument("--out", type=Path, default=BACKEND.parent / "data" / "eval", help="output directory")
    parser.add_argument("--rebuild", action="store_true", help="rebuild every index even if unchanged")
    args = parser.parse_args(argv)

    plan = compare.load_plan(args.questions)
    if args.variants:
        wanted = [name.strip() for name in args.variants.split(",") if name.strip()]
        by_name = {v.name: v for v in [*plan.variants, *compare.DEFAULT_VARIANTS]}
        missing = [name for name in wanted if name not in by_name]
        if missing:
            parser.error(f"unknown variants: {', '.join(missing)} (known: {', '.join(by_name)})")
        plan.variants = [by_name[name] for name in wanted]

    _, csv_path, md_path = compare.run(plan, args.out, folder=args.folder, rebuild=args.rebuild)
    print()
    print(md_path.read_text(encoding="utf-8").split("\n## Per question")[0])
    print(f"CSV:      {csv_path}")
    print(f"Markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
