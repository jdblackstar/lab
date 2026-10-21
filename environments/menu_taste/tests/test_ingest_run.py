import json

from menu_taste.corpus import load_menus
from menu_taste.ingest.cli import main


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
