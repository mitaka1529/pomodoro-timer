"""Loads the translation glossary from glossary.csv (UTF-8 with BOM, editable in Excel).

Columns: 日本語キー (normalized Japanese, as printed in missing_terms.csv), 英語, 備考.
"""
import csv
from pathlib import Path

G = {}
UNCERTAIN_NAMES = set()
with open(Path(__file__).with_name("glossary.csv"), encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        key, en = row["日本語キー"], (row["英語"] or "").strip()
        if key and en:
            G[key] = en
            if "要確認" in (row.get("備考") or ""):
                UNCERTAIN_NAMES.add(key)
