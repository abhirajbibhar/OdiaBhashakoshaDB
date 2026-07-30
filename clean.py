#!/usr/bin/env python3
"""
Clean Praharaj dictionary source files in a directory.
Removes:
  - leading "NNNN," prefixes (e.g. 5197,)
  - <page n="..."> tags (including malformed quote variants)
  - hanging quotes before <entry>

Also reports detailed counts per file and a final summary.
"""

import re
import os
from pathlib import Path
from collections import defaultdict

# ──────────────────────────────────────────────
# CHANGE THESE PATHS
INPUT_DIR  = "./src"          # folder containing the source files
OUTPUT_DIR = "./output"    # where cleaned files will be written
# ──────────────────────────────────────────────

LEADING_NUM   = re.compile(r"^\d+\s*,\s*", re.MULTILINE)
PAGE_TAG      = re.compile(
    r'<page\s+n\s*=\s*["\']*\s*["\']*\s*\d+\s*["\']*\s*["\']*\s*>',
    re.IGNORECASE
)
HANGING_QUOTE = re.compile(r',\s*"\s*(?=<entry>)')

def clean_text(text: str):
    """Return cleaned text + counts of what was removed."""
    num_matches   = LEADING_NUM.findall(text)
    page_matches  = PAGE_TAG.findall(text)
    quote_matches = HANGING_QUOTE.findall(text)

    text = LEADING_NUM.sub("", text)
    text = PAGE_TAG.sub("", text)
    text = HANGING_QUOTE.sub(",", text)
    text = re.sub(r"  +", " ", text)

    return text, {
        "numbers_removed": len(num_matches),
        "pages_removed":   len(page_matches),
        "quotes_fixed":    len(quote_matches),
    }

def main():
    input_path  = Path(INPUT_DIR)
    output_path = Path(OUTPUT_DIR)
    output_path.mkdir(parents=True, exist_ok=True)

    files = sorted([f for f in input_path.iterdir() if f.is_file()])
    if not files:
        print(f"No files found in {INPUT_DIR}")
        return

    print(f"Found {len(files)} file(s) in: {INPUT_DIR}\n")
    print("-" * 70)

    totals = defaultdict(int)
    files_with_changes = 0

    for i, f in enumerate(files, 1):
        try:
            original = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            original = f.read_text(encoding="utf-8", errors="replace")

        cleaned, stats = clean_text(original)

        out_file = output_path / f.name
        out_file.write_text(cleaned, encoding="utf-8")

        changed = any(stats.values())
        if changed:
            files_with_changes += 1

        # per-file report
        status = "CHANGED" if changed else "clean  "
        print(f"[{i:3d}/{len(files)}] {status}  {f.name}")
        if changed:
            print(f"         numbers removed : {stats['numbers_removed']}")
            print(f"         page tags removed: {stats['pages_removed']}")
            print(f"         quotes fixed     : {stats['quotes_fixed']}")
        print()

        for k, v in stats.items():
            totals[k] += v

    # final summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total files processed     : {len(files)}")
    print(f"Files that needed cleaning: {files_with_changes}")
    print(f"Files already clean       : {len(files) - files_with_changes}")
    print()
    print(f"Total leading numbers removed : {totals['numbers_removed']}")
    print(f"Total <page> tags removed     : {totals['pages_removed']}")
    print(f"Total hanging quotes fixed    : {totals['quotes_fixed']}")
    print()
    print(f"Cleaned files written to: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()