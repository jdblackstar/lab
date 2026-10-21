"""menu-taste-ingest: turn a folder of menu files into a canonical JSONL corpus.

    menu-taste-ingest inspect ~/menus/                 # what was found, no API calls
    menu-taste-ingest layout ~/menus/*.xlsx            # sheet structure, cell text hidden
    menu-taste-ingest run ~/menus/ -o private/menus.jsonl
    menu-taste-ingest stats private/menus.jsonl
    menu-taste-ingest render private/menus.jsonl --id 3f9a1c2b7d10-0

``run`` is resumable: documents already in the output (matched by content hash) are
skipped, so re-running after adding files only processes the new ones. Each model
response is cached under ``--cache-dir`` for auditing. A ``.review.md`` file next to the
output lists every menu with warnings that need a human look before the corpus is used.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..cloze import build_cloze_items
from ..corpus import load_menus, write_menus
from ..render import render_menu
from ..schema import Menu, MenuKind, SourceRef
from .redact import redact_menu
from .sources import SourceDoc, load_path


def iter_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            root = p.resolve()
            for f in sorted(p.rglob("*")):
                if any(part.startswith(".") for part in f.relative_to(p).parts):
                    continue
                # A link in a menus folder could point at any file the user can
                # read, and its bytes would go to the model provider.
                if f.is_symlink() or not f.resolve().is_relative_to(root):
                    print(
                        f"warning: skipping {f}: symlink or outside {p}",
                        file=sys.stderr,
                    )
                    continue
                if f.is_file():
                    files.append(f)
        elif p.is_file():
            files.append(p)
        else:
            print(f"warning: {p} does not exist", file=sys.stderr)
    return files


def load_docs(paths: list[str]) -> list[SourceDoc]:
    return [doc for f in iter_files(paths) for doc in load_path(f)]


def cmd_inspect(args) -> int:
    for doc in load_docs(args.paths):
        if doc.error:
            print(f"SKIP  {doc.path}: {doc.error}")
            continue
        if doc.menus_json is not None:
            print(f"JSON  {doc.path}: {len(doc.menus_json)} record(s)")
            continue
        kinds = Counter(p.kind for p in doc.parts)
        size = sum(len(p.data) for p in doc.parts)
        summary = ", ".join(f"{n} {k}" for k, n in kinds.items())
        notes = f" ({'; '.join(doc.notes)})" if doc.notes else ""
        print(
            f"OK    {doc.path}: {doc.media_type} -> {summary}, {size / 1024:.0f} KB{notes}"
        )
    return 0


def _menus_from_json(doc: SourceDoc) -> list[Menu]:
    menus = []
    for i, record in enumerate(doc.menus_json or []):
        record = dict(record)
        record.setdefault("menu_id", f"{doc.sha256[:12]}-{i}")
        record.setdefault(
            "source",
            {"sha256": doc.sha256, "media_type": doc.media_type, "index_in_source": i},
        )
        menus.append(redact_menu(Menu.model_validate(record)))
    return menus


def _process(doc: SourceDoc, args, client) -> tuple[list[Menu], list[str]]:
    from .extract import extract_menus

    if doc.menus_json is not None:
        return _menus_from_json(doc), []
    cache = Path(args.cache_dir) / f"{doc.sha256}.json" if args.cache_dir else None
    if cache and cache.exists() and not args.force:
        from .extract import ExtractionResult

        result = ExtractionResult.model_validate_json(cache.read_text())
    else:
        result = extract_menus(
            doc,
            client=client,
            model=args.model,
            effort=args.effort,
            use_fallbacks=not args.no_fallbacks,
        )
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(result.model_dump_json(indent=2))
    menus = []
    for i, body in enumerate(result.menus):
        menu = Menu(
            **body.model_dump(),
            menu_id=f"{doc.sha256[:12]}-{i}",
            source=SourceRef(
                sha256=doc.sha256,
                media_type=doc.media_type,
                index_in_source=i,
                extractor=args.model,
            ),
        )
        menus.append(redact_menu(menu))
    return menus, result.document_notes


def cmd_run(args) -> int:
    out = Path(args.output)
    existing = load_menus(out) if out.exists() else []
    done = {m.source.sha256 for m in existing if m.source}
    docs = load_docs(args.paths)
    todo, skipped = [], []
    doc_notes: dict[str, list[str]] = {}
    for doc in docs:
        if doc.error:
            skipped.append(f"{doc.path}: {doc.error}")
        elif doc.sha256 in done and not args.force:
            # Keep this document's extractor notes in the rewritten review file.
            cache = (
                Path(args.cache_dir) / f"{doc.sha256}.json" if args.cache_dir else None
            )
            if cache and cache.exists():
                notes = json.loads(cache.read_text()).get("document_notes")
                if notes:
                    doc_notes[doc.path] = notes
            continue
        else:
            todo.append(doc)
            done.add(doc.sha256)  # the same file attached twice is processed once
    if args.force:
        redo = {d.sha256 for d in todo}
        existing = [m for m in existing if not m.source or m.source.sha256 not in redo]

    client = None
    if any(d.menus_json is None for d in todo):
        import os

        import anthropic

        client = anthropic.Anthropic(
            base_url=args.base_url, api_key=os.environ.get(args.api_key_env)
        )

    print(
        f"{len(todo)} document(s) to process, {len(docs) - len(todo) - len(skipped)} already done or duplicate, "
        f"{len(skipped)} unreadable"
    )
    menus = list(existing)
    failures = list(skipped)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_process, d, args, client): d for d in todo}
        for fut in as_completed(futures):
            doc = futures[fut]
            try:
                new, notes = fut.result()
            except Exception as e:  # noqa: BLE001 - one bad document shouldn't stop a batch
                failures.append(f"{doc.path}: {type(e).__name__}: {e}")
                print(f"FAIL  {doc.path}: {e}", file=sys.stderr)
                continue
            # Replace, not append: canonical JSON keeps its records' original
            # provenance, so a rerun can't tell it was done and reprocesses it.
            ids = {m.menu_id for m in new}
            menus = [m for m in menus if m.menu_id not in ids] + new
            if notes:
                doc_notes[doc.path] = notes
            print(f"done  {doc.path}: {len(new)} menu(s)")
            write_menus(menus, out)  # checkpoint after every document

    write_menus(menus, out)
    review = out.with_suffix(".review.md")
    review.write_text(review_report(menus, doc_notes, failures))
    print(f"wrote {len(menus)} menu(s) to {out}; review notes in {review}")
    return 1 if failures and not menus else 0


def review_report(
    menus: list[Menu], doc_notes: dict[str, list[str]], failures: list[str]
) -> str:
    lines = ["# Menu ingest review", ""]
    flagged = [m for m in menus if m.warnings]
    lines.append(
        f"{len(menus)} menus, {len(flagged)} with warnings, {len(failures)} failed files."
    )
    lines.append("")
    if failures:
        lines += (
            ["## Failed or skipped files", ""] + [f"- {f}" for f in failures] + [""]
        )
    if doc_notes:
        lines += ["## Extractor notes", ""]
        for path, notes in doc_notes.items():
            lines += [f"- {path}: {n}" for n in notes]
        lines.append("")
    if flagged:
        lines += ["## Warnings (check for client details before using the corpus)", ""]
        for m in flagged:
            lines.append(f"### {m.menu_id} — {m.title or '(untitled)'}")
            lines += [f"- {w}" for w in m.warnings] + [""]
    return "\n".join(lines)


def cmd_layout(args) -> int:
    from .layout import describe_workbook

    for f in iter_files(args.paths):
        if f.suffix.lower() in (".xlsx", ".xlsm"):
            print(describe_workbook(f, max_rows=args.rows, show_headers=args.headers))
    return 0


def cmd_import_grid(args) -> int:
    from .grid import import_grid

    menus, report = import_grid(
        args.path, scrub_file=args.scrub_file, pair_columns=args.pairs
    )
    out = Path(args.output)
    write_menus(menus, out)
    review = out.with_suffix(".review.md")
    review.write_text(review_report(menus, {}, []))
    print(json.dumps({"menus": len(menus), **report}, indent=2))
    print(f"wrote {out}; review notes in {review}")
    return 0


def cmd_stats(args) -> int:
    menus = load_menus(args.corpus)
    kinds = Counter(m.kind.value for m in menus)
    service = Counter(m.service.value for m in menus)
    courses = Counter(s.course.value for m in menus for s in m.sections)
    items = sum(len(s.items) for m in menus for s in m.sections)
    rows = build_cloze_items(menus, num_options=args.num_options)
    by_course = Counter(r["info"]["course"] for r in rows)
    report = {
        "menus": len(menus),
        "items": items,
        "kind": dict(kinds),
        "service": dict(service),
        "sections_by_course": dict(courses.most_common()),
        "cloze_questions": len(rows),
        "cloze_by_course": dict(by_course.most_common()),
        "cloze_eligible_menus": sum(
            1 for m in menus if m.kind in (MenuKind.event, MenuKind.sample)
        ),
        "menus_with_warnings": sum(1 for m in menus if m.warnings),
    }
    print(json.dumps(report, indent=2))
    return 0


def cmd_render(args) -> int:
    for m in load_menus(args.corpus):
        if args.id and m.menu_id not in args.id:
            continue
        print(f"=== {m.menu_id} [{m.kind.value}] {m.title or ''}")
        print(render_menu(m, verbatim_headings=True, include_notes=True))
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    from .extract import DEFAULT_EFFORT, DEFAULT_MODEL

    parser = argparse.ArgumentParser(
        prog="menu-taste-ingest",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser(
        "inspect", help="List detected files and parts without calling a model"
    )
    p.add_argument("paths", nargs="+")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser(
        "layout",
        help="Describe spreadsheet structure with all cell text hidden (safe to share)",
    )
    p.add_argument("paths", nargs="+")
    p.add_argument("--rows", type=int, default=40, help="Rows to show per sheet")
    p.add_argument(
        "--headers",
        action="store_true",
        help="Also show the text of the first row that looks like column labels (check it before sharing)",
    )
    p.set_defaults(func=cmd_layout)

    p = sub.add_parser("run", help="Extract menus into a JSONL corpus")
    p.add_argument("paths", nargs="+")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument(
        "--effort",
        default=DEFAULT_EFFORT,
        choices=["low", "medium", "high", "xhigh", "max"],
    )
    p.add_argument(
        "--base-url",
        default=None,
        help="Anthropic-compatible endpoint, e.g. https://api.pinference.ai/api",
    )
    p.add_argument(
        "--api-key-env",
        default="ANTHROPIC_API_KEY",
        help="Environment variable holding the key for that endpoint",
    )
    p.add_argument(
        "--no-fallbacks",
        action="store_true",
        help="Skip server-side refusal fallbacks (for endpoints that don't support them)",
    )
    p.add_argument("--workers", type=int, default=4)
    p.add_argument(
        "--cache-dir", default=None, help="Defaults to <output dir>/.extract-cache"
    )
    p.add_argument(
        "--force", action="store_true", help="Re-extract documents already done"
    )
    p.set_defaults(func=cmd_run)

    p = sub.add_parser(
        "import-grid",
        help="Import a spreadsheet where each row is a menu of (title, description) column pairs",
    )
    p.add_argument("path")
    p.add_argument("-o", "--output", required=True)
    p.add_argument(
        "--scrub-file",
        help="Names to remove (business, suppliers, venues), one per line. Keep it private.",
    )
    p.add_argument(
        "--pairs", type=int, default=None, help="Number of column pairs (default: all)"
    )
    p.set_defaults(func=cmd_import_grid)

    p = sub.add_parser(
        "stats", help="Summarize a corpus and how many questions it yields"
    )
    p.add_argument("corpus")
    p.add_argument("--num-options", type=int, default=4)
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("render", help="Print menus as text for eyeballing")
    p.add_argument("corpus")
    p.add_argument("--id", nargs="*")
    p.set_defaults(func=cmd_render)

    args = parser.parse_args(argv)
    if args.cmd == "run" and args.cache_dir is None:
        args.cache_dir = str(Path(args.output).parent / ".extract-cache")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
