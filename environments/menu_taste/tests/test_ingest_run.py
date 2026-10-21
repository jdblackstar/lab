import json

from menu_taste.corpus import load_menus
from menu_taste.ingest.cli import iter_files, main


def _record(menu_id: str) -> dict:
    return {
        "menu_id": menu_id,
        "kind": "event",
        "service": "plated",
        "source": {"sha256": "a" * 64, "media_type": "application/pdf"},
        "sections": [
            {
                "course": "main",
                "items": [{"name": "Halibut", "description": "peas, morels $12"}],
            }
        ],
    }


def _run_twice(tmp_path):
    src = tmp_path / "menus.jsonl"
    src.write_text(json.dumps(_record("m1")) + "\n" + json.dumps(_record("m2")) + "\n")
    out = tmp_path / "out" / "corpus.jsonl"
    for _ in range(2):
        assert main(["run", str(src), "-o", str(out)]) == 0
    return load_menus(out)


def test_canonical_json_records_are_redacted(tmp_path):
    menus = _run_twice(tmp_path)
    assert {m.sections[0].items[0].description for m in menus} == {"peas, morels"}


def test_rerunning_canonical_json_does_not_duplicate_menus(tmp_path):
    menus = _run_twice(tmp_path)
    assert sorted(m.menu_id for m in menus) == ["m1", "m2"]


def test_symlinks_inside_a_menus_folder_are_not_loaded(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("private key")
    menus = tmp_path / "menus"
    menus.mkdir()
    (menus / "real.txt").write_text("Halibut, peas")
    (menus / "menu.txt").symlink_to(secret)
    (menus / "linked_dir").symlink_to(tmp_path, target_is_directory=True)
    assert iter_files([str(menus)]) == [menus / "real.txt"]


def test_rerun_keeps_extractor_notes_for_documents_it_skips(tmp_path):
    import hashlib

    src = tmp_path / "menu.txt"
    src.write_text("Halibut, peas")
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    out = tmp_path / "out" / "corpus.jsonl"
    record = _record("m1")
    record["source"]["sha256"] = sha
    out.parent.mkdir()
    out.write_text(json.dumps(record) + "\n")
    cache = out.parent / ".extract-cache" / f"{sha}.json"
    cache.parent.mkdir()
    cache.write_text(json.dumps({"menus": [], "document_notes": ["page 2 illegible"]}))

    assert main(["run", str(src), "-o", str(out)]) == 0
    assert "page 2 illegible" in out.with_suffix(".review.md").read_text()


def test_an_unreadable_file_is_skipped_not_fatal(tmp_path, monkeypatch):
    from pathlib import Path

    from menu_taste.ingest.cli import load_docs

    menus = tmp_path / "menus"
    menus.mkdir()
    (menus / "good.txt").write_text("Halibut, peas")
    (menus / "bad.txt").write_text("Lemon tart")
    read_bytes = Path.read_bytes

    def fail_on_bad(self):
        if self.name == "bad.txt":
            raise PermissionError("Permission denied")
        return read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", fail_on_bad)
    docs = load_docs([str(menus)])
    assert {Path(d.path).name: d.error for d in docs} == {
        "bad.txt": "Permission denied",
        "good.txt": None,
    }
