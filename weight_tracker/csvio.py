"""Read weigh-ins from CSV, and write them back out.

Import is meant to take whatever the user has: this app's own export, a spreadsheet
they kept by hand, or another app's export (Withings, Fitbit, Renpho, Google Fit and
the like all put a date column and a weight column in their CSVs). Columns are found
by their header; a file with no header is read as date, weight[, unit].
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass, field

from .store import Entry, validate

DATE_WORDS = ("date", "日期", "timestamp")
TIME_WORDS = ("time", "时间")
WEIGHT_WORDS = ("weight", "体重", "body mass", "bodymass")
# "Fat weight", "Muscle weight", "Goal weight"... are not the body weight.
NOT_WEIGHT_WORDS = ("fat", "muscle", "bone", "water", "lean", "goal", "target", "bmi", "目标", "脂", "肌", "骨", "水")
UNIT_WORDS = ("unit", "单位")

UNIT_NAMES = {
    "kg": "kg", "kgs": "kg", "公斤": "kg", "千克": "kg",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb", "磅": "lb",
    "斤": "jin",
}

# Slash dates are read month first (10/12/2026 = Oct 12), as US apps write them.
DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日", "%d.%m.%Y",
    "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y", "%d %b %Y",
)
TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p", "%I:%M%p")

MAX_ERRORS = 20

HEADER = ["date", "time", "weight", "unit", "note"]


@dataclass
class ImportResult:
    entries: list[Entry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # first MAX_ERRORS, for showing the user
    error_count: int = 0

    def error(self, message: str) -> None:
        self.error_count += 1
        if len(self.errors) < MAX_ERRORS:
            self.errors.append(message)


def parse_time(text: str) -> str:
    """'7:31', '07:31:05', '7:31 AM' -> 'HH:MM'."""
    for fmt in TIME_FORMATS:
        try:
            return dt.datetime.strptime(text.strip(), fmt).strftime("%H:%M")
        except ValueError:
            continue
    raise ValueError(f"看不懂时间 {text!r}")


def parse_datetime(text: str) -> tuple[dt.date, str | None]:
    """'2026-10-12 07:31', '10/12/2026 7:31 AM', '2026年10月12日'... -> (date, 'HH:MM' or None)."""
    s = " ".join(text.split())
    has_time = ":" in s
    try:
        value = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        value = None
    if value is not None:
        if value.tzinfo is not None:  # an instant: show it in local time, where it was taken
            value = value.astimezone().replace(tzinfo=None)
        return value.date(), value.strftime("%H:%M") if has_time else None

    for dfmt in DATE_FORMATS:
        for fmt in [f"{dfmt} {tfmt}" for tfmt in TIME_FORMATS] if has_time else [dfmt]:
            try:
                value = dt.datetime.strptime(s, fmt)
            except ValueError:
                continue
            return value.date(), value.strftime("%H:%M") if has_time else None
    raise ValueError(f"看不懂日期 {text!r}")


def parse_weight(text: str) -> tuple[float, str | None]:
    """'165.4', '165.4 lb', '75,3kg', '150斤' -> (number, 'lb' / 'kg' / 'jin' / None)."""
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*([A-Za-z\u4e00-\u9fff]*)\.?\s*", text)
    if not m:
        raise ValueError(f"看不懂体重 {text!r}")
    unit_text = m.group(2).lower()
    if unit_text and unit_text not in UNIT_NAMES:
        raise ValueError(f"不认识的单位 {m.group(2)!r}")
    return float(m.group(1).replace(",", ".")), UNIT_NAMES.get(unit_text)


def _unit_in(text: str) -> str | None:
    """Unit named in a header like 'Weight (kg)' or '体重(斤)'."""
    t = text.lower()
    if re.search(r"kg|公斤|千克", t):
        return "kg"
    if re.search(r"\blbs?\b|磅|pound", t):
        return "lb"
    if "斤" in t:
        return "jin"
    return None


def _find(headers: list[str], words: tuple[str, ...], exclude: tuple[str, ...] = (), skip: tuple = ()) -> int | None:
    for i, h in enumerate(headers):
        h = h.lower()
        if i not in skip and any(w in h for w in words) and not any(w in h for w in exclude):
            return i
    return None


def _looks_like_data(row: list[str]) -> bool:
    try:
        parse_datetime(row[0])
        parse_weight(row[1])
        return True
    except (ValueError, IndexError):
        return False


def parse(text: str, default_unit: str = "lb", today: dt.date | None = None) -> ImportResult:
    """Read weigh-ins out of CSV text. `default_unit` applies where the file doesn't say."""
    result = ImportResult()
    text = text.lstrip("\ufeff")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [(reader.line_num, row) for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        result.error("文件是空的")
        return result

    first = [c.strip() for c in rows[0][1]]
    header_unit = None
    date_col = _find(first, DATE_WORDS)
    if date_col is None:  # e.g. Renpho's "Time of Measurement"
        date_col = _find(first, TIME_WORDS, ("zone", "时区"))
    weight_col = _find(first, WEIGHT_WORDS, NOT_WEIGHT_WORDS)
    if date_col is not None and weight_col is not None:
        time_col = _find(first, TIME_WORDS, ("zone", "时区"), skip=(date_col,))
        unit_col = _find(first, UNIT_WORDS)
        note_col = _find(first, ("note", "comment", "备注"))
        header_unit = _unit_in(first[weight_col])
        rows = rows[1:]
    elif _looks_like_data(first):
        date_col, weight_col, unit_col, time_col, note_col = 0, 1, 2, None, None
    else:
        result.error("找不到日期列和体重列。第一行需要是表头（例如 date,weight），或者直接是 日期,体重[,单位]")
        return result

    for line, row in rows:
        def cell(i: int | None) -> str:
            return row[i].strip() if i is not None and i < len(row) else ""

        if not cell(weight_col):
            continue  # e.g. a body-fat-only row in a scale app's export
        try:
            date, time = parse_datetime(cell(date_col))
            if cell(time_col):
                time = parse_time(cell(time_col))
            weight, unit = parse_weight(cell(weight_col))
            if unit is None and cell(unit_col):
                unit = UNIT_NAMES.get(cell(unit_col).lower())
                if unit is None:
                    raise ValueError(f"不认识的单位 {cell(unit_col)!r}")
            unit = unit or header_unit or default_unit
            if unit == "jin":
                weight, unit = weight / 2, "kg"
            entry = Entry(date, weight, unit, time, cell(note_col)[:200])
            validate(entry, today)
        except ValueError as e:
            result.error(f"第 {line} 行：{e}")
            continue
        result.entries.append(entry)
    return result


def dump(entries: list[Entry]) -> str:
    """CSV that opens cleanly in Excel (UTF-8 with BOM) and imports back losslessly."""
    out = io.StringIO()
    out.write("\ufeff")
    w = csv.writer(out)
    w.writerow(HEADER)
    for e in entries:
        w.writerow([e.date.isoformat(), e.time or "", f"{e.weight:g}", e.unit, e.note])
    return out.getvalue()
