#!/usr/bin/env python3
"""
parse_praharaj_app_content.py

Reads a SQLite .db file, shows the columns of the table
`praharaj_app_content`, lets you pick which columns you want
(e.g. 4 columns), then exports just those columns to CSV/JSON.

USAGE:
    python parse_praharaj_app_content.py praharaj_app.db

    Optional flags:
    --table TABLE_NAME     (default: praharaj_app_content)
    --out output.csv       (default: <table>_selected.csv)
    --format csv|json      (default: csv)
    --columns col1,col2    (skip the interactive prompt and pass
                            columns directly, comma separated)
"""

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path


def get_columns(cursor, table):
    cursor.execute(f"PRAGMA table_info('{table}')")
    rows = cursor.fetchall()
    if not rows:
        raise ValueError(f"Table '{table}' not found (or has no columns).")
    # PRAGMA table_info returns: cid, name, type, notnull, dflt_value, pk
    return [{"cid": r[0], "name": r[1], "type": r[2]} for r in rows]


def prompt_for_columns(columns):
    print("\nColumns found in the table:\n")
    for col in columns:
        print(f"  [{col['cid']}] {col['name']}  ({col['type']})")

    print(
        "\nWhich columns do you want to parse into your output? "
        "Enter the numbers or names, comma separated."
    )
    print("Example: 0,2,5,7   or   id,title,content,created_at\n")

    raw = input("Your selection: ").strip()
    if not raw:
        print("No selection made, exiting.")
        sys.exit(1)

    picks = [p.strip() for p in raw.split(",") if p.strip()]
    by_index = {str(c["cid"]): c["name"] for c in columns}
    by_name = {c["name"]: c["name"] for c in columns}

    selected = []
    for p in picks:
        if p in by_index:
            selected.append(by_index[p])
        elif p in by_name:
            selected.append(by_name[p])
        else:
            print(f"Warning: '{p}' did not match a column index or name, skipping.")

    if not selected:
        print("None of your entries matched a real column. Exiting.")
        sys.exit(1)

    return selected


def export_rows(cursor, table, columns, out_path, fmt):
    col_list = ", ".join(f'"{c}"' for c in columns)
    cursor.execute(f"SELECT {col_list} FROM '{table}'")
    rows = cursor.fetchall()

    if fmt == "json":
        data = [dict(zip(columns, row)) for row in rows]
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    else:  # csv
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)

    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="Parse selected columns from a SQLite table.")
    parser.add_argument("db_path", help="Path to the .db (SQLite) file")
    parser.add_argument("--table", default="praharaj_app_content", help="Table name")
    parser.add_argument("--out", default=None, help="Output file path")
    parser.add_argument("--format", choices=["csv", "json"], default="csv")
    parser.add_argument(
        "--columns",
        default=None,
        help="Comma-separated column names/indices to skip the interactive prompt",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"File not found: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    try:
        columns = get_columns(cursor, args.table)
    except ValueError as e:
        print(str(e))
        # Helpful: show what tables *do* exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
        print(f"Tables available in this .db: {tables}")
        sys.exit(1)

    if args.columns:
        picks = [p.strip() for p in args.columns.split(",")]
        by_index = {str(c["cid"]): c["name"] for c in columns}
        by_name = {c["name"]: c["name"] for c in columns}
        selected = [by_index.get(p) or by_name.get(p) for p in picks]
        selected = [s for s in selected if s]
        if not selected:
            print("No valid columns given via --columns.")
            sys.exit(1)
    else:
        selected = prompt_for_columns(columns)

    out_path = args.out or f"{args.table}_selected.{args.format}"
    count = export_rows(cursor, args.table, selected, out_path, args.format)

    print(f"\nExported {count} rows, columns: {selected}")
    print(f"Saved to: {out_path}")

    conn.close()


if __name__ == "__main__":
    main()