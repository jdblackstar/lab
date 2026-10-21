"""Describe a spreadsheet's structure without revealing its contents.

Prints, per sheet, which cells hold text, numbers, prices, or dates, plus formatting
cues (bold, merged cells, hidden rows), so an import can be designed without anyone
seeing a dish name or client detail. Text is replaced by its length: ``T12b`` is a
bold 12-character string.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

LEGEND = (
    "T<n> text of n chars (b=bold, i=italic, U=all caps, :=ends with colon, "
    "$=contains a price-like token), N number, $ currency-formatted number, "
    "% percent, D date/time, F formula without cached value, . empty"
)


def _cell_code(cell) -> str:
    value = cell.value
    if value is None:
        return "."
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return "D"
    if isinstance(value, bool):
        return "N"
    if isinstance(value, (int, float)):
        fmt = cell.number_format or ""
        if any(sym in fmt for sym in ("$", "€", "£", "[$")) or "Accounting" in fmt:
            return "$"
        if "%" in fmt:
            return "%"
        return "N"
    text = str(value)
    if text.startswith("="):
        return "F"
    code = f"T{len(text.strip())}"
    font = cell.font
    if font is not None and font.b:
        code += "b"
    if font is not None and font.i:
        code += "i"
    letters = [c for c in text if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        code += "U"
    if text.rstrip().endswith(":"):
        code += ":"
    if "$" in text or any(tok.endswith("++") for tok in text.split()):
        code += "$"
    return code


def describe_workbook(
    path: str | Path, *, max_rows: int = 40, show_headers: bool = False
) -> str:
    # formulas: data_only=True reads cached values; F marks formulas never calculated.
    wb = load_workbook(path, data_only=True)
    lines = [
        f"# {Path(path).name}: {len(wb.worksheets)} sheet(s)",
        f"legend: {LEGEND}",
        "",
    ]
    for index, ws in enumerate(wb.worksheets, 1):
        lines.append(
            f"## sheet {index} ({ws.sheet_state}): {ws.max_row} rows x {ws.max_column} cols, "
            f"{len(ws.merged_cells.ranges)} merged range(s)"
        )
        merged = sorted(str(r) for r in ws.merged_cells.ranges)[:10]
        if merged:
            lines.append("merged: " + ", ".join(merged))
        hidden_cols = [k for k, d in ws.column_dimensions.items() if d.hidden]
        if hidden_cols:
            lines.append("hidden columns: " + ", ".join(hidden_cols))
        width = min(ws.max_column, 26)
        header = "row  " + " ".join(
            f"{get_column_letter(c):>5}" for c in range(1, width + 1)
        )
        lines.append(header)
        shown_header = False
        for r_idx, row in enumerate(
            ws.iter_rows(min_row=1, max_row=min(ws.max_row, max_rows), max_col=width), 1
        ):
            codes = [_cell_code(c) for c in row]
            hidden = ws.row_dimensions[r_idx].hidden
            if all(c == "." for c in codes):
                lines.append(f"{r_idx:>3}{'h' if hidden else ' '} (blank)")
                continue
            lines.append(
                f"{r_idx:>3}{'h' if hidden else ' '} "
                + " ".join(f"{c:>5}" for c in codes)
            )
            if show_headers and not shown_header and r_idx <= 15:
                # A header row: at least three short labels and nothing else.
                labels = [str(c.value).strip() for c in row if c.value is not None]
                if (
                    len(labels) >= 3
                    and all(
                        isinstance(c.value, str) for c in row if c.value is not None
                    )
                    and all(len(t) <= 20 for t in labels)
                ):
                    lines.append("     header text: " + " | ".join(labels))
                    shown_header = True
        if ws.max_row > max_rows:
            lines.append(f"... {ws.max_row - max_rows} more row(s)")
        lines.append("")
    return "\n".join(lines)
