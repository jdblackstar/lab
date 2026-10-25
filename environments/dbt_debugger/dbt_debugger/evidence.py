"""How an evidence ref grounds a fact in the scenario spec.

An evidence ref is the small JSON object that ``add_file_evidence``,
``add_sample_rows_evidence``, and ``add_run_history_evidence`` store in the rollout
state. ``rubric_hints.required_evidence`` entries name the facts a diagnosis must cite
in the same vocabulary. This module is the one place that resolves either against the
spec, so the tool server (checking a ref before storing it), scoring (checking stored
refs against requirements), and the offline validator (checking that every requirement
is satisfiable) cannot drift apart.
"""

from __future__ import annotations

import json
from typing import Any

from dbt_debugger.claim_text_matching import text_contains_option
from dbt_debugger.sample_rows import matching_sample_rows

RUN_HISTORY_RECORD_TYPES = frozenset({"summary", "model", "test", "warning"})
RECORD_NAME_KEY = {"model": "model", "test": "name"}
"""Field that names a ``model``/``test`` record, in refs, requirements, and records."""
RECORD_LIST_KEY = {"model": "model_results", "test": "tests"}
"""``run_history`` list holding the ``model``/``test`` records."""


def project_files(spec: dict[str, Any]) -> dict[str, str]:
    """Return ``path -> content`` for the bundled dbt project files."""
    return {entry["path"]: entry["content"] for entry in spec["dbt_project"]["files"]}


def parse_match_json(match_json: str) -> dict[str, Any]:
    """Parse a sample-row match into a non-empty object of scalar values."""
    if not match_json.strip():
        raise ValueError("sample_rows evidence requires non-empty match_json")
    try:
        raw = json.loads(match_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"match_json must be valid JSON: {exc}") from exc
    if not isinstance(raw, dict) or not raw:
        raise ValueError("match_json must decode to a non-empty object")
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if not key.strip():
            raise ValueError("match_json keys must be non-empty strings")
        if not (value is None or isinstance(value, (str, int, float, bool))):
            raise ValueError("match_json values must be JSON scalar values")
        out[key.strip()] = value
    return out


def missing_anchors(text: str, anchors: list[str]) -> list[str]:
    """Return the ``all_of`` anchors that *text* does not contain."""
    return [anchor for anchor in anchors if not text_contains_option(text, anchor)]


def cited_lines(ref: dict[str, Any], files: dict[str, str]) -> str | None:
    """Return the lines a ``file_span`` ref cites, or None if it cites no bundled file."""
    content = files.get(ref.get("path"))
    start, end = int(ref.get("start_line", 0)), int(ref.get("end_line", 0))
    if content is None or start < 1 or end < start:
        return None
    return "\n".join(content.splitlines()[start - 1 : end])


def run_history_entries(record_type: str, run_history: dict[str, Any]) -> list[Any]:
    """Return the run-history entries of one record type: the summary string, the
    warning strings, or the ``model``/``test`` result records."""
    if record_type == "summary":
        return [str(run_history.get("summary", ""))]
    if record_type == "warning":
        return list(run_history.get("warnings", []))
    return list(run_history.get(RECORD_LIST_KEY[record_type]) or [])


def entry_matches(entry: Any, filters: dict[str, Any]) -> bool:
    """Return whether one run-history entry passes the name, status, and ``contains``
    filters of *filters*, an evidence ref or a requirement; blank filters match all."""
    record_type = filters["record_type"]
    contains = str(filters.get("contains", "")).strip()
    if record_type in ("summary", "warning"):
        return not contains or text_contains_option(entry, contains)
    name_key = RECORD_NAME_KEY[record_type]
    name = str(filters.get(name_key, "")).strip()
    status = str(filters.get("status", "")).strip().lower()
    if name and str(entry.get(name_key, "")).strip() != name:
        return False
    if status and str(entry.get("status", "")).strip().lower() != status:
        return False
    return not contains or text_contains_option(
        json.dumps(entry, sort_keys=True), contains
    )


def evidence_matches(
    ref: dict[str, Any], requirement: dict[str, Any], spec: dict[str, Any]
) -> bool:
    """Return whether stored evidence *ref* satisfies one ``required_evidence`` entry.

    The ref must cite the same artifact (file path, sample table, or run-history record
    type), its citation must still select the records the requirement names, and the
    requirement's ``all_of`` anchors must appear in what it cites.
    """
    kind = requirement["kind"]
    if ref.get("kind") != kind:
        return False
    if kind == "file_span":
        if ref.get("path") != requirement["path"]:
            return False
        segment = cited_lines(ref, project_files(spec))
        return segment is not None and not missing_anchors(
            segment, requirement["all_of"]
        )
    if kind == "sample_rows":
        table = requirement["table"]
        if ref.get("table") != table or table not in spec["sample_data"]:
            return False
        try:
            match = parse_match_json(str(ref.get("match_json", "")))
        except ValueError:
            return False
        if any(match.get(key) != value for key, value in requirement["match"].items()):
            return False
        rows = matching_sample_rows(spec["sample_data"][table], match)
        if len(rows) < requirement.get("min_rows", 1):
            return False
        return not missing_anchors(
            json.dumps(rows, sort_keys=True), requirement["all_of"]
        )
    if ref.get("record_type") != requirement["record_type"]:
        return False
    return any(
        entry_matches(entry, ref) and entry_matches(entry, requirement)
        for entry in run_history_entries(requirement["record_type"], spec["run_history"])
    )
